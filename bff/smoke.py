"""Smoke test against a RUNNING BFF: calls every endpoint, checks the status codes and the envelope, prints the key figures. Read-only. The token is read from the token file (or env) and never printed.

    py -3 bff\\smoke.py [--base-url http://127.0.0.1:8765] [--token-file F:\\Projects\\Ravi\\StockBotData\\bff\\token.txt]

Exit code 0 when every check passed, 1 otherwise."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bff.config import DEFAULT_ROOT, TokenMissing, read_token  # noqa: E402

TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+05:30$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ENVELOPE = ("apiVersion", "dataAsOf", "expectedAsOf", "generatedAt")


def call(base: str, path: str, token: str | None):
    req = urllib.request.Request(base + path)
    if token is not None:
        req.add_header("X-Paper-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "null")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="http://127.0.0.1:8765")
    ap.add_argument("--token-file", default=str(DEFAULT_ROOT / "bff" / "token.txt"))
    a = ap.parse_args(argv)
    try:
        token = read_token(os.environ, Path(a.token_file))
    except TokenMissing as exc:
        print(f"FAIL: {exc}")
        return 1
    fails: list = []

    def check(ok: bool, what: str) -> None:
        print(("ok   " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    for ep in ("health", "today", "account", "positions", "trades"):
        st, body = call(a.base_url, f"/v1/{ep}", token)
        check(st == 200, f"GET /v1/{ep} -> {st}")
        if st != 200:
            continue
        check(body.get("apiVersion") == "1", f"{ep}: apiVersion 1")
        check(all(k in body for k in ENVELOPE), f"{ep}: envelope present")
        check(bool(DATE.match(body["dataAsOf"])) and bool(DATE.match(body["expectedAsOf"])) and bool(TS.match(body["generatedAt"])), f"{ep}: dates and +05:30 timestamp")
        if ep == "account":
            s = body["summary"]
            check(s["equityPaise"] == body["curve"][-1]["accountPaise"], "account: curve ends at equity")
            check(body["curve"][0]["accountPaise"] == s["startingCapitalPaise"], "account: curve starts at the starting capital")
            print(f"     start {s['startDate']}  equity {s['equityPaise']} paise  cash {s['cashPaise']}  return {s['returnPct']}%  nifty {s['niftyReturnPct']}%  closed {s['closedTrades']}  data {body['dataAsOf']}")
        elif ep == "positions":
            check(body["cashPaise"] + sum(p["shares"] * p["lastClosePaise"] for p in body["positions"]) == call(a.base_url, "/v1/account", token)[1]["summary"]["equityPaise"],
                  "positions: cash + positions = account equity")
            print(f"     {len(body['positions'])} open, cash {body['cashPaise']} paise")
        elif ep == "today":
            print(f"     signal day {body['isSignalDay']}  tickets {len(body['tickets'])}  blocked {len(body['blocked'])}  pending {len(body['pendingFills'])}  data {body['dataAsOf']}")
        elif ep == "trades":
            print(f"     {len(body['trades'])} closed  stats {body['stats']}")
        elif ep == "health":
            print(f"     status {body['status']}  latestSealedDate {body['latestSealedDate']}  expectedAsOf {body['expectedAsOf']}")
    for label, tok in (("no token", None), ("wrong token", "x" * 8)):
        st, body = call(a.base_url, "/v1/account", tok)
        check(st == 401 and body["error"]["code"] == "UNAUTHORIZED", f"{label} -> 401 UNAUTHORIZED")
    st, body = call(a.base_url, "/v1/nothing", token)
    check(st == 404 and "error" in body, "unknown route -> 404 with the error body")
    print("SMOKE " + ("PASSED" if not fails else f"FAILED ({len(fails)})"))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
