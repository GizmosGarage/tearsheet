import os
import pytest
from unittest.mock import patch
from sqlalchemy import text
from tearsheet.store.models import Company
import tearsheet.store.db as db

@pytest.fixture(autouse=True)
def mock_db_url():
    with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:"}):
        # Reset the singletons in db.py for the test
        db._engine = None
        db._SessionLocal = None
        yield
        db._engine = None
        db._SessionLocal = None

from tearsheet.store.db import get_engine, get_session_factory, init_db, session_scope

def test_engine_and_factory():
    engine = get_engine()
    assert engine is not None
    
    SessionLocal = get_session_factory()
    assert SessionLocal is not None

def test_init_db():
    init_db()
    # verify tables created
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='companies';"))
        assert result.fetchone() is not None

def test_session_scope():
    init_db()
    with session_scope() as session:
        c = Company(ticker="TEST1", cik="0001")
        session.add(c)
        
    with session_scope() as session:
        c = session.query(Company).filter_by(ticker="TEST1").first()
        assert c is not None
        
    with pytest.raises(ValueError):
        with session_scope() as session:
            c = Company(ticker="TEST2", cik="0002")
            session.add(c)
            raise ValueError("Roll back!")
            
    with session_scope() as session:
        c = session.query(Company).filter_by(ticker="TEST2").first()
        assert c is None

from sqlalchemy.exc import IntegrityError
from tearsheet.store.models import Document

def test_foreign_keys_enforced():
    init_db()
    with pytest.raises(IntegrityError):
        with session_scope() as session:
            doc = Document(filing_id=99999, section="1A", text="test")
            session.add(doc)
