"""The StockBot paper BFF: a read-only FastAPI app for the Android app. Endpoints exactly as in docs/android/contract/openapi.yaml (apiVersion 1).

Read-only by construction: every database connection is opened ``mode=ro`` with ``PRAGMA query_only=ON`` (bff.sources); no endpoint writes, no order or broker code exists, the lock files are never
touched, and nothing runs in the background. Safe to kill at any time.
"""
from __future__ import annotations

import hmac
import logging
import logging.handlers
import threading
import time
from datetime import date, datetime, timezone
from typing import Callable, Dict, Optional, Sequence, Tuple

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from bff import builders as B
from bff import models as M
from bff import sources as S
from bff.config import Settings, load_settings

log = logging.getLogger("bff.access")

MSG_UNAUTHORIZED = "The access token is missing or not valid."
MSG_NOT_READY = "Today's data is not ready yet."
MSG_SERVER = "Something went wrong on the server."
MSG_NOT_FOUND = "There is no such endpoint."


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def setup_access_log(path) -> None:
    """A rotating access log (1 MB x 5): one line per request with the method, the path (no query string), the status and the time taken. Headers are never logged, so the token cannot appear."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for h in list(log.handlers):
        log.removeHandler(h)
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


class Service:
    """Builds the responses. Responses are cached on (mtime and size of live_state.db, the lake's sealed-through date); a changed key rebuilds. The envelope's expectedAsOf and generatedAt are
    refreshed on every request (they depend on the clock, not on the data)."""

    def __init__(self, settings: Settings, now_fn: Callable[[], datetime], signal_fn: Callable[[Sequence[date]], bool], sector_for: Callable[[str], str]):
        self.s = settings
        self.now_fn = now_fn
        self.signal_fn = signal_fn
        self.sector_for = sector_for
        self._lock = threading.Lock()
        self._cache: Dict[str, Tuple[Tuple, object]] = {}

    # -------------------------------------------------------------------------------------------------------------- helpers
    def _key(self) -> Tuple:
        sealed = S.read_sealed(self.s.lake, self.s.busy_timeout_s)
        return (S.read_journal_version(self.s.state_db), sealed)

    def _fresh(self, model):
        """The cached model with this request's expectedAsOf and generatedAt."""
        now = self.now_fn()
        return model.model_copy(update={"expectedAsOf": B.expected_as_of(now, S.read_no_file_days(self.s.calendar_csv)), "generatedAt": B.iso_ist(now)})

    def _load(self):
        state = S.read_state(self.s.state_db, self.s.busy_timeout_s)
        f = B.fold(state.decisions, state.initial_cash)
        lake = S.read_lake(self.s.lake, f.start_date, f.data_as_of, B.symbols_held(f), self.s.busy_timeout_s)
        env = B.make_env(f.data_as_of, self.now_fn(), S.read_no_file_days(self.s.calendar_csv))
        return state, f, lake, env

    def get(self, endpoint: str):
        with self._lock:
            key = self._key()
            hit = self._cache.get(endpoint)
            if hit is not None and hit[0] == key:
                return self._fresh(hit[1])
            state, f, lake, env = self._load()
            if endpoint == "today":
                model = B.build_today(f, S.read_tickets(self.s.tickets_dir, f.data_as_of), lake.calendar_tail, env, B.load_risk_pct(self.s.shared_yaml), self.sector_for, self.signal_fn)
            elif endpoint == "account":
                closed = sum(len(d.closed) for d in f.decisions)
                model = B.build_account(f, state.initial_cash, lake.closes, lake.nifty, closed, B.load_marks(self.s.marks_yaml), env)
            elif endpoint == "positions":
                model = B.build_positions(f, lake.closes, env)
            elif endpoint == "trades":
                model = B.build_trades(f, env)
            else:                                                                  # pragma: no cover
                raise KeyError(endpoint)
            self._cache[endpoint] = (key, model)
            return model

    def health(self) -> M.Health:
        now = self.now_fn()
        expected = B.expected_as_of(now, S.read_no_file_days(self.s.calendar_csv))
        sealed: Optional[date] = None
        last: Optional[date] = None
        try:
            sealed = S.read_sealed(self.s.lake, self.s.busy_timeout_s)
        except S.SourceError:
            pass
        try:
            last = S.read_last_session(self.s.state_db, self.s.busy_timeout_s)
        except S.SourceError:
            pass
        ok = sealed is not None and last is not None
        return M.Health(apiVersion="1", status="ok" if ok else "not_ready", serverTime=B.iso_ist(now), latestSealedDate=sealed, dataAsOf=sealed or last or expected,
                        expectedAsOf=expected, generatedAt=B.iso_ist(now))


def create_app(settings: Optional[Settings] = None, now_fn: Optional[Callable[[], datetime]] = None, signal_fn: Optional[Callable] = None,
               sector_for: Optional[Callable[[str], str]] = None) -> FastAPI:
    """Build the app. With no ``settings`` they are read from the environment, and a missing token raises ``TokenMissing`` (the BFF refuses to start)."""
    settings = settings or load_settings()
    if not settings.token:
        from bff.config import TokenMissing
        raise TokenMissing("no access token configured")
    if sector_for is None:
        from stockbot.data.sector_map import sector_for as _sf
        sector_for = _sf
    svc = Service(settings, now_fn or (lambda: datetime.now(timezone.utc)), signal_fn or B.default_signal_fn, sector_for)
    token_bytes = settings.token.encode("utf-8")

    app = FastAPI(title="StockBot Paper API", version="1", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = svc

    def err(status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(B.error_body(code, message), status_code=status)

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return err(exc.status, exc.code, exc.message)

    @app.exception_handler(S.SourceError)
    async def _source_error(_: Request, exc: S.SourceError):
        return err(503, "NOT_READY", MSG_NOT_READY)

    @app.exception_handler(B.BuildError)
    async def _build_error(_: Request, exc: B.BuildError):
        return err(503, "NOT_READY", MSG_NOT_READY)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        return err(exc.status_code, "SERVER_ERROR", MSG_NOT_FOUND if exc.status_code in (404, 405) else MSG_SERVER)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception):
        log.error("unexpected %s", type(exc).__name__)                              # the type only: a message could hold anything
        return err(500, "SERVER_ERROR", MSG_SERVER)

    def require_token(request: Request) -> None:
        given = request.headers.get("x-paper-token", "").encode("utf-8")
        if not hmac.compare_digest(given, token_bytes):                              # constant time
            raise ApiError(401, "UNAUTHORIZED", MSG_UNAUTHORIZED)

    router = APIRouter(prefix="/v1", dependencies=[Depends(require_token)])

    def respond(model) -> JSONResponse:
        return JSONResponse(model.model_dump(mode="json"))

    @router.get("/health")
    def health():
        return respond(svc.health())

    @router.get("/today")
    def today():
        return respond(svc.get("today"))

    @router.get("/account")
    def account():
        return respond(svc.get("account"))

    @router.get("/positions")
    def positions():
        return respond(svc.get("positions"))

    @router.get("/trades")
    def trades():
        return respond(svc.get("trades"))

    app.include_router(router)

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        t0 = time.monotonic()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            client = request.client.host if request.client else "-"
            log.info("%s %s %s %s %dms", client, request.method, request.url.path, status, int((time.monotonic() - t0) * 1000))

    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET"], allow_headers=["X-Paper-Token"])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))     # added last = outermost: a wrong Host header is refused first
    return app
