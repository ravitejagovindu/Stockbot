"""stockbot.live: EOD runner, tickets, state DB, idempotency, scheduler, read-only API. Same imports as backtest plus its own state store; never backtest."""

from stockbot.data.asof import active_view_name


class MemoryViewNotValidated(RuntimeError):
    """The in-memory as-of view (STOCKBOT_VIEW=memory) has been proven for backtests only."""


def refuse_memory_view() -> None:
    """Called at every live entry point: the live path always reads through the SQL view until the memory view is tested there."""
    if active_view_name() == "memory":
        raise MemoryViewNotValidated("memory view is not validated for live; unset STOCKBOT_VIEW")
