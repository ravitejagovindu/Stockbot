# StockBot paper BFF (backend for the Android app)

A small, **read-only** FastAPI service in `bff\`. It reads the paper account that the daily job writes and serves it to the StockBot Paper Android app as JSON, exactly as the frozen contract describes (`docs\android\contract\`, apiVersion 1). It adds nothing to the job: no existing Python file was changed to build it.

## What it is and is not

* **Read-only.** Every SQLite connection to `finsight.db` and `state\live_state.db` is opened with a read-only URI (`file:...?mode=ro`) and `PRAGMA query_only=ON`, used for one read and closed (no connection is held between requests). A write through such a connection raises an error (a test proves it).
* **No endpoint writes, places an order or touches a broker.** There are six GET endpoints and nothing else (other methods answer 405). No broker key exists anywhere.
* **No locks.** It never reads or writes the lock files and never takes a run lock. If a database is busy (the 19:30 job is writing) it waits 3 s, retries once, then answers `503 NOT_READY`: never a partial result.
* **No background work.** No threads of its own, no scheduler, no timers. It only does something when a request arrives. It is safe to kill at any time.
* **Not the old app.** Never start it together with `stockbot\live\main.py`: that app starts the old scheduler (`stockbot\live\scheduler.py`), and two schedulers must never run the paper step. The BFF imports neither.

## Endpoints (header `X-Paper-Token` on every call)

| Call | Answers |
|---|---|
| `GET /v1/health` | status (`ok` or `not_ready`), server time, latest sealed data date |
| `GET /v1/today` | the newest ticket list: tickets, blocked, pending sells, signal-day flag |
| `GET /v1/account` | equity, returns against Nifty, daily curve, drawdowns, review marks |
| `GET /v1/positions` | open positions and cash |
| `GET /v1/trades` | closed trades, newest first, with the footer figures |
| `GET /v1/job` | (v1.1) the daily job's status: the scheduler service on or off, today's state, the last 10 days, the last 20 attempts |

A wrong or missing token gives `401` with `{"apiVersion":"1","error":{"code":"UNAUTHORIZED","message":"..."}}`; data not available gives `503 NOT_READY`; anything else `500 SERVER_ERROR`; an unknown route `404`. The contract (`docs\android\contract\CONTRACT.md`) is the reference for every field.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `STOCKBOT_BFF_HOST` | `127.0.0.1` | address to bind (`start_bff.ps1` sets the Tailscale address) |
| `STOCKBOT_BFF_PORT` | `8765` | port (it must be free; `run.py` refuses to start otherwise) |
| `STOCKBOT_BFF_ALLOWED_HOSTS` | `localhost,127.0.0.1` | accepted `Host` headers (a wrong one gets 400); `start_bff.ps1` adds the Tailscale address and name |
| `STOCKBOT_BFF_CORS` | none | allowed origins; unset = no CORS at all (the app is native) |
| `STOCKBOT_BFF_TOKEN` | none | the access token (else the token file below) |
| `STOCKBOT_DATA_ROOT` | `F:\Projects\Ravi\StockBotData` | where `daily\calendar.csv`, `logs\bff.log` and `bff\token.txt` live |
| `STOCKBOT_STATE_DB`, `STOCKBOT_DB`, `STOCKBOT_TICKETS_DIR` | as `stockbot.config.paths` | state database, lake, tickets folder |

The review marks (35 percent drawdown, 30 closed trades, the verdict) are in `bff\paper_marks.yaml`; the risk per trade is read from `stockbot\config\shared.yaml`.

## The token

* It is read from `STOCKBOT_BFF_TOKEN`, else from the first line of `F:\Projects\Ravi\StockBotData\bff\token.txt` (outside the repository, never committed). With neither, the BFF **refuses to start** (exit 2).
* It is compared in constant time, never printed, never logged, never in an error message.
* To create it once (32 random bytes as hex) without printing it:
  `py -3 -c "import secrets,pathlib; p=pathlib.Path(r'F:\Projects\Ravi\StockBotData\bff\token.txt'); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(secrets.token_hex(32)+'\n')"`
  To rotate it, replace the file and restart the BFF. Copy it to the phone yourself when stage 4 needs it.

## Start and stop (the scripts)

```powershell
powershell -ExecutionPolicy Bypass -File F:\Projects\Ravi\StockBot\bff\start_bff.ps1      # start
powershell -ExecutionPolicy Bypass -File F:\Projects\Ravi\StockBot\bff\start_bff.ps1 -Status   # is it running?
powershell -ExecutionPolicy Bypass -File F:\Projects\Ravi\StockBot\bff\stop_bff.ps1       # stop
```

`start_bff.ps1` finds the laptop's Tailscale IPv4 address and MagicDNS name itself (`tailscale ip -4`, `tailscale status --json`), sets `STOCKBOT_BFF_HOST` to the Tailscale address (never all interfaces) and `STOCKBOT_BFF_ALLOWED_HOSTS` to `<tailscale ip>, <magicdns name>, localhost, 127.0.0.1`, port 8765, and starts `bff\run.py` in a **new, minimized, detached window** (Python 3.13 at `C:\Users\ravit\AppData\Local\Programs\Python\Python313\python.exe`, working directory the main folder), like the scheduler service. It refuses to start a second copy (exit 2) or when the port is in use (exit 3), and prints the pid, the address and the log path (never the token). `stop_bff.ps1` stops only the python process whose command line is `bff\run.py`.

The BFF does **not** survive a reboot or a Tailscale restart; start it again with the script. Because it binds only to the Tailscale address, `http://127.0.0.1:8765` is not served; test with the Tailscale address (`py -3 bff\smoke.py --base-url http://100.125.195.111:8765`).

To run it by hand instead (for example for a different port): set the environment variables above, then `py -3 bff\run.py` in its own window; Ctrl+C stops it. Exit codes of `run.py`: 2 no token, 3 port busy. Never run it together with `stockbot\live\main.py`.

### Firewall

No new rule was needed: Tailscale's own inbound allow rules ("Tailscale-In", Domain and Private profiles, any port, local address = the Tailscale address) already cover TCP 8765 on the Tailscale interface. The equivalent single rule, if ever needed, is in `docs\android\CONNECTION.md`.

### Rotating the token

Stop the BFF, delete `F:\Projects\Ravi\StockBotData\bff\token.txt`, create a new one (command above, "The token"), start the BFF with the script, then paste the new token into the phone's Connection screen. The old token stops working at once.

## Logs

`F:\Projects\Ravi\StockBotData\logs\bff.log`: rotating (1 MB x 5), one line per request (client, method, path without query, status, milliseconds). Headers are never logged, so the token cannot appear. An unexpected error logs only the exception type.

## How it works in one paragraph

On a request it reads the journal of `live_state.db` (every processed session), folds it session by session into positions, cash, closed trades and a daily equity curve (open positions marked at that day's lake close), reads the Nifty closes and the sealed-through date from the lake, and builds the response in whole paise. Responses are cached on (mtime and size of `live_state.db`, the lake's sealed-through date); the envelope's `expectedAsOf` and `generatedAt` are refreshed on every request. The choices behind each field are in `docs\bff\STAGE3_REPORT.md`.

## Tests

`py -m pytest tests\bff` (no network; temporary files only; never the real state or lake).

## Roll-back

Delete the folder `bff\` (and `tests\bff\`, `docs\bff\`). Nothing else depends on it: no existing file was changed except two added rows in `docs\guides\CODEBASE_GUIDE.md`, and the daily job, the scheduler service and the paper state are untouched. Stop the BFF first (Ctrl+C), and delete `F:\Projects\Ravi\StockBotData\bff\token.txt` if you no longer want the token.

## `GET /v1/job` (v1.1, stage 5): the daily job's status

Read-only, like everything else here. It shows what the scheduler service (`scripts\scheduler_service.py`, the 19:30 IST job and the 08:30 catch-up) did; there is no way to start, retry or stop anything through it.

It reads, and never writes: `F:\Projects\Ravi\StockBotData\logs\scheduler_service.log` (and its rotated files `.1` to `.5`), the service's instance file `locks\scheduler_service.pid` (pid and start time), the **existence** (never the content) of `locks\daily_update.lock`, the lake's sealed date (the same read as `/v1/health`) and `daily\calendar.csv`. A missing or half-written log, an unknown line or garbage never gives a 500: unreadable lines are skipped, and a log with no usable line answers `503 NOT_READY`.

State rules (first match wins): `DONE` an attempt ended with exit 0; `RUNNING` (today) an attempt began with no result yet, or the data job's lock file exists; `NO_FILE` the service stopped with its ALERT line and the last exit was 3 (the NSE never published a file, probably a holiday); `ALERT` the service stopped with its ALERT line for another reason (for example a stale lock, exit 5), or a past weekday with no final answer; `RETRYING` (today) the last decision was a retry, with the logged next attempt time; `WEEKEND` Saturday or Sunday without a DONE; `WAITING` a weekday before 19:30 with no attempt yet. The full table is in `docs\android\contract\CONTRACT.md`.

**The BFF that is already running was started before this endpoint existed: it needs a restart to serve `/v1/job`** (`stop_bff.ps1`, then `start_bff.ps1`, once this change is merged; or `Stop-Process` on the BFF pid and start it again). The other five endpoints are unchanged.
