from sqlalchemy.orm import Session


def decide(session: Session):
    from data.db.connection import get_session
    return get_session
