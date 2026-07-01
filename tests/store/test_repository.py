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
from tearsheet.store.models import Company, Filing, Document, FinancialFact, QualitativeFact, Citation, SourceDocument

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

def test_upsert_source_documents():
    repo = Repository()
    c = repo.upsert_company(ticker="AAPL", cik="0000320193")
    f = repo.upsert_filing(Filing(company_id=c.id, form_type="10-K", accession_number="001"))

    docs = [
        SourceDocument(
            filing_id=f.id, filename="a.htm", doc_type="text.htm",
            sha256="ab" * 32, byte_size=10, edgar_url="http://sec/a.htm"
        ),
        SourceDocument(
            filing_id=f.id, filename="ex21.htm", doc_type="EX-21",
            sha256="cd" * 32, byte_size=20, edgar_url="http://sec/ex21.htm"
        ),
    ]
    saved = repo.upsert_source_documents(docs)
    assert len(saved) == 2
    assert all(sd.id is not None for sd in saved)

    # Re-acquisition with a changed hash updates in place, keyed by (filing_id, filename)
    updated = repo.upsert_source_documents([
        SourceDocument(
            filing_id=f.id, filename="a.htm", doc_type="text.htm",
            sha256="ef" * 32, byte_size=12, edgar_url="http://sec/a.htm"
        )
    ])
    original_a = next(sd for sd in saved if sd.filename == "a.htm")
    assert updated[0].id == original_a.id
    assert updated[0].sha256 == "ef" * 32
    assert updated[0].byte_size == 12

    stored = repo.get_source_documents(f.id)
    assert len(stored) == 2
    assert {sd.filename: sd.sha256 for sd in stored} == {
        "a.htm": "ef" * 32,
        "ex21.htm": "cd" * 32,
    }


def test_get_source_documents_empty():
    repo = Repository()
    c = repo.upsert_company(ticker="EMPTY", cik="0009")
    f = repo.upsert_filing(Filing(company_id=c.id, form_type="10-K", accession_number="009"))
    assert repo.get_source_documents(f.id) == []


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
    
    fact = QualitativeFact(company_id=c.id, category="Risk", summary="Bad")
    cit = Citation(document_id=doc.id, quote="Bad things", start_offset=0, end_offset=10)
    fact.citations.append(cit)
    
    saved = repo.save_qualitative_facts([fact])
    assert len(saved) == 1
    assert saved[0].id is not None
    assert len(saved[0].citations) == 1
    
    # Verify deep eager loading (no DetachedInstanceError outside session)
    assert saved[0].company.ticker == "AAPL"
    assert saved[0].citations[0].document.section == "1A"

def test_get_qualitative_facts():
    repo = Repository()
    c = repo.upsert_company(ticker="GETQFACTS", cik="888")
    f = repo.upsert_filing(Filing(company_id=c.id, form_type="10-K", accession_number="001"))
    doc = repo.save_documents([Document(filing_id=f.id, section="1A", text="text1")])[0]
    
    fact1 = QualitativeFact(company_id=c.id, category="risk_factor", summary="Risk 1")
    cit1 = Citation(document_id=doc.id, quote="Bad things 1", start_offset=0, end_offset=10)
    fact1.citations.append(cit1)
    
    fact2 = QualitativeFact(company_id=c.id, category="competitor", summary="Comp 1")
    cit2 = Citation(document_id=doc.id, quote="Bad things 2", start_offset=11, end_offset=20)
    fact2.citations.append(cit2)
    
    repo.save_qualitative_facts([fact1, fact2])
    
    # Read without session scope (testing eager load)
    all_facts = repo.get_qualitative_facts(company_id=c.id)
    assert len(all_facts) == 2
    assert all_facts[0].category == "competitor"  # alphabetical sort by category
    assert all_facts[1].category == "risk_factor"
    
    # Test relationship eager load outside session
    assert all_facts[0].citations[0].document.section == "1A"
    
    # Test filter
    filtered = repo.get_qualitative_facts(company_id=c.id, category="risk_factor")
    assert len(filtered) == 1
    assert filtered[0].summary == "Risk 1"

def test_get_financial_facts():
    repo = Repository()
    c = repo.upsert_company(ticker="FINFACTS", cik="888")
    
    # Intentionally insert out of chronological order
    fact2 = FinancialFact(company_id=c.id, concept="Revenues", value=200.0, period_end=date(2022, 12, 31))
    fact1 = FinancialFact(company_id=c.id, concept="Revenues", value=100.0, period_end=date(2021, 12, 31))
    fact3 = FinancialFact(company_id=c.id, concept="Assets", value=500.0, period_end=date(2022, 12, 31))
    
    repo.save_financial_facts([fact2, fact1, fact3])
    
    # Test optional concept filter and chronological sorting
    revs = repo.get_financial_facts(company_id=c.id, concept="Revenues")
    assert len(revs) == 2
    assert revs[0].period_end == date(2021, 12, 31)
    assert revs[1].period_end == date(2022, 12, 31)
    
    # Test all facts
    all_facts = repo.get_financial_facts(company_id=c.id)
    assert len(all_facts) == 3

def test_get_latest_filing():
    repo = Repository()
    c = repo.upsert_company(ticker="LATEST", cik="888")
    
    f1 = Filing(company_id=c.id, form_type="10-K", accession_number="001", filed_date=date(2020, 1, 1))
    f2 = Filing(company_id=c.id, form_type="10-K", accession_number="002", filed_date=date(2022, 1, 1))
    f3 = Filing(company_id=c.id, form_type="10-K", accession_number="003", filed_date=date(2021, 1, 1))
    
    repo.upsert_filing(f1)
    repo.upsert_filing(f2)
    repo.upsert_filing(f3)
    
    latest = repo.get_latest_filing(c.id)
    assert latest is not None
    assert latest.accession_number == "002"
    assert latest.filed_date == date(2022, 1, 1)

def test_get_financial_series():
    repo = Repository()
    c = repo.upsert_company(ticker="SERIES", cik="888")
    
    # Valid
    f1 = FinancialFact(company_id=c.id, concept="Revenues", value=100.0, period_end=date(2021, 12, 31))
    # Sentinel date (should be dropped)
    f2 = FinancialFact(company_id=c.id, concept="Revenues", value=200.0, period_end=date(1970, 1, 1))
    # None value (should be dropped)
    f3 = FinancialFact(company_id=c.id, concept="Revenues", value=None, period_end=date(2022, 12, 31))
    # Valid
    f4 = FinancialFact(company_id=c.id, concept="Revenues", value=300.0, period_end=date(2023, 12, 31))
    
    repo.save_financial_facts([f1, f2, f3, f4])
    
    series = repo.get_financial_series(c.id, "Revenues")
    assert len(series) == 2
    assert series[0] == (date(2021, 12, 31), 100.0)
    assert series[1] == (date(2023, 12, 31), 300.0)

def test_rerun_does_not_create_uncited_fact():
    repo = Repository()
    c = repo.upsert_company(ticker="RERUN", cik="123")
    f = repo.upsert_filing(Filing(company_id=c.id, form_type="10-K", accession_number="001"))
    doc = repo.save_documents([Document(filing_id=f.id, section="1A", text="text1")])[0]
    
    # Save first fact
    fact1 = QualitativeFact(company_id=c.id, category="risk_factor", summary="Risk 1")
    cit1 = Citation(document_id=doc.id, quote="span", start_offset=0, end_offset=10)
    fact1.citations.append(cit1)
    
    saved1 = repo.save_qualitative_facts([fact1])
    assert len(saved1) == 1
    
    # Save second fact with different summary but SAME citation span
    fact2 = QualitativeFact(company_id=c.id, category="risk_factor", summary="Risk 2")
    cit2 = Citation(document_id=doc.id, quote="span", start_offset=0, end_offset=10)
    fact2.citations.append(cit2)
    
    saved2 = repo.save_qualitative_facts([fact2])
    # The citation insert for fact2 will fail because the span is already owned by fact1.
    # Therefore fact2 should not be surfaced.
    
    all_facts = repo.get_qualitative_facts(company_id=c.id)
    for fact in all_facts:
        assert len(fact.citations) > 0
    
    assert len(all_facts) == 1
    assert all_facts[0].summary == "Risk 1"
