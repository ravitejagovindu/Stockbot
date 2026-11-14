"""Live adapter (restructure Phase 6 Part B). It holds NO decision logic: it loads State from the live state store, applies the operator's reports (D4), calls
``engine.decide`` once per session (C2) in non-strict mode (C4), and journals the result.

No order is ever sent anywhere: the adapter produces tickets (Decisions.new_tickets) for the operator to act on; the operator reports what really happened
(``FillReport`` / ``ExitReport`` / ``NotTakenReport``) before the next session is processed. Reports are applied to State first, so reality overrides the engine's
inference; tickets nobody reported are simulated by ``decide`` and flagged UNRECONCILED_FILL.
Idempotent per trading date: processing a date that is already in the journal changes nothing (reports already journaled are skipped by their id).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Optional, Sequence

from stockbot.data.asof import AsOfView
from stockbot.data.lake import open_lake
from stockbot.engine.decide import EventData, decide
from stockbot.engine.reports import ExitReport, FillReport, NotTakenReport, ReportError, apply_effect, exit_effect, fill_effect, not_taken_effect
from stockbot.engine.types import Decisions, State
from stockbot.live import refuse_memory_view
from stockbot.live.state_store import StateStore
from stockbot.risk.costs import CostModel


class LiveAdapter:
    def __init__(self, store: StateStore, lake, strategies: Sequence, policies: Mapping[str, Any], shared_config, event_data: EventData, *,
                 overlays: Optional[Mapping[str, Any]] = None):
        refuse_memory_view()
        self.store, self.strategies, self.policies, self.cfg, self.events, self.overlays = store, strategies, policies, shared_config, event_data, overlays
        self.conn = open_lake(lake) if not hasattr(lake, "execute") else lake
        self.costs = CostModel.from_shared(shared_config.costs)

    def state(self) -> State:
        return self.store.load()

    def _apply_reports(self, st: State, reports: Sequence) -> State:
        for r in reports:
            rid = r.report_id()
            if self.store.has_effect(rid):
                continue                                            # already journaled: idempotent
            if isinstance(r, FillReport):
                t = next((t for t in st.pending if t.ticket_id == r.ticket_id), None)
                if t is None:
                    raise ReportError(f"no pending ticket {r.ticket_id}")
                strat = next((s for s in self.strategies if s.spec.id == t.strategy_id), None)
                if strat is None:
                    raise ReportError(f"strategy {t.strategy_id} is not registered")
                eff = fill_effect(st, r, self.policies[strat.spec.exit_policy], AsOfView(self.conn, r.date), self.costs)
            elif isinstance(r, ExitReport):
                eff = exit_effect(st, r, self.costs)
            elif isinstance(r, NotTakenReport):
                eff = not_taken_effect(st, r)
            else:
                raise ReportError(f"unknown report type {type(r).__name__}")
            st = apply_effect(st, eff)
            self.store.append_effect(eff, st)
        return st

    def process(self, as_of: date, reports: Sequence = ()) -> list:
        """Process every session up to ``as_of`` that the state has not seen (one ``decide`` per session). Returns the new Decisions (empty if already done)."""
        st = self.store.load()
        if st.as_of is not None and st.as_of >= as_of:
            if any(not self.store.has_effect(r.report_id()) for r in reports):
                raise ReportError(f"late report: {as_of} is already processed; corrections of simulated events are not supported")
            return []
        st = self._apply_reports(st, reports)
        sessions = [d for d in AsOfView(self.conn, as_of).sessions() if st.as_of is None or d > st.as_of]
        if st.as_of is None:
            sessions = sessions[-1:]                                # first run: no history to replay
        out = []
        for d in sessions:
            dec, st = decide(d, st, AsOfView(self.conn, d), self.strategies, self.cfg, self.events, policies=self.policies, overlays=self.overlays, strict=False, mode="live")
            self.store.append_decisions(dec, st)
            out.append(dec)
        return out
