# Device Monitor (Cloud)

Slim FastAPI service for phone heartbeats. Local first → Catalyst AppSail later.

## Stage status

| Stage | Status |
|-------|--------|
| 1 Slim API on :9000 | Done |
| 2 Persistent store | SQLite local + Catalyst `Devices` table ready |
| 3 AppSail deploy | See **DEPLOY.md** (CLI required; Docker optional) |

## Run locally (Stage 2)

```bash
cd cloud-monitor
source .venv/bin/activate
# default is sqlite — data survives restarts
export MONITOR_STORE=sqlite
python main.py
```

- API: http://127.0.0.1:9000  
- Docs: http://127.0.0.1:9000/docs  
- DB file: `cloud-monitor/data/devices.db`

## Verify persistence

```bash
# Terminal A
python main.py

# Terminal B
curl -X POST http://127.0.0.1:9000/api/monitor/register \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"test-1","device_name":"Test Phone","model":"Demo"}'

curl -X POST http://127.0.0.1:9000/api/monitor/heartbeat \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"test-1","active":true,"battery_percent":81}'

curl http://127.0.0.1:9000/health
# expect: {"status":"ok","store":"sqlite",...}

# Stop server (Ctrl+C), start again, then:
curl http://127.0.0.1:9000/api/monitor/devices
# device test-1 should still be listed
```

## Store backends

| `MONITOR_STORE` | Use when |
|-----------------|----------|
| `sqlite` (default) | Local + until Data Store works |
| `memory` | Quick disposable tests |
| `catalyst` | Inside Catalyst AppSail after table exists |

See `DATASTORE_SETUP.md` for creating the Catalyst `Devices` table.
