# FInsight Trading Engine - Phase 3 Enhancements

## 1. Pyramiding (Adding to Winners)
**Goal:** Maximize returns on massive, multi-month trends by systematically adding new capital to stocks that are already winning.

**Required Upgrades:**
* **Screening Logic:** Remove the rule that blocks a stock if it is already in the `active_positions` table. Instead, evaluate if the stock has formed a mathematically valid *new* consolidation base.
* **Risk & Sizing Math:** Create a new "Top-Up" trade ticket. The engine must ensure that adding new shares (with a new stop-loss) does not breach the 15% maximum portfolio heat cap, and must calculate a blended average cost for the UI.
* **UI Updates:** Trade tickets should clearly distinguish between "New Initial Setup" and "Pyramid Add", so the user knows they are adding to an existing winner rather than opening a new position.

## 2. Multi-Timeframe Alignment (Tide & Wave Filter)
**Goal:** Drastically increase the win rate of daily breakouts by ensuring they only occur in the direction of the weekly macro-trend.

**Required Upgrades:**
* **Data Ingestion:** Upgrade the `market_data_lake` to dynamically resample daily data into weekly OHLCV bars.
* **Universe Screener:** Add a new gate that calculates moving averages on the weekly timeframe. Reject any stock whose weekly trend is pointing downward, regardless of how good the daily breakout looks.
