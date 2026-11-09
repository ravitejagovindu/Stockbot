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

## 3. Anti-Cluster & Falling-Knife Protection (The "Adani Cluster" Safeguard)
**Goal:** Prevent catastrophic cluster drawdowns caused by repeatedly catching falling knives in crashing stocks or over-concentrating in single promoter/conglomerate groups.

**Context & Empirical Finding:**
* During the Jan–Feb 2023 Hindenburg sell-off, the engine took 17 consecutive stop-outs across Adani group stocks (`ADANIGREEN`, `ADANIENSOL`, `ADANIENT`, `ADANIPOWER`).
* Because resistance targets were anchored to 52-week highs from late 2022, crashing stocks produced artificially inflated projected R:R multiples (5:1 to 20:1), tricking the sizing engine into repeatedly re-buying the same falling stocks immediately after being stopped out.
* This single cluster erased over 12% of total account equity in 5 weeks, single-handedly driving the Bull Run maximum drawdown to 20.74%.

**Required Upgrades:**
* **Trend Alignment Gate (Anti-Falling-Knife Floor):** Require price to be strictly trading above its 50-day SMA (or Donchian 20-day midpoint) at entry. Disqualify any stock trading below key moving averages regardless of how attractive the projected R:R appears.
* **Post-Stop Re-Entry Cooldown Period:** Introduce a mandatory cooldown window (e.g., 10–15 trading days) after a symbol hits its initial stop loss before the engine is permitted to generate another trade ticket for that same symbol.
* **Conglomerate / Group Exposure Limits:** Extend sector exposure checks to track corporate group / promoter parent entities (e.g., hard cap of 15% combined total risk across all subsidiaries of a single conglomerate like Adani, Tata, or Reliance).
* **Dynamic Resistance Target Ceiling:** Discard or penalize 52-week high resistance targets if the current price is down more than 25–30% from that peak, preventing distorted reward-to-risk calculations on broken chart structures.

## 4. Two-Stage Macro Regime Filter (Bull-Trend vs. Bull-Correction via 50-day SMA)
**Goal:** Prevent over-allocating capital into bear market bounces or cyclical pullbacks within broader secular bull regimes, preserving capital when the index is correcting.

**Context & Empirical Finding:**
* In late 2022 and early 2023, Nifty traded below its 50-day SMA while remaining above its 200-day SMA.
* Because the binary kill switch only checked `NIFTY > 200 SMA`, the engine treated the market as a roaring bull market and aggressively maintained 12 concurrent positions into a declining index tape.
* Clustered stop-outs across 12 positions during this cyclical pullback contributed significantly to the 20.74% maximum drawdown.

**Required Upgrades:**
* **Macro Regime Granularity:** Upgrade `RegimeFilter` to evaluate both the intermediate trend (50-day SMA) and the long-term secular trend (200-day SMA):
  * **Stage A (Confirmed Bull Trend):** `Nifty > SMA(50)` AND `Nifty > SMA(200)` $\implies$ Full Aggression mode (`max_concurrent_positions: 12`).
  * **Stage B (Bull Pullback / Consolidation):** `Nifty < SMA(50)` BUT `Nifty > SMA(200)` $\implies$ Defensive Pullback mode (`max_concurrent_positions: 8–9`).
  * **Stage C (Secular Bear Market):** `Nifty < SMA(200)` $\implies$ Macro Kill Switch active (0 new positions).
* **Dynamic Exposure Throttling:** In Stage B, the engine automatically lowers the maximum concurrent open position limit from 12 down to 8 or 9, curbing portfolio heat during choppy index corrections while preserving full compounding capacity once the 50-day SMA is reclaimed.


