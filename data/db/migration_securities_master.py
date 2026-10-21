"""data/db/migration_securities_master.py — Create securities_master table.

Run once: py -3 -m data.db.migration_securities_master
"""
from sqlalchemy import text
from data.db.connection import get_session


def main() -> None:
    with get_session() as s:
        s.execute(text("""
            CREATE TABLE IF NOT EXISTS securities_master (
                symbol          VARCHAR(20) PRIMARY KEY,
                company_name    VARCHAR(200),
                series          VARCHAR(10) NOT NULL DEFAULT 'EQ',
                listing_date    DATE NOT NULL,
                isin            VARCHAR(30),
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        s.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_securities_listing_date ON securities_master(listing_date);
        """))
        s.commit()
        print("securities_master table migration complete.")


if __name__ == "__main__":
    main()
