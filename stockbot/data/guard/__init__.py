"""Database guard (design in docs/shared/db-guard/GUARD.md): sealed history, logged corrections, run-time database checks."""
from stockbot.data.guard.core import (GuardError, UnregisteredTables, audit, close_window, connect_writer, correct, current_seal, ensure, install, installed, open_window, seal_table, status,  # noqa: F401
                                      uninstall, window_state)
from stockbot.data.guard.registry import BACKTEST_READS, DATED, EXEMPT, INSERT_ONLY, RULES  # noqa: F401
