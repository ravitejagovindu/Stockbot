"""A file-backed copy of the mini lake (+ one 1:5 split on FIXCO) for tests of the read-only lake and the as-of view."""
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from stockbot.data.db.connection import Base
from stockbot.data.db.models import CorporateActionsLog
from tests.fixtures import mini_lake

SPLIT_EX_IDX = 200          # a 1:5 split on FIXCO's session 200 (factor 0.2)


def _make(path: Path, with_split: bool = True):
    eng = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng)() as s:
        ds = mini_lake.build(s)
        if with_split:
            s.add(CorporateActionsLog(symbol="FIXCO", ex_date=ds[SPLIT_EX_IDX], action_type="SPLIT", ratio_numerator=1, ratio_denominator=5,
                                      source="test", evidence_tier="T1"))
        s.commit()
    eng.dispose()
    return mini_lake.sessions()


@pytest.fixture
def lake_path(tmp_path):
    p = tmp_path / "lake.db"
    _make(p)
    return p


