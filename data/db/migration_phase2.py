import sys
from pathlib import Path

# Add project root to path so imports work
sys.path.append(str(Path(__file__).resolve().parents[2]))

from data.db.connection import engine, Base
import data.db.models  # Ensures models are loaded

def run_migration():
    print("Running Phase 2 Migrations...")
    Base.metadata.create_all(engine)
    print("Migrations complete.")

if __name__ == "__main__":
    run_migration()
