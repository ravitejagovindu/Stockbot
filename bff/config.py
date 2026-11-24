"""BFF settings: everything comes from environment variables or a default path. No secret is ever stored in the repository.

  STOCKBOT_BFF_HOST            bind address (default 127.0.0.1)
  STOCKBOT_BFF_PORT            port (default 8765)
  STOCKBOT_BFF_ALLOWED_HOSTS   comma-separated Host header values accepted (default "localhost,127.0.0.1")
  STOCKBOT_BFF_CORS            comma-separated allowed origins; unset = no CORS middleware (the app is native)
  STOCKBOT_BFF_TOKEN           the access token (else the first line of <data root>\\bff\\token.txt)
  STOCKBOT_DATA_ROOT           the data root (default F:\\Projects\\Ravi\\StockBotData): daily\\calendar.csv, logs\\bff.log, bff\\token.txt
  STOCKBOT_STATE_DB, STOCKBOT_DB, STOCKBOT_TICKETS_DIR   as in stockbot.config.paths (state\\live_state.db, finsight.db, state\\tickets)
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from stockbot.config.paths import lake_path, state_db_path, tickets_dir  # noqa: E402  (pure path helpers)

DEFAULT_ROOT = Path(r"F:\Projects\Ravi\StockBotData")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


class TokenMissing(RuntimeError):
    """Neither STOCKBOT_BFF_TOKEN nor the token file exists (or it is empty): the BFF refuses to start."""


@dataclass(frozen=True)
class Settings:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    allowed_hosts: Tuple[str, ...] = ("localhost", "127.0.0.1")
    cors_origins: Tuple[str, ...] = ()
    token: str = field(default="", repr=False)                 # never shown in a repr, a log or an error
    data_root: Path = DEFAULT_ROOT
    state_db: Path = field(default_factory=state_db_path)
    lake: Path = field(default_factory=lake_path)
    tickets_dir: Path = field(default_factory=tickets_dir)
    shared_yaml: Path = REPO / "stockbot" / "config" / "shared.yaml"
    marks_yaml: Path = REPO / "bff" / "paper_marks.yaml"
    busy_timeout_s: float = 3.0

    @property
    def calendar_csv(self) -> Path:
        return self.data_root / "daily" / "calendar.csv"

    @property
    def log_file(self) -> Path:
        return self.data_root / "logs" / "bff.log"

    @property
    def token_file(self) -> Path:
        return self.data_root / "bff" / "token.txt"


def _csv(value: Optional[str], default: Tuple[str, ...]) -> Tuple[str, ...]:
    if value is None or not value.strip():
        return default
    return tuple(x.strip() for x in value.split(",") if x.strip())


def read_token(env: Mapping[str, str], token_file: Path) -> str:
    """The token from STOCKBOT_BFF_TOKEN, else from the token file. Raises TokenMissing (without ever including the token in a message)."""
    t = (env.get("STOCKBOT_BFF_TOKEN") or "").strip()
    if t:
        return t
    try:
        lines = token_file.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        lines = []
    if lines and lines[0].strip():
        return lines[0].strip()
    raise TokenMissing(f"no access token: set STOCKBOT_BFF_TOKEN or create {token_file}")


def load_settings(env: Optional[Mapping[str, str]] = None, *, require_token: bool = True) -> Settings:
    env = os.environ if env is None else env
    root = Path(env.get("STOCKBOT_DATA_ROOT") or DEFAULT_ROOT)
    base = Settings(data_root=root)
    token = read_token(env, base.token_file) if require_token else (env.get("STOCKBOT_BFF_TOKEN") or "")
    return Settings(
        host=env.get("STOCKBOT_BFF_HOST") or DEFAULT_HOST,
        port=int(env.get("STOCKBOT_BFF_PORT") or DEFAULT_PORT),
        allowed_hosts=_csv(env.get("STOCKBOT_BFF_ALLOWED_HOSTS"), ("localhost", "127.0.0.1")),
        cors_origins=_csv(env.get("STOCKBOT_BFF_CORS"), ()),
        token=token,
        data_root=root,
        state_db=Path(env["STOCKBOT_STATE_DB"]) if env.get("STOCKBOT_STATE_DB") else state_db_path(),
        lake=Path(env["STOCKBOT_DB"]) if env.get("STOCKBOT_DB") else lake_path(),
        tickets_dir=Path(env["STOCKBOT_TICKETS_DIR"]) if env.get("STOCKBOT_TICKETS_DIR") else tickets_dir(),
    )
