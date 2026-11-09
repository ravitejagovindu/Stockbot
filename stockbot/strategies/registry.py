"""Strategy registry (restructure Phase 4): a validated, id-unique list of strategy specs. ``default_registry`` is EMPTY: no strategy exists in the tree."""
from __future__ import annotations

from typing import Iterator

from stockbot.strategies.spec import SpecError, StrategySpec


class StrategyRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, StrategySpec] = {}

    def register(self, spec: StrategySpec) -> StrategySpec:
        if not isinstance(spec, StrategySpec):
            raise SpecError("only StrategySpec objects can be registered")
        if spec.id in self._specs:
            raise SpecError(f"strategy id already registered: {spec.id}")
        self._specs[spec.id] = spec
        return spec

    def get(self, strategy_id: str) -> StrategySpec:
        try:
            return self._specs[strategy_id]
        except KeyError:
            raise SpecError(f"unknown strategy id: {strategy_id}") from None

    def ids(self) -> list[str]:
        return sorted(self._specs)

    def all(self) -> list[StrategySpec]:
        return [self._specs[i] for i in self.ids()]

    def __len__(self) -> int:
        return len(self._specs)

    def __iter__(self) -> Iterator[StrategySpec]:
        return iter(self.all())


default_registry = StrategyRegistry()
