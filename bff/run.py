"""Start the StockBot paper BFF (read-only). Run it in its own PowerShell window, like the scheduler service:

    cd F:\\Projects\\Ravi\\StockBot
    py -3 bff\\run.py

Settings come from environment variables (see bff/config.py). Without a token (STOCKBOT_BFF_TOKEN or F:\\Projects\\Ravi\\StockBotData\\bff\\token.txt) it refuses to start (exit 2). If the port is taken
it exits 3. Ctrl+C stops it; it is safe to kill at any time (it only reads). Never run it together with stockbot\\live\\main.py (that app starts the old scheduler)."""
from __future__ import annotations

import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bff.config import TokenMissing, load_settings  # noqa: E402


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def main() -> int:
    try:
        settings = load_settings()
    except TokenMissing as exc:
        print(f"REFUSED: {exc}")
        return 2
    if not port_is_free(settings.host, settings.port):
        print(f"REFUSED: {settings.host}:{settings.port} is already in use (set STOCKBOT_BFF_PORT to another port)")
        return 3
    import uvicorn
    from bff.app import create_app, setup_access_log

    setup_access_log(settings.log_file)
    app = create_app(settings)
    from datetime import date
    from bff.builders import default_signal_fn
    default_signal_fn((date(2026, 1, 1), date(2026, 1, 2)))          # loads the repository's own signal-day function now (about 9 s), so the first request is not slow
    print(f"StockBot paper BFF (read-only) listening on http://{settings.host}:{settings.port}  log: {settings.log_file}", flush=True)
    uvicorn.run(app, host=settings.host, port=settings.port, access_log=False, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
