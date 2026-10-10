# FInsight Trading Engine - Phase 4 Enhancements

## 1. Short / Hedging Engine
**Goal:** Generate positive returns (or perfectly hedge existing long exposure) during Bear Markets, replacing the 100% Cash strategy with an active defense.

**Required Upgrades:**
* **Secondary Engine Architecture:** Build a parallel version of the screening and risk sizing engine that strictly activates *only* when the Kill Switch is ON.
* **Instrument Selection:** Define the hedging instruments. Instead of risky single-stock short selling, configure the engine to scan for Inverse Nifty ETFs or safely sized Nifty Put Options.
* **Risk Parity:** Ensure the risk engine automatically calculates the exact amount of the Inverse ETF required to mathematically offset the delta of any remaining open long positions.
