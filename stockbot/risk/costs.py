"""stockbot/risk/costs.py — transaction cost and tax modeling.

All rates are read from strategy_config.yaml `costs:` section.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    stt_buy_pct: float
    stt_sell_pct: float
    brokerage_per_order: float
    exch_pct: float
    sebi_pct: float
    stamp_buy_pct: float
    gst_pct: float
    dp_sell_inr: float
    stcg_pct: float

    @staticmethod
    def from_config(cfg: dict) -> "CostModel":
        c = cfg["costs"]
        return CostModel(
            float(c["stt_buy_pct"]),
            float(c["stt_sell_pct"]),
            float(c["brokerage_per_order_inr"]),
            float(c["exchange_txn_pct"]),
            float(c["sebi_fee_pct"]),
            float(c["stamp_duty_buy_pct"]),
            float(c["gst_pct"]),
            float(c["dp_charge_per_sell_inr"]),
            float(c["stcg_tax_pct"]),
        )

    @staticmethod
    def from_shared(costs) -> "CostModel":
        """Build from the typed shared config section (stockbot.config.shared.CostsConfig); same numbers as ``from_config`` on strategy_config.yaml."""
        return CostModel(costs.stt_buy_pct, costs.stt_sell_pct, costs.brokerage_per_order_inr, costs.exchange_txn_pct, costs.sebi_fee_pct,
                         costs.stamp_duty_buy_pct, costs.gst_pct, costs.dp_charge_per_sell_inr, costs.stcg_tax_pct)

    def _fees(self, value: float) -> float:
        """Exchange transaction charges + SEBI turnover fee."""
        return value * (self.exch_pct + self.sebi_pct) / 100.0

    def buy_cost(self, value: float) -> float:
        """Total buy-side transaction costs."""
        base = self.brokerage_per_order + self._fees(value)
        return (
            value * (self.stt_buy_pct + self.stamp_buy_pct) / 100.0
            + base * (1.0 + self.gst_pct / 100.0)
        )

    def sell_cost(self, value: float) -> float:
        """Total sell-side transaction costs (includes DP charge)."""
        base = self.brokerage_per_order + self._fees(value)
        return (
            value * self.stt_sell_pct / 100.0
            + self.dp_sell_inr
            + base * (1.0 + self.gst_pct / 100.0)
        )

    def tax_on_gain(self, net_gain: float) -> float:
        """Per-position STCG approximation: max(0, gain) * stcg_pct."""
        return max(0.0, net_gain) * self.stcg_pct / 100.0
