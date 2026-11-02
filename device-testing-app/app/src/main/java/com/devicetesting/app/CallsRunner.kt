package com.devicetesting.app

import android.os.SystemClock
import android.telephony.TelephonyManager

/**
 * Runs the calls catalog on the phone.
 * Outgoing cases dial the saved number and pass only when the system call log
 * or a new system-log line shows that call. The number is not written into results.
 */
class CallsRunner(
    private val watch: CallWatch,
    private val evidence: CallEvidence,
    private val confirm: (String) -> Boolean,
    private val placeCall: () -> Boolean,
    private val endCall: () -> Boolean,
    private val savedNumber: () -> String,
    private val shouldStop: () -> Boolean,
    private val onStatus: (String) -> Unit,
) {
    fun run(test: TestCase): CaseResult {
        val outcome = try {
            execute(test.id)
        } catch (e: SecurityException) {
            Outcome("BLOCKED", "Phone permission is required")
        } catch (e: Exception) {
            Outcome("FAIL", e.message ?: e.javaClass.simpleName)
        }
        return CaseResult(test.id, test.title, test.suite, outcome.verdict, outcome.detail)
    }

    private fun execute(id: String): Outcome {
        return when (id) {
            "CALL-FUNC-001" -> readiness()
            "CALL-FUNC-002" -> outgoing()
            "CALL-FUNC-003" -> incoming()
            "CALL-FUNC-004" -> answered()
            "CALL-PERF-001" -> setupTiming()
            "CALL-PERF-002" -> blocked("Needs a lab reference phone. This app cannot time the caller's start.")
            "CALL-PERF-003" -> durationCheck()
            "CALL-REL-001" -> repeatedOutgoing()
            "CALL-REL-002" -> holdCall()
            "CALL-REL-003" -> blocked("Needs an approved lab network interruption. Not run on this phone.")
            "CALL-SEC-001" -> permissionDenial()
            "CALL-SEC-002" -> dataMinimization()
            else -> na("No on-phone action is mapped for this case")
        }
    }

    private fun readiness(): Outcome {
        if (!watch.hasTelephony()) return na("This device has no telephony")
        if (!watch.hasPhonePermission()) return blocked("Phone permission is required")
        val subs = watch.subscriptionCount() ?: return blocked("SIM state could not be read")
        val voice = watch.voiceInService() ?: return blocked("Voice service state could not be read")
        if (subs == 0) return blocked("No SIM is installed. This case needs a SIM, so it is blocked instead of failed.")
        if (!voice) return blocked("Voice service is not in service. This is not a call failure.")
        return pass("Active subscriptions: $subs. Voice service is in service.")
    }

    private fun outgoing(): Outcome {
        val placed = dial(holdMs = 0)
        if (placed.verdict != "PASS") return Outcome(placed.verdict, placed.detail)
        return pass("${placed.detail} Off-hook does not prove the other phone answered.")
    }

    private fun incoming(): Outcome {
        val ready = readiness()
        if (ready.verdict != "PASS") return ready
        onStatus("From the other phone, call this device")
        val ringing = watch.await(TelephonyManager.CALL_STATE_RINGING, 90_000, shouldStop)
        if (shouldStop() && !ringing) return unverified("Stopped before ringing")
        if (!ringing) return fail("Ringing was not observed")
        onStatus("Answer or reject the call. This case continues when the phone is idle.")
        var answered = false
        val deadline = SystemClock.elapsedRealtime() + 120_000
        while (SystemClock.elapsedRealtime() < deadline) {
            if (shouldStop()) return unverified("Stopped during the incoming call")
            val state = watch.refresh()
            if (state == TelephonyManager.CALL_STATE_OFFHOOK) answered = true
            if (state == TelephonyManager.CALL_STATE_IDLE) {
                val how = if (answered) "answered" else "rejected"
                return pass("Ringing observed, then the call was $how, then the phone returned to idle.")
            }
            try {
                Thread.sleep(300)
            } catch (_: InterruptedException) {
                return unverified("Stopped during the incoming call")
            }
        }
        return fail("The phone did not return to idle")
    }

    private fun answered(): Outcome {
        val ready = readiness()
        if (ready.verdict != "PASS") return ready
        onStatus("From the other phone, call this device")
        val ringing = watch.await(TelephonyManager.CALL_STATE_RINGING, 90_000, shouldStop)
        if (!ringing) return if (shouldStop()) unverified("Stopped before ringing") else fail("Ringing was not observed")
        onStatus("Answer the call on this phone")
        val offhook = watch.await(TelephonyManager.CALL_STATE_OFFHOOK, 90_000, shouldStop)
        if (shouldStop() && !offhook) return unverified("Stopped before the call was answered")
        if (!offhook) return fail("The call was not answered")
        onStatus("Answer detected. End the call, then choose Pass or Fail.")
        val idle = watch.await(TelephonyManager.CALL_STATE_IDLE, 180_000, shouldStop)
        if (shouldStop() && !idle) return unverified("Stopped before the call ended")
        if (!idle) return fail("The phone did not return to idle")
        val audio = confirm("Could both sides hear each other?")
        if (shouldStop()) return unverified("Stopped during the audio check")
        if (!audio) return fail("Tester did not confirm two-way audio")
        return pass("Ringing, answer, and idle were observed. The tester confirmed two-way audio.")
    }

    private fun setupTiming(): Outcome {
        val placed = dial(holdMs = 0)
        if (placed.verdict != "PASS") return Outcome(placed.verdict, placed.detail)
        return unverified(
            "${placed.detail} No pass limit is configured, so the timing stays not verified. This is not answer time."
        )
    }

    private fun durationCheck(): Outcome {
        val placed = dial(holdMs = 15_000)
        if (placed.verdict != "PASS") return Outcome(placed.verdict, placed.detail)
        val logged = placed.logDurationSec
        if (logged == null) {
            return unverified("${placed.detail} The system call log has no duration, so connected time was not compared.")
        }
        val detail = "${placed.detail} System call log duration is $logged seconds. That is connected time, not the whole off-hook interval."
        return pass(detail)
    }

    private fun repeatedOutgoing(): Outcome {
        var completed = 0
        repeat(CYCLE_COUNT) { index ->
            if (shouldStop()) return unverified("Stopped after $completed of $CYCLE_COUNT calls")
            onStatus("Call ${index + 1} of $CYCLE_COUNT")
            val cycle = outgoing()
            if (cycle.verdict == "BLOCKED" || cycle.verdict == "NOT_APPLICABLE" || cycle.verdict == "NOT_VERIFIED") {
                return cycle
            }
            if (cycle.verdict != "PASS") return fail("Call ${index + 1} was not verified. ${cycle.detail}")
            completed++
            if (index < CYCLE_COUNT - 1) pause(15_000, "Pausing 15 seconds before the next call")
        }
        return pass("Completed $completed of $CYCLE_COUNT calls. Each one is in the system call log.")
    }

    private fun holdCall(): Outcome {
        val placed = dial(holdMs = HOLD_MS)
        if (placed.verdict != "PASS") return Outcome(placed.verdict, placed.detail)
        return pass("${placed.detail} Call state does not prove speech quality.")
    }

    /**
     * Dials the saved number, waits through [holdMs], ends the call, then checks
     * the system call log and new system-log lines.
     */
    private fun dial(holdMs: Long): Placed {
        val ready = readiness()
        if (ready.verdict != "PASS") return Placed(ready.verdict, ready.detail, null)
        if (!watch.hasCallPermission()) {
            return Placed("BLOCKED", "Call permission is required to dial the saved number", null)
        }
        if (!evidence.hasCallLogPermission()) {
            return Placed("BLOCKED", "Call log permission is required to verify the call", null)
        }
        val number = savedNumber()
        if (number.isBlank()) return Placed("BLOCKED", "Save a test number before running this case", null)
        val beforeLog = evidence.logcatSnapshot()
        val since = System.currentTimeMillis()
        val started = SystemClock.elapsedRealtime()
        onStatus("Calling the saved number")
        if (!placeCall()) return Placed("FAIL", "The call could not be started", null)
        val offhook = watch.await(TelephonyManager.CALL_STATE_OFFHOOK, 60_000, shouldStop)
        if (shouldStop() && !offhook) return Placed("NOT_VERIFIED", "Stopped before the call went off-hook", null)
        if (!offhook) return Placed("FAIL", "The call did not go off-hook", null)
        val setupMs = SystemClock.elapsedRealtime() - started
        val wait = stayUntilOtherPhoneRings(beforeLog)
        if (wait.stopped != null) {
            if (watch.refresh() != TelephonyManager.CALL_STATE_IDLE) finishCall()
            return wait.stopped
        }
        if (wait.stillOffHook && holdMs > 0) {
            val held = holdOffHook(holdMs)
            if (held != null) {
                if (watch.refresh() != TelephonyManager.CALL_STATE_IDLE) finishCall()
                return held
            }
        }
        if (wait.stillOffHook && !finishCall()) {
            return Placed("FAIL", "The phone did not return to idle", null)
        }
        val hit = waitForCallLog(number, since, 20_000)
        val logcat = evidence.newLogConfirms(beforeLog, evidence.logcatSnapshot(), number)
        if (hit == null && !logcat) {
            val reason = if (offhook) {
                "The phone went off-hook, but the system call log and system log have no outgoing call to the saved number."
            } else {
                "The call was not placed. The system call log and system log have no outgoing call to the saved number."
            }
            return Placed("FAIL", reason, null)
        }
        val source = when {
            hit != null && logcat -> "the system call log and the system log"
            hit != null -> "the system call log"
            else -> "the system log"
        }
        return Placed(
            "PASS",
            "Dialed the saved number. Verified from $source. Off-hook in $setupMs ms.",
            hit?.durationSec,
        )
    }

    /**
     * Keeps the outgoing call up until the other phone has time to ring.
     * A short idle gap while dialing is ignored. Hanging up in that gap is what
     * disconnected the call locally on the Nexus 6P before the other phone rang.
     * If the other phone answers and ends the call, this returns without hanging up.
     */
    private fun stayUntilOtherPhoneRings(beforeLog: String): RingWait {
        val started = SystemClock.elapsedRealtime()
        var alertedAt = 0L
        var offHookMs = 0L
        var idleMs = 0L
        var nextLogCheck = started
        while (true) {
            if (shouldStop()) {
                return RingWait(Placed("NOT_VERIFIED", "Stopped before the other phone could ring", null), false)
            }
            val now = SystemClock.elapsedRealtime()
            val state = watch.refresh()
            if (state == TelephonyManager.CALL_STATE_IDLE) {
                idleMs += 1_000
                val endedByTheOtherSide = offHookMs >= 3_000 && idleMs >= 5_000
                if (endedByTheOtherSide) {
                    onStatus("Call finished. Checking the system call log.")
                    return RingWait(null, false)
                }
            } else {
                offHookMs += 1_000
                idleMs = 0
            }
            if (alertedAt == 0L && now >= nextLogCheck) {
                nextLogCheck = now + 2_000
                if (evidence.sawNewAlerting(beforeLog)) alertedAt = now
            }
            val rangLongEnough = alertedAt > 0L && now - alertedAt >= RING_AFTER_ALERT_MS && offHookMs >= 3_000
            val gaveTheNetworkTime = offHookMs >= MIN_RING_MS
            if (rangLongEnough || gaveTheNetworkTime) {
                return RingWait(null, watch.refresh() != TelephonyManager.CALL_STATE_IDLE)
            }
            val left = if (alertedAt > 0L) {
                ((RING_AFTER_ALERT_MS - (now - alertedAt)) / 1000).coerceAtLeast(0)
            } else {
                ((MIN_RING_MS - offHookMs) / 1000).coerceAtLeast(0)
            }
            onStatus(
                if (alertedAt > 0L) "Other phone is ringing, $left seconds"
                else "Waiting for the other phone to ring, $left seconds"
            )
            try {
                Thread.sleep(1000)
            } catch (_: InterruptedException) {
                return RingWait(Placed("NOT_VERIFIED", "Stopped before the other phone could ring", null), false)
            }
        }
    }

    private fun holdOffHook(holdMs: Long): Placed? {
        val holdUntil = SystemClock.elapsedRealtime() + holdMs
        var idleSamples = 0
        while (SystemClock.elapsedRealtime() < holdUntil) {
            if (shouldStop()) return Placed("NOT_VERIFIED", "Stopped during the call", null)
            if (watch.refresh() == TelephonyManager.CALL_STATE_IDLE) {
                idleSamples++
                if (idleSamples >= 2) return Placed("FAIL", "Call state changed during the call", null)
            } else {
                idleSamples = 0
            }
            val left = ((holdUntil - SystemClock.elapsedRealtime()) / 1000).coerceAtLeast(0)
            onStatus("On the call, $left seconds left")
            try {
                Thread.sleep(1000)
            } catch (_: InterruptedException) {
                return Placed("NOT_VERIFIED", "Stopped during the call", null)
            }
        }
        return null
    }

    private fun finishCall(): Boolean {
        if (watch.refresh() == TelephonyManager.CALL_STATE_IDLE) return true
        onStatus("Ending the call")
        val ended = endCall()
        if (!ended) {
            val manual = confirm("The app could not end the call. End it, then tap Pass.")
            if (!manual) return false
        }
        return watch.await(TelephonyManager.CALL_STATE_IDLE, 60_000, shouldStop)
    }

    private fun waitForCallLog(number: String, sinceMs: Long, timeoutMs: Long): CallEvidence.Hit? {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            if (shouldStop()) return evidence.outgoingSince(number, sinceMs)
            evidence.outgoingSince(number, sinceMs)?.let { return it }
            try {
                Thread.sleep(500)
            } catch (_: InterruptedException) {
                return evidence.outgoingSince(number, sinceMs)
            }
        }
        return evidence.outgoingSince(number, sinceMs)
    }

    private fun permissionDenial(): Outcome {
        val handled = watch.exerciseDeniedPath()
        if (!handled) return fail("The denied-permission path crashed or still read call state.")
        val missing = watch.missingPermissions()
        val permissionNote = if (missing.isEmpty()) {
            "The system permission was left granted."
        } else {
            "Missing ${missing.joinToString(", ")} permission."
        }
        return pass("Denied phone access was handled without crashing or placing a call. $permissionNote No SIM is required.")
    }

    private fun dataMinimization(): Outcome {
        val detail = "The system call log is read only to verify placement. This result does not include the saved number."
        if (Regex("\\+?\\d{7,}").containsMatchIn(detail)) return fail("Result text contains a phone number")
        return pass(detail)
    }

    private fun pause(ms: Long, status: String) {
        val until = SystemClock.elapsedRealtime() + ms
        while (SystemClock.elapsedRealtime() < until) {
            if (shouldStop()) return
            onStatus(status)
            try {
                Thread.sleep(1000)
            } catch (_: InterruptedException) {
                return
            }
        }
    }

    private fun pass(detail: String) = Outcome("PASS", detail)
    private fun fail(detail: String) = Outcome("FAIL", detail)
    private fun blocked(detail: String) = Outcome("BLOCKED", detail)
    private fun na(detail: String) = Outcome("NOT_APPLICABLE", detail)
    private fun unverified(detail: String) = Outcome("NOT_VERIFIED", detail)

    private data class Outcome(val verdict: String, val detail: String)

    private data class Placed(val verdict: String, val detail: String, val logDurationSec: Int?)

    private data class RingWait(val stopped: Placed?, val stillOffHook: Boolean)

    companion object {
        const val CYCLE_COUNT = 3
        const val HOLD_MS = 300_000L
        const val MIN_RING_MS = 35_000L
        const val RING_AFTER_ALERT_MS = 15_000L
    }
}
