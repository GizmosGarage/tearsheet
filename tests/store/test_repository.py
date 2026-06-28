import os
import pytest
from unittest.mock import patch
from datetime import date
import tearsheet.store.db as db

@pytest.fixture(autouse=True)
def mock_db_url():
    with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:"}):
        db._engine = None
        db._SessionLocal = None
        db.init_db()
        yield
        db._engine = None
        db._SessionLocal = None

from tearsheet.store.repository import Repository
from tearsheet.store.models import Company, Filing, Document, FinancialFact, QualitativeFact, Citation

def test_upsert_company():
    repo = Repository()
    c1 = repo.upsert_company(ticker="AAPL", cik="0000320193", name="Apple")
    assert c1.id is not None
    assert c1.ticker == "AAPL"
    
    # Update existing
    c2 = repo.upsert_company(ticker="AAPL", cik="0000320193", name="Apple Inc.")
    assert c2.id == c1.id
    assert c2.name == "Apple Inc."
    
    c3 = repo.get_company_by_ticker("AAPL")
    assert c3 is not None
    assert c3.name == "Apple Inc."

def test_upsert_filing():
    repo = Repository()
    c = repo.upsert_company(ticker="AAPL", cik="0000320193")
    
    f1 = Filing(company_id=c.id, form_type="10-K", accession_number="001", filed_date=date(2023, 1, 1))
    saved_f1 = repo.upsert_filing(f1)
    assert saved_f1.id is not None
    
    # Update existing
    f2 = Filing(company_id=c.id, form_type="10-K", accession_number="001", filed_date=date(2023, 1, 2))
    saved_f2 = repo.upsert_filing(f2)
    assert saved_f2.id == saved_f1.id
    assert saved_f2.filed_date == date(2023, 1, 2)

def test_save_documents():
    repo = Repository()
    c = repo.upsert_company(ticker="AAPL", cik="0000320193")
    f = repo.upsert_filing(Filing(company_id=c.id, form_type="10-K", accession_number="001"))
    
    docs = [
        Document(filing_id=f.id, section="1A", text="text1"),
        Document(filing_id=f.id, section="1B", text="text2")
    ]
    saved_docs = repo.save_documents(docs)
    assert len(saved_docs) == 2
    assert saved_docs[0].id is not None
    
def test_save_documents_eager_loads_filing():
    repo = Repository()
    c = repo.upsert_company(ticker="MSFTX", cik="0003")
    f = repo.upsert_filing(Filing(company_id=c.id, form_type="10-K", accession_number="0003"))
    
    docs = [Document(filing_id=f.id, section="1A", text="text")]
    saved_docs = repo.save_documents(docs)
    
    # outside session context
    assert saved_docs[0].filing is not None
    assert saved_docs[0].filing.accession_number == "0003"

def test_save_financial_facts():
    repo = Repository()
    c = repo.upsert_company(ticker="AAPL", cik="0000320193")
    
    facts = [
        FinancialFact(company_id=c.id, concept="Rev", value=100.0),
        FinancialFact(company_id=c.id, concept="Cost", value=50.0)
    ]
    saved = repo.save_financial_facts(facts)
    assert len(saved) == 2
    assert saved[0].id is not None
    assert saved[0].period_end == date(1970, 1, 1)

def test_save_financial_facts_null_dedupe():
    repo = Repository()
    c = repo.upsert_company(ticker="NULLCO", cik="0005")
    
    # Save a fact with no period_end
    fact1 = FinancialFact(company_id=c.id, concept="Revenues", value=100.0)
    saved1 = repo.save_financial_facts([fact1])
    assert len(saved1) == 1
    assert saved1[0].period_end == date(1970, 1, 1)
    
    # Save again, should deduplicate
    fact2 = FinancialFact(company_id=c.id, concept="Revenues", value=200.0)
    saved2 = repo.save_financial_facts([fact2])
    assert len(saved2) == 1
    assert saved2[0].id == saved1[0].id
    assert saved2[0].value == 200.0
    
def test_save_qualitative_facts():
    repo = Repository()
    c = repo.upsert_company(ticker="AAPL", cik="0000320193")
    f = repo.upsert_filing(Filing(company_id=c.id, form_type="10-K", accession_number="001"))
    doc = repo.save_documents([Document(filing_id=f.id, section="1A", text="text1")])[0]
    
    fact = QualitativeFact(company_id=c.id, category="risk", summary="Risk 1")
    citation = Citation(document_id=doc.id, quote="quote", start_offset=0, end_offset=5)
    fact.citations = [citation]
    
    # Assuming the signature was changed to take only facts
    saved = repo.save_qualitative_facts([fact])
    assert len(saved) == 1
    assert saved[0].id is not None
    assert saved[0].citations[0].id is not None
