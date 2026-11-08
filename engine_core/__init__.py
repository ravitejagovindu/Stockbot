"""Legacy package (restructure in progress). Intentionally has NO re-exports: nothing imports names from the package root, and re-exporting
position_lifecycle etc. here made `import stockbot.engine.corporate_action_events` fail with a circular import when imported first.
This package is removed in Phase 10; see docs/restructure/INVENTORY.csv."""
