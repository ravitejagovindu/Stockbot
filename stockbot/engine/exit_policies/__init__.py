"""stockbot.engine.exit_policies: the shared library of reusable exit policies (fixed_hold_<N>, trailing_pct_<P>) and the registry that resolves their ids.

Each policy implements stockbot.engine.exit_policy.ExitPolicy and imports nothing else of the engine. A strategy names one in StrategySpec.exit_policy; a strategy that
needs something special defines its own policy inside stockbot/strategies/<name>/. See docs/exit_policies/EXIT_POLICIES.md.
"""
