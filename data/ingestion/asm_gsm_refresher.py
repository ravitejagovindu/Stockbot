"""
FInsight Trading Engine — ASM/GSM Surveillance List Refresher
=============================================================
Downloads the current ASM (Additional Surveillance Measure) and GSM (Graded
Surveillance Measure) lists from NSE India and refreshes the ``asm_gsm_list``
table.

Design notes:
    - This is a SNAPSHOT, not a log.  The table is completely replaced on each
      ``refresh()`` call.  Stocks no longer on the list are deleted.
    - ``is_under_surveillance()`` is a fast DB lookup (indexed on ``symbol``).
    - NSE endpoints return 403 without proper browser headers + session cookies.
      ``BaseIngestor._get_nse_session()`` handles the warm-up automatically.

NSE Source URLs (as of 2024 — check NSE periodically for endpoint changes):
    ASM: https://archives.nseindia.com/content/equities/asm_securities.csv
    GSM: https://www.nseindia.com/api/corporate-announcements?index=SECURITIES_UNDER_GSM
         or https://nsearchives.nseindia.com/content/equities/gsm_securities.csv

Usage:
    refresher = ASMGSMRefresher()
    result = refresher.refresh()
    # → {'added': 3, 'removed': 1, 'updated': 0, 'total': 52}

    is_risky = refresher.is_under_surveillance("YESBANK")
    # → True / False
"""
from __future__ import annotations

import io
import logging
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import text

from data.db.connection import get_session
from data.ingestion.base_ingestor import BaseIngestor

logger = logging.getLogger(__name__)

# ── NSE data endpoints ───────────────────────────────────────────────────────
# Primary CSV endpoints (publicly accessible archives)
_ASM_CSV_URL = (
    "https://archives.nseindia.com/content/equities/asm_securities.csv"
)
_GSM_CSV_URL = (
    "https://nsearchives.nseindia.com/content/equities/gsm_securities.csv"
)

# Fallback: NSE API-style endpoint (may require stricter headers)
_ASM_API_URL = (
    "https://www.nseindia.com/api/reportsmf?index=ASM"
)
_GSM_API_URL = (
    "https://www.nseindia.com/api/corporate-announcements?index=SECURITIES_UNDER_GSM"
)

# Canonical framework labels
_FRAMEWORK_ASM = "ASM"
_FRAMEWORK_GSM = "GSM"


class ASMGSMRefresher(BaseIngestor):
    """
    Refreshes the ASM/GSM surveillance lists from NSE.

    Each call to ``refresh()`` fully replaces the ``asm_gsm_list`` table
    content.  This is appropriate because the list represents a current
    snapshot, not a historical log.

    Args:
        None — all configuration loaded from ``strategy_config.yaml`` via
        ``BaseIngestor.__init__()``.
    """

    def __init__(self) -> None:
        super().__init__(
            kite_rate_per_sec=1.0,  # NSE scraping — be conservative
            max_retries=3,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(self, *args: Any, **kwargs: Any) -> dict:
        """
        Convenience alias satisfying ``BaseIngestor.ingest()`` contract.

        Delegates to ``refresh()``.
        """
        return self.refresh()

    def refresh(self) -> dict:
        """
        Download current ASM and GSM lists from NSE and replace the DB table.

        Strategy:
            1. Fetch ASM list (CSV → DataFrame).
            2. Fetch GSM list (CSV → DataFrame).
            3. Compare new lists with existing DB rows to compute diff stats.
            4. DELETE all existing rows.
            5. INSERT all new rows.

        Returns:
            Dict with keys:
                ``added`` (int): Symbols newly appearing on any list.
                ``removed`` (int): Symbols no longer on any list.
                ``updated`` (int): Symbols still present but with changed stage.
                ``total`` (int): Total rows now in the table.

        Note:
            On a first run the DB table is empty, so ``added`` equals the
            total count and ``removed`` is 0.
        """
        self.logger.info("Refreshing ASM/GSM surveillance lists from NSE.")

        asm_df = self._fetch_framework(_FRAMEWORK_ASM)
        gsm_df = self._fetch_framework(_FRAMEWORK_GSM)

        new_df = pd.concat([asm_df, gsm_df], ignore_index=True)
        self.logger.info(
            "Fetched %d ASM + %d GSM = %d total surveillance entries.",
            len(asm_df),
            len(gsm_df),
            len(new_df),
        )

        # Load current DB state for diff computation
        old_records = self._load_existing()

        # Compute diff
        old_keys = {(r["symbol"], r["framework"]) for r in old_records}
        new_keys = {
            (row["symbol"], row["framework"])
            for _, row in new_df.iterrows()
        }

        added = len(new_keys - old_keys)
        removed = len(old_keys - new_keys)

        # Count updated: same key but different stage
        old_stage_map = {
            (r["symbol"], r["framework"]): r.get("stage")
            for r in old_records
        }
        updated = sum(
            1
            for _, row in new_df.iterrows()
            if (row["symbol"], row["framework"]) in old_stage_map
            and old_stage_map[(row["symbol"], row["framework"])] != row.get("stage")
        )

        # Replace table contents atomically
        self._replace_table(new_df)

        result = {
            "added": added,
            "removed": removed,
            "updated": updated,
            "total": len(new_df),
        }
        self.logger.info("ASM/GSM refresh complete: %s", result)
        return result

    def is_under_surveillance(self, symbol: str) -> bool:
        """
        Check whether *symbol* is currently under ASM or GSM surveillance.

        This is a fast, indexed DB lookup.  Call after ``refresh()`` to
        ensure data is current.

        Args:
            symbol: NSE ticker (case-sensitive, must match stored value).

        Returns:
            True if the symbol appears in ``asm_gsm_list``, False otherwise.
        """
        with get_session() as session:
            row = session.execute(
                text(
                    "SELECT 1 FROM asm_gsm_list WHERE symbol = :sym LIMIT 1"
                ),
                {"sym": symbol},
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_framework(self, framework: str) -> pd.DataFrame:
        """
        Download and parse the surveillance list for *framework* (ASM or GSM).

        Tries CSV endpoint first, then API endpoint as fallback.

        Args:
            framework: ``"ASM"`` or ``"GSM"``.

        Returns:
            DataFrame with columns: ``symbol``, ``framework``, ``stage``,
            ``effective_date``.
        """
        csv_url = _ASM_CSV_URL if framework == _FRAMEWORK_ASM else _GSM_CSV_URL
        api_url = _ASM_API_URL if framework == _FRAMEWORK_ASM else _GSM_API_URL

        df: pd.DataFrame | None = None

        # ── Attempt 1: CSV download ────────────────────────────────────
        try:
            df = self._fetch_csv(csv_url, framework)
            if df is not None and not df.empty:
                self.logger.debug(
                    "%s CSV fetch succeeded (%d rows).", framework, len(df)
                )
                return df
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("%s CSV fetch failed: %s", framework, exc)

        # ── Attempt 2: API/HTML fallback ──────────────────────────────
        try:
            df = self._fetch_api(api_url, framework)
            if df is not None and not df.empty:
                self.logger.debug(
                    "%s API fetch succeeded (%d rows).", framework, len(df)
                )
                return df
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("%s API fetch also failed: %s", framework, exc)

        self.logger.warning(
            "Could not fetch %s list from any source. Returning empty DataFrame.",
            framework,
        )
        return pd.DataFrame(
            columns=["symbol", "framework", "stage", "effective_date"]
        )

    def _fetch_csv(self, url: str, framework: str) -> pd.DataFrame:
        """
        Download a CSV from NSE archives and convert to the canonical schema.

        NSE ASM CSV columns (may vary — we handle common variants):
            ``Symbol``, ``Series``, ``Date of Inclusion``, ``Stage``

        Args:
            url: CSV download URL.
            framework: ``"ASM"`` or ``"GSM"`` label for the ``framework`` column.

        Returns:
            Normalised DataFrame.
        """
        session = self._get_nse_session()
        resp = self._with_retry(session.get, url, timeout=30)
        resp.raise_for_status()

        # Parse CSV from response content
        csv_text = resp.content.decode("utf-8", errors="replace")
        raw_df = pd.read_csv(io.StringIO(csv_text))

        return self._normalise_dataframe(raw_df, framework)

    def _fetch_api(self, url: str, framework: str) -> pd.DataFrame:
        """
        Fetch surveillance list from the NSE JSON API endpoint.

        Args:
            url: NSE API URL.
            framework: ``"ASM"`` or ``"GSM"``.

        Returns:
            Normalised DataFrame.
        """
        session = self._get_nse_session()
        resp = self._with_retry(session.get, url, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # Handle list or dict-with-data-key responses
        if isinstance(data, list):
            raw_df = pd.DataFrame(data)
        elif isinstance(data, dict):
            # NSE often wraps data in a key like "data" or "resultList"
            for key in ("data", "resultList", "results", "securities"):
                if key in data and isinstance(data[key], list):
                    raw_df = pd.DataFrame(data[key])
                    break
            else:
                raw_df = pd.DataFrame([data])
        else:
            return pd.DataFrame(
                columns=["symbol", "framework", "stage", "effective_date"]
            )

        return self._normalise_dataframe(raw_df, framework)

    def _normalise_dataframe(self, raw_df: pd.DataFrame, framework: str) -> pd.DataFrame:
        """
        Normalise a raw NSE DataFrame into the canonical schema.

        Handles column name variations across NSE CSV and API responses.

        Args:
            raw_df: Raw DataFrame from NSE source.
            framework: ``"ASM"`` or ``"GSM"``.

        Returns:
            DataFrame with columns: symbol, framework, stage, effective_date.
        """
        if raw_df.empty:
            return pd.DataFrame(
                columns=["symbol", "framework", "stage", "effective_date"]
            )

        # Normalise column names to lowercase for consistent lookup
        raw_df.columns = [str(c).strip().lower() for c in raw_df.columns]

        # Symbol column aliases used by NSE
        symbol_col = next(
            (c for c in raw_df.columns if c in ("symbol", "security", "tradingsymbol", "scrip")),
            None,
        )
        # Stage/classification column aliases
        stage_col = next(
            (c for c in raw_df.columns if "stage" in c or "classification" in c or "grade" in c),
            None,
        )
        # Date column aliases
        date_col = next(
            (
                c for c in raw_df.columns
                if "date" in c or "inclusion" in c or "effective" in c
            ),
            None,
        )

        if symbol_col is None:
            self.logger.warning(
                "No symbol column found in %s DataFrame. Columns: %s",
                framework,
                list(raw_df.columns),
            )
            return pd.DataFrame(
                columns=["symbol", "framework", "stage", "effective_date"]
            )

        out = pd.DataFrame()
        out["symbol"] = raw_df[symbol_col].astype(str).str.strip().str.upper()
        out["framework"] = framework
        out["stage"] = raw_df[stage_col].astype(str).str.strip() if stage_col else None
        out["effective_date"] = date.today()

        if date_col:
            try:
                out["effective_date"] = pd.to_datetime(
                    raw_df[date_col], errors="coerce", dayfirst=True
                ).dt.date.fillna(date.today())
            except Exception:  # noqa: BLE001
                pass  # Keep today's date as fallback

        # Drop rows with empty or invalid symbols
        out = out[out["symbol"].str.len() > 0].drop_duplicates(
            subset=["symbol", "framework"]
        )
        return out.reset_index(drop=True)

    def _load_existing(self) -> list[dict]:
        """
        Load all current rows from ``asm_gsm_list``.

        Returns:
            List of dicts with keys: symbol, framework, stage.
        """
        with get_session() as session:
            rows = session.execute(
                text("SELECT symbol, framework, stage FROM asm_gsm_list")
            ).fetchall()
        return [{"symbol": r[0], "framework": r[1], "stage": r[2]} for r in rows]

    def _replace_table(self, new_df: pd.DataFrame) -> None:
        """
        Atomically replace all rows in ``asm_gsm_list`` with *new_df*.

        Uses a DELETE-all + INSERT-new pattern within a single transaction.
        This is intentional: ASM/GSM is a snapshot list, not a cumulative log.

        Args:
            new_df: DataFrame with columns: symbol, framework, stage, effective_date.
        """
        with get_session() as session:
            # 1. Delete all existing rows
            session.execute(text("DELETE FROM asm_gsm_list"))

            # 2. Insert all new rows
            if not new_df.empty:
                rows_to_insert = [
                    {
                        "symbol": row["symbol"],
                        "framework": row["framework"],
                        "stage": row.get("stage"),
                        "effective_date": row["effective_date"],
                    }
                    for _, row in new_df.iterrows()
                ]
                session.execute(
                    text(
                        """
                        INSERT INTO asm_gsm_list (symbol, framework, stage, effective_date)
                        VALUES (:symbol, :framework, :stage, :effective_date)
                        """
                    ),
                    rows_to_insert,
                )

        self.logger.debug(
            "Replaced asm_gsm_list with %d rows.", len(new_df)
        )
