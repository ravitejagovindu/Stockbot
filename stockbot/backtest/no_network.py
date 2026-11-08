"""stockbot/backtest/no_network.py — a backtest must be reproducible from the database alone: any attempt to reach the network raises.

Patches the socket layer (``connect``, ``connect_ex``, ``create_connection``, ``getaddrinfo``) for the duration of the context, so requests, urllib,
yfinance and friends all fail with ``NetworkAccessError``.  SQLite and local files are unaffected.
"""
from __future__ import annotations

import socket
from contextlib import contextmanager


class NetworkAccessError(RuntimeError):
    """Raised when code running inside a backtest tries to use the network."""


def _refuse(*args, **kwargs):
    raise NetworkAccessError("network access attempted inside a backtest (backtests must run from the database only; "
                             "fetch data beforehand with the ingestion/scraper scripts)")


@contextmanager
def network_forbidden():
    saved = (socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo)
    socket.socket.connect = _refuse
    socket.socket.connect_ex = _refuse
    socket.create_connection = _refuse
    socket.getaddrinfo = _refuse
    try:
        yield
    finally:
        socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo = saved
