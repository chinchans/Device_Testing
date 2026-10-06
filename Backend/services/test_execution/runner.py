"""Runs generated test scripts on a device one at a time and streams their progress as events.

Each execution lives in <script set>/executions/<execution id>/:
  execution.json   record (settings, per-case status and verdicts), rewritten on every change
  events.jsonl     every streamed event, replayed for finished executions
  <case>.log       the script's stderr
  <case>/          the script's --out directory (result JSON + evidence files)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from observability.logging import logger
from services.test_execution import devices, reports
from services.test_execution.script_sets import clean_product_name, run_dir, script_set_detail
from services.test_scripts.generator import OUTPUT_ROOT

_EXEC_ID = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{4}$")
_LOG_LINE = re.compile(r"^\[(\d\d:\d\d:\d\d)\] (.*)$")
_SLA = re.compile(r"^sla: (\S+) = (.*?) \(target (\S+) (.*?)\) (ok|FAIL)$")
_OP_START = re.compile(r"^op\[(\w+)\]: ([A-Za-z]\w*) (\{.*\})$")
_OP_END = re.compile(r"^op\[(\w+)\]: (PASS|FAIL|NOT_APPLICABLE|SKIPPED|BLOCKED_PRECONDITION|HARNESS_ERROR)\b ?(.*)$")
_MANUAL = re.compile(r"^MANUAL: (.*)$")
_METRIC = re.compile(r"^metric (\S+) = (.*)$")
_ACTIVE_STATES = {"queued", "running", "pausing", "paused", "stopping"}
STOP_GRACE_S = 90
HEALTH_INTERVAL_S = 15
MAX_LOG_CHARS = 400_000


class ExecutionError(ValueError):
    """The execution request cannot be started as given."""


class ExecutionNotFound(LookupError):
    """No execution with that id."""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _duration(start: str | None, end: str | None) -> float | None:
    try:
        return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 1)
    except (TypeError, ValueError):
        return None


class Execution:
    """One queued/running execution; the record is mirrored to execution.json."""

    def __init__(self, record: dict[str, Any], exec_dir: Path, script_dir: Path) -> None:
        self.record = record
        self.dir = exec_dir
        self.script_dir = script_dir
        self.cond = threading.Condition()
        self._save_lock = threading.Lock()
        self.events: list[dict[str, Any]] = []
        self.seq = 0
        self.proc: subprocess.Popen[str] | None = None
        self.interrupt: str | None = None
        self.stop_requested = False
        self.pause_requested = False
        self.done = threading.Event()

    def emit(self, type_: str, **data: Any) -> None:
        with self.cond:
            self.seq += 1
            event = {"seq": self.seq, "t": _now(), "type": type_, **data}
            self.events.append(event)
            with (self.dir / "events.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
            self.cond.notify_all()

    def save(self) -> None:
        # Control requests, the health sampler and the worker thread all save the same record.
        with self._save_lock:
            tmp = self.dir / f"execution.json.{threading.get_ident()}.tmp"
            tmp.write_text(json.dumps(self.record, indent=2), encoding="utf-8")
            tmp.replace(self.dir / "execution.json")

    def set_state(self, state: str) -> None:
        self.record["state"] = state
        self.save()
        self.emit("state", state=state)


class ExecutionManager:
    def __init__(self) -> None:
        self._active: dict[str, Execution] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ lifecycle

    def start(self, run_id: str, case_ids: list[str], serial: str, *,
              overrides: dict[str, str] | None = None,
              case_overrides: dict[str, dict[str, str]] | None = None,
              case_timeout_min: float = 60) -> dict[str, Any]:
        script_dir = run_dir(run_id)
        detail = script_set_detail(run_id)
        by_id = {c["case_id"]: c for c in detail["cases"]}
        ids = [c for c in dict.fromkeys(case_ids) if c]
        unknown = [c for c in ids if c not in by_id]
        if not ids:
            raise ExecutionError("select at least one test case")
        if unknown:
            raise ExecutionError(f"not in script set {run_id}: {', '.join(unknown)}")
        try:
            online = devices.online_serials()
        except devices.AdbUnavailable as exc:
            raise ExecutionError(str(exc)) from exc
        if serial not in online:
            raise ExecutionError(f"device {serial} is not online")
        with self._lock:
            busy = next((e for e in self._active.values()
                         if e.record["serial"] == serial and e.record["state"] in _ACTIVE_STATES), None)
            if busy:
                raise ExecutionError(f"device {serial} is busy with execution {busy.record['id']}")

            exec_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
            exec_dir = script_dir / "executions" / exec_id
            exec_dir.mkdir(parents=True)
            info = devices.device_info(serial)
            record = {
                "id": exec_id,
                "run_id": run_id,
                "feature": detail["feature"],
                "product_name": detail.get("product_name"),
                "serial": serial,
                "device": {k: info.get(k) for k in ("manufacturer", "model", "android_version", "sdk_int",
                                                    "fingerprint", "is_emulator")},
                "health": info.get("health"),
                "overrides": {k: str(v) for k, v in (overrides or {}).items() if str(k).strip()},
                "case_overrides": {cid: {k: str(v) for k, v in vs.items()}
                                   for cid, vs in (case_overrides or {}).items() if cid in ids},
                "case_timeout_min": case_timeout_min,
                "state": "queued",
                "created_at": _now(),
                "started_at": None,
                "finished_at": None,
                "current_case": None,
                "cases": [{
                    "case_id": cid,
                    "name": by_id[cid]["name"],
                    "category": by_id[cid]["category"],
                    "execution": by_id[cid]["execution"],
                    "filename": by_id[cid]["filename"],
                    "spec_values": by_id[cid]["spec_values"],
                    "estimate_s": by_id[cid]["estimate_s"],
                    "status": "pending",
                    "verdict": None,
                    "reason": "",
                } for cid in ids],
            }
            ex = Execution(record, exec_dir, script_dir)
            ex.save()
            self._active[exec_id] = ex
        threading.Thread(target=self._run, args=(ex,), name=f"exec-{exec_id}", daemon=True).start()
        return record

    def control(self, exec_id: str, action: str) -> dict[str, Any]:
        ex = self._active.get(exec_id)
        if ex is None or ex.record["state"] not in _ACTIVE_STATES:
            raise ExecutionError("execution is not running")
        if action == "stop":
            ex.stop_requested = True
            with ex.cond:
                ex.cond.notify_all()
            ex.set_state("stopping")
            self._interrupt(ex, "stopped by user")
        elif action == "skip":
            if not ex.record.get("current_case"):
                raise ExecutionError("no case is running")
            self._interrupt(ex, "skipped by user")
        elif action == "pause":
            ex.pause_requested = True
            if ex.record["state"] == "running":
                ex.set_state("pausing")
        elif action == "resume":
            ex.pause_requested = False
            with ex.cond:
                ex.cond.notify_all()
            if ex.record["state"] in ("pausing", "paused"):
                ex.set_state("running")
        else:
            raise ExecutionError(f"unknown action {action!r}")
        return ex.record

    def _interrupt(self, ex: Execution, why: str) -> None:
        proc = ex.proc
        if proc is None or proc.poll() is not None:
            return
        ex.interrupt = why
        try:
            proc.send_signal(signal.SIGINT)
        except ProcessLookupError:
            return

        def kill() -> None:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        threading.Timer(STOP_GRACE_S, kill).start()

    # --------------------------------------------------------------- worker

    def _run(self, ex: Execution) -> None:
        rec = ex.record
        rec["started_at"] = _now()
        ex.set_state("running")
        ex.emit("execution_start", total=len(rec["cases"]), serial=rec["serial"])
        threading.Thread(target=self._health_loop, args=(ex,), daemon=True).start()
        crashed = False
        try:
            for index, case in enumerate(rec["cases"]):
                with ex.cond:
                    while ex.pause_requested and not ex.stop_requested:
                        if rec["state"] != "paused":
                            rec["state"] = "paused"
                            ex.save()
                            ex.emit("state", state="paused")
                        ex.cond.wait(1)
                if ex.stop_requested:
                    break
                if rec["state"] in ("paused", "pausing") and not ex.pause_requested:
                    ex.set_state("running")
                self._run_case(ex, case, index)
        except Exception as exc:  # the record must always be closed
            logger.exception("execution %s crashed", rec["id"])
            crashed = True
            ex.emit("log", case_id=rec.get("current_case"), text=f"runner error: {exc}", level="error")
        finally:
            for case in rec["cases"]:
                if case["status"] in ("pending", "running"):
                    case["status"] = "cancelled"
            rec["current_case"] = None
            rec["finished_at"] = _now()
            rec["state"] = "interrupted" if crashed else "stopped" if ex.stop_requested else "finished"
            rec["summary"] = reports.summarize(rec)
            ex.save()
            ex.emit("execution_end", state=rec["state"], summary=rec["summary"])
            ex.done.set()

    def _run_case(self, ex: Execution, case: dict[str, Any], index: int) -> None:
        rec = ex.record
        cid = case["case_id"]
        case.update(status="running", started_at=_now())
        rec["current_case"] = cid
        ex.save()
        ex.emit("case_start", case_id=cid, name=case["name"], index=index, total=len(rec["cases"]))

        out_dir = ex.dir / cid
        variables = {**rec["overrides"], **rec["case_overrides"].get(cid, {})}
        cmd = [sys.executable, "-u", str(ex.script_dir / case["filename"]),
               "--serial", rec["serial"], "--out", str(out_dir)]
        for name, value in variables.items():
            cmd += ["--var", f"{name}={value}"]
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "ANDROID_SERIAL": rec["serial"]}
        ex.interrupt = None
        proc = subprocess.Popen(cmd, cwd=ex.script_dir, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, errors="replace", bufsize=1, env=env,
                                start_new_session=True)
        ex.proc = proc
        stdout: list[str] = []
        reader = threading.Thread(target=lambda: stdout.extend(proc.stdout or []), daemon=True)
        reader.start()
        timeout_s = max(1.0, float(rec.get("case_timeout_min") or 60) * 60)
        timer = threading.Timer(timeout_s, self._interrupt, (ex, f"timed out after {timeout_s / 60:g} min"))
        timer.start()
        tail: list[str] = []
        with (ex.dir / f"{cid}.log").open("w", encoding="utf-8") as log:
            for line in proc.stderr or []:
                log.write(line)
                log.flush()
                line = line.rstrip("\n")
                tail = (tail + [line])[-15:]
                self._emit_log(ex, cid, line)
        proc.wait()
        timer.cancel()
        reader.join(5)
        ex.proc = None

        verdict, reason, result_file = None, "", None
        for line in reversed(stdout):
            try:
                summary = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(summary, dict) and summary.get("verdict"):
                verdict, reason = summary["verdict"], summary.get("reason") or ""
                result_file = summary.get("result_file")
                break
        if ex.interrupt:
            timed_out = ex.interrupt.startswith("timed out")
            verdict, reason = ("ERROR" if timed_out else "STOPPED"), ex.interrupt
        elif verdict is None:
            verdict = "ERROR"
            reason = f"script exited with code {proc.returncode} without a verdict: " + " | ".join(tail[-3:])

        result = self._load_result(result_file, out_dir, cid)
        checks = result.get("checks") or []
        case.update(
            status="done",
            verdict=verdict,
            reason=reason,
            finished_at=_now(),
            exit_code=proc.returncode,
            result_file=f"{cid}/{cid}_result.json" if result else None,
            log_file=f"{cid}.log",
            checks_total=len(checks),
            failed_checks=[{k: c.get(k) for k in ("description", "expected", "actual", "target", "operator")}
                           for c in checks if not c.get("passed")][:20],
            manual_steps=len(result.get("manual_steps") or []),
        )
        case["duration_s"] = _duration(case["started_at"], case["finished_at"])
        case["cause"] = reports.classify(case)
        rec["current_case"] = None
        ex.save()
        ex.emit("case_end", case_id=cid, verdict=verdict, reason=reason, cause=case["cause"],
                duration_s=case["duration_s"], index=index)

    @staticmethod
    def _load_result(result_file: str | None, out_dir: Path, cid: str) -> dict[str, Any]:
        for path in filter(None, [Path(result_file) if result_file else None, out_dir / f"{cid}_result.json"]):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
        return {}

    def _emit_log(self, ex: Execution, cid: str, line: str) -> None:
        m = _LOG_LINE.match(line)
        msg = m.group(2) if m else line
        level = "info"
        if (s := _SLA.match(msg)):
            level = "metric"
            ex.emit("metric", case_id=cid, key=s.group(1), actual=s.group(2), operator=s.group(3),
                    target=s.group(4), passed=s.group(5) == "ok")
        elif (s := _METRIC.match(msg)):
            level = "metric"
            ex.emit("metric", case_id=cid, key=s.group(1), actual=s.group(2), operator=None, target=None,
                    passed=None)
        elif (s := _MANUAL.match(msg)):
            level = "manual"
            ex.emit("manual", case_id=cid, text=s.group(1))
        elif (s := _OP_END.match(msg)):
            level = "op_fail" if s.group(2) in ("FAIL", "HARNESS_ERROR") else "op"
        elif _OP_START.match(msg):
            level = "op"
        elif msg.startswith(("host:", "sh:")):
            level = "cmd"
        elif re.search(r"Traceback|Error|Exception", msg):
            level = "error"
        ex.emit("log", case_id=cid, time=m.group(1) if m else None, text=msg, level=level)

    def _health_loop(self, ex: Execution) -> None:
        while not ex.done.wait(HEALTH_INTERVAL_S):
            try:
                h = devices.health(ex.record["serial"])
            except Exception:  # health sampling is best-effort
                continue
            ex.record["health"] = h
            ex.emit("health", **h)

    # -------------------------------------------------------------- queries

    def _find(self, exec_id: str) -> tuple[Execution | None, Path]:
        if not _EXEC_ID.match(exec_id or ""):
            raise ExecutionNotFound(exec_id)
        ex = self._active.get(exec_id)
        if ex is not None:
            return ex, ex.dir
        found = next(OUTPUT_ROOT.glob(f"*/executions/{exec_id}/execution.json"), None)
        if found is None:
            raise ExecutionNotFound(exec_id)
        return None, found.parent

    def record(self, exec_id: str) -> dict[str, Any]:
        ex, path = self._find(exec_id)
        if ex is not None:
            rec = ex.record
        else:
            rec = json.loads((path / "execution.json").read_text(encoding="utf-8"))
            if rec.get("state") in _ACTIVE_STATES:
                rec["state"] = "interrupted"
                for case in rec.get("cases") or []:
                    if case.get("status") in ("pending", "running"):
                        case["status"] = "cancelled"
                (path / "execution.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        for case in rec.get("cases") or []:
            case["cause"] = reports.classify(case)
        return {**rec, "product_name": clean_product_name(rec.get("product_name")),
                "summary": reports.summarize(rec)}

    def delete(self, exec_id: str) -> None:
        ex, path = self._find(exec_id)
        if ex is not None and ex.record["state"] in _ACTIVE_STATES:
            raise ExecutionError("stop the execution before deleting it")
        with self._lock:
            self._active.pop(exec_id, None)
        shutil.rmtree(path)

    def list(self, run_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        pattern = f"{run_id}/executions/*/execution.json" if run_id else "*/executions/*/execution.json"
        ids = sorted((p.parent.name for p in OUTPUT_ROOT.glob(pattern)), reverse=True)[:limit]
        out = []
        for exec_id in ids:
            try:
                rec = self.record(exec_id)
            except (ExecutionNotFound, OSError, json.JSONDecodeError):
                continue
            out.append({k: rec.get(k) for k in ("id", "run_id", "feature", "product_name", "serial", "device",
                                                 "state", "created_at", "started_at", "finished_at",
                                                 "overrides", "summary")})
        return out

    def wait_events(self, exec_id: str, after: int, timeout: float = 10) -> tuple[list[dict[str, Any]], bool]:
        """Events with seq > after (blocking up to timeout for new ones) and whether the stream is over."""
        ex, path = self._find(exec_id)
        if ex is None:
            events = []
            log = path / "events.jsonl"
            if log.is_file():
                for line in log.read_text(encoding="utf-8").splitlines():
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("seq", 0) > after:
                        events.append(event)
            return events, True
        with ex.cond:
            if ex.seq <= after and not ex.done.is_set():
                ex.cond.wait(timeout)
            events = [e for e in ex.events if e["seq"] > after]
            return events, ex.done.is_set() and not events

    def case_detail(self, exec_id: str, case_id: str) -> dict[str, Any]:
        rec = self.record(exec_id)
        case = next((c for c in rec["cases"] if c["case_id"] == case_id), None)
        if case is None:
            raise ExecutionNotFound(f"{exec_id}/{case_id}")
        _, path = self._find(exec_id)
        out_dir = path / case_id
        result = self._load_result(None, out_dir, case_id)
        log_path = path / f"{case_id}.log"
        log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
        files = sorted(({"name": f.name, "size": f.stat().st_size} for f in out_dir.iterdir() if f.is_file()),
                       key=lambda f: f["name"]) if out_dir.is_dir() else []
        spec_check = None
        if case.get("cause") == "spec_mismatch":
            siblings = [self._load_result(None, path / c["case_id"], c["case_id"]) for c in rec["cases"]]
            spec_check = reports.spec_comparison(case, result, siblings)
        return {"execution_id": exec_id, "run_id": rec["run_id"], "case": case, "result": result,
                "spec_check": spec_check,
                "log": log[-MAX_LOG_CHARS:], "log_truncated": len(log) > MAX_LOG_CHARS, "files": files,
                "overrides": {**rec.get("overrides", {}), **rec.get("case_overrides", {}).get(case_id, {})},
                "blocked_hint": reports.blocked_hint(case.get("reason") or "")
                if case.get("verdict") == "BLOCKED_PRECONDITION" else None}

    def case_file(self, exec_id: str, case_id: str, name: str) -> Path:
        _, path = self._find(exec_id)
        target = (path / case_id / name).resolve()
        if target.parent != (path / case_id).resolve() or not target.is_file():
            raise ExecutionNotFound(f"{exec_id}/{case_id}/{name}")
        return target

    def review(self, exec_id: str, case_id: str, decision: str, note: str = "") -> dict[str, Any]:
        if decision not in ("PASS", "FAIL"):
            raise ExecutionError("decision must be PASS or FAIL")
        ex, path = self._find(exec_id)
        rec = ex.record if ex is not None else json.loads((path / "execution.json").read_text(encoding="utf-8"))
        case = next((c for c in rec["cases"] if c["case_id"] == case_id), None)
        if case is None:
            raise ExecutionNotFound(f"{exec_id}/{case_id}")
        if case.get("verdict") != "MANUAL_REVIEW":
            raise ExecutionError(f"{case_id} is {case.get('verdict')}, not MANUAL_REVIEW")
        case["review"] = {"decision": decision, "note": note.strip(), "at": _now()}
        case["cause"] = reports.classify(case)
        if rec.get("state") not in _ACTIVE_STATES:
            rec["summary"] = reports.summarize(rec)
        if ex is not None:
            ex.save()
        else:
            (path / "execution.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        return case

    def result_details(self, exec_id: str) -> dict[str, dict[str, Any]]:
        _, path = self._find(exec_id)
        rec = self.record(exec_id)
        return {c["case_id"]: self._load_result(None, path / c["case_id"], c["case_id"]) for c in rec["cases"]}


manager = ExecutionManager()
