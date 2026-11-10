from stockbot.engine.exit_policies.registry import resolve


class AlphaExit:
    id = "alpha_exit"

    def initial_state(self, position, view):
        return {}

    def step(self, position, bar, view, ctx):
        return resolve("fixed_hold_5").step(position, bar, view, ctx)

    def on_corporate_action(self, exit_state, factor):
        return dict(exit_state)
