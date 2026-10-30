# Catalyst Data Store setup (when console works)

Stage 2 code works **now** with SQLite (`MONITOR_STORE=sqlite`).  
Use this guide when Cloud Scale → Data Store opens, before switching to `MONITOR_STORE=catalyst`.

## Open Data Store

1. Go to [Catalyst Console (IN)](https://console.catalyst.zoho.in)
2. Open project **Device-Monitor**
3. Left menu → **Cloud Scale** (not Serverless)
4. Click **Data Store**
5. If you see Enable / Get started, click it

If it still fails: try another browser, disable blockers, or open  
`https://console.catalyst.zoho.in` → Project overview → Cloud Scale tile.

## Create table `Devices`

Columns (plus auto `ROWID` / timestamps):

| Column | Type | Notes |
|--------|------|--------|
| `device_id` | Text / Var Char | Unique device key (mark unique if offered) |
| `device_name` | Text / Var Char | Display name |
| `last_seen` | Double / Decimal | Unix timestamp |
| `payload` | Text / Large text | Full JSON heartbeat snapshot |

Permissions: allow AppSail / server to **insert + update + read** (Admin/User as required).

## Switch API to Catalyst store (after AppSail deploy)

```bash
export MONITOR_STORE=catalyst
export MONITOR_DEVICES_TABLE=Devices
```

Locally keep:

```bash
export MONITOR_STORE=sqlite
```
