import sqlite3
import pandas as pd

db_path = r"f:\Projects\Ravi\StockBot\finsight.db"
conn = sqlite3.connect(db_path)

print("--- Database Verification Report ---")

total_rows = pd.read_sql("SELECT COUNT(*) as c FROM market_data_lake", conn).iloc[0]['c']
print(f"Total Rows: {total_rows:,}")

unique_symbols = pd.read_sql("SELECT COUNT(DISTINCT symbol) as c FROM market_data_lake", conn).iloc[0]['c']
print(f"Unique Symbols: {unique_symbols:,}")

dates = pd.read_sql("SELECT MIN(trade_date) as s, MAX(trade_date) as e FROM market_data_lake", conn).iloc[0]
print(f"Date Range: {dates['s']} to {dates['e']}")

print("\n--- Sample Data (Recent 5 days for RELIANCE) ---")
sample = pd.read_sql("SELECT symbol, trade_date, open_raw, high_raw, low_raw, close_raw, volume_raw FROM market_data_lake WHERE symbol='RELIANCE' ORDER BY trade_date DESC LIMIT 5", conn)
print(sample.to_string(index=False))

# Check for Nulls in critical columns
print("\n--- Data Quality Checks ---")
nulls = pd.read_sql("SELECT COUNT(*) as c FROM market_data_lake WHERE close_raw IS NULL OR volume_raw IS NULL", conn).iloc[0]['c']
print(f"Rows with missing Close/Volume data: {nulls}")

conn.close()
