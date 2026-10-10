# FInsight Trading Engine - Phase 2 Enhancements

## 1. Dynamic Account Ledger (Monthly SIPs & Compounding)
**Goal:** Shift from a static `.env` configuration to a dynamic database ledger to seamlessly handle monthly top-ups (SIPs) and automatic profit compounding.

**Required Upgrades:**
* **Database Ledger:** Create a new `account_ledger` table in the SQLite database to act as a historical log for all cash flows (Deposits, Withdrawals, Realized Profits, and Realized Losses).
* **UI Controls:** Add a "Deposit / Withdraw Funds" interface on the React Dashboard (Analytics/Portfolio page) so the user can easily log their monthly capital injections (e.g., adding ₹25,000).
* **Dynamic Risk Sizing:** Update the `RiskAndSizingEngine` in `pipeline.py`. Instead of reading `ACCOUNT_EQUITY` from the `.env` file, the engine will query the ledger to calculate the true live equity `(Total Deposits - Withdrawals + Realized P&L)`. This ensures the 1.2% risk math scales perfectly as the account grows.

## 2. Kill Switch Proximity Dashboard
**Goal:** Add a visual graph/gauge to the UI to show the user exactly how close the market is to flipping the Kill Switch ON or OFF.

**Required Upgrades:**
* **Distance Metrics:** The backend API needs to return the exact distance (%) between the current Nifty price and its moving averages (20-day and 200-day), as well as the VIX thresholds.
* **UI Visuals:** Add a visual Thermometer or Radar gauge to the Dashboard banner showing how close the market is to the danger zone, removing the need for the user to guess based on raw numbers.

## 3. Sector-Level Performance Aggregation
**Goal:** Expand the Sector Exposure visual to not just show capital allocation, but also aggregate Profit/Loss by sector.

**Required Upgrades:**
* **UI Visuals:** Upgrade the Portfolio tab so the user can see exactly which sectors are driving their portfolio's profits and which are dragging it down (e.g., 'IT: +5.2%', 'Banking: -1.1%').

## 4. Partial Profit Booking (Scaling Out)
**Goal:** Upgrade the exit logic to allow scaling out of positions to lock in guaranteed profits early.

**Required Upgrades:**
* **Engine Math:** Update the PositionLifecycleManager to trigger a 50% sell alert when a stock reaches a predefined multiple of risk (e.g., 1:2 R:R).
* **Position Tracking:** The database and UI must handle 'split' positions, tracking the locked-in cash while continuing to manage the trailing stop for the remaining 50% of the shares.

## 5. Adaptive "Parabolic" Stop-Losses
**Goal:** Protect profits on stocks that go vertical by dynamically tightening the trailing stop as momentum accelerates.

**Required Upgrades:**
* **Engine Math:** Update the PositionLifecycleManager to monitor price acceleration. If a stock moves up significantly in a short time, shift the stop-loss logic from a standard 2x ATR to a tighter, parabolic metric (like 1x ATR or previous day's low).
* **UI Badges:** Add a new state badge in the Portfolio table (e.g., PARABOLIC_TRAILING) so the user knows the engine has tightened the safety net.
