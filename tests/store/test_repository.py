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
from tearsheet.store.models import Company, Filing, Document, ExtractedSpan, FinancialFact, Citation, SourceDocument

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


def test_extraction_run_and_gap_lifecycle():
    from tearsheet.store.models import ExtractionGap

    repo = Repository()
    c = repo.upsert_company(ticker="RUNCO", cik="0011")
    f = repo.upsert_filing(Filing(company_id=c.id, form_type="10-K", accession_number="011"))

    run = repo.create_extraction_run(company_id=c.id, extractor_version="abc1234")
    assert run.id is not None
    assert run.finished_at is None

    saved = repo.save_extraction_gaps([
        ExtractionGap(run_id=run.id, filing_id=f.id, target="Item 7",
                      status="not_found", detail="missing"),
    ])
    assert saved[0].id is not None

    with pytest.raises(ValueError, match="Unknown gap status"):
        repo.save_extraction_gaps([
            ExtractionGap(run_id=run.id, filing_id=f.id, target="x", status="bogus")
        ])

    repo.finish_extraction_run(run.id)
    gaps = repo.get_extraction_gaps(run.id)
    assert len(gaps) == 1
    assert gaps[0].status == "not_found"


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
    
def test_save_documents_computes_missing_text_hash():
    import hashlib
    repo = Repository()
    c = repo.upsert_company(ticker="HASHCO", cik="0007")
    f = repo.upsert_filing(Filing(company_id=c.id, form_type="10-K", accession_number="007"))

    saved = repo.save_documents([Document(filing_id=f.id, section="1A", text="some text")])
    assert saved[0].text_sha256 == hashlib.sha256(b"some text").hexdigest()


def test_save_documents_rejects_corrupted_hash():
    repo = Repository()
    c = repo.upsert_company(ticker="BADHASH", cik="0008")
    f = repo.upsert_filing(Filing(company_id=c.id, form_type="10-K", accession_number="008"))

    doc = Document(
        filing_id=f.id, section="1A", text="some text",
        text_sha256="0" * 64, extraction_method="sectioner"
    )
    with pytest.raises(ValueError, match="Custody violation"):
        repo.save_documents([doc])


def test_save_documents_persists_custody_fields():
    import hashlib
    repo = Repository()
    c = repo.upsert_company(ticker="CUSTODY", cik="0010")
    f = repo.upsert_filing(Filing(company_id=c.id, form_type="10-K", accession_number="010"))
    sd = repo.upsert_source_documents([
        SourceDocument(
            filing_id=f.id, filename="a.htm", sha256="ab" * 32,
            byte_size=10, edgar_url="http://sec/a.htm"
        )
    ])[0]

    text = "verbatim section text"
    doc = Document(
        filing_id=f.id, source_document_id=sd.id, section="1A", text=text,
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        extraction_method="sectioner",
    )
    saved = repo.save_documents([doc])[0]
    assert saved.source_document_id == sd.id
    assert saved.extraction_method == "sectioner"
    assert saved.text_sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    
def test_save_extracted_spans():
    repo = Repository()
    c = repo.upsert_company(ticker="AAPL", cik="0000320193")
    f = repo.upsert_filing(Filing(company_id=c.id, form_type="10-K", accession_number="001"))
    doc = repo.save_documents([Document(filing_id=f.id, section="1A", text="Bad things happen")])[0]

    span = ExtractedSpan(
        company_id=c.id, category="risk_factor",
        label="Bad", label_start_offset=0, label_end_offset=3,
    )
    cit = Citation(document_id=doc.id, quote="Bad things", start_offset=0, end_offset=10)
    span.citations.append(cit)

    saved = repo.save_extracted_spans([span])
    assert len(saved) == 1
    assert saved[0].id is not None
    assert saved[0].label == "Bad"
    assert saved[0].label_start_offset == 0
    assert saved[0].label_end_offset == 3
    assert len(saved[0].citations) == 1

    # Verify deep eager loading (no DetachedInstanceError outside session)
    assert saved[0].company.ticker == "AAPL"
    assert saved[0].citations[0].document.section == "1A"

def test_get_extracted_spans():
    repo = Repository()
    c = repo.upsert_company(ticker="GETSPANS", cik="888")
    f = repo.upsert_filing(Filing(company_id=c.id, form_type="10-K", accession_number="001"))
    doc = repo.save_documents([Document(filing_id=f.id, section="1A", text="text1")])[0]

    span1 = ExtractedSpan(company_id=c.id, category="risk_factor", label="Risk 1")
    cit1 = Citation(document_id=doc.id, quote="Bad things 1", start_offset=0, end_offset=10)
    span1.citations.append(cit1)

    span2 = ExtractedSpan(company_id=c.id, category="competitor")
    cit2 = Citation(document_id=doc.id, quote="Bad things 2", start_offset=11, end_offset=20)
    span2.citations.append(cit2)

    repo.save_extracted_spans([span1, span2])

    # Read without session scope (testing eager load)
    all_spans = repo.get_extracted_spans(company_id=c.id)
    assert len(all_spans) == 2
    assert all_spans[0].category == "competitor"  # alphabetical sort by category
    assert all_spans[1].category == "risk_factor"

    # Test relationship eager load outside session
    assert all_spans[0].citations[0].document.section == "1A"

    # Test filter
    filtered = repo.get_extracted_spans(company_id=c.id, category="risk_factor")
    assert len(filtered) == 1
    assert filtered[0].label == "Risk 1"

def test_get_financial_facts():
    repo = Repository()
    c = repo.upsert_company(ticker="FINFACTS", cik="888")
    
    # Intentionally insert out of chronological order
    fact2 = FinancialFact(company_id=c.id, concept="Revenues", value=200.0, period_end=date(2022, 12, 31), fiscal_year=2022)
    fact1 = FinancialFact(company_id=c.id, concept="Revenues", value=100.0, period_end=date(2021, 12, 31), fiscal_year=2021)
    fact3 = FinancialFact(company_id=c.id, concept="Assets", value=500.0, period_end=date(2022, 12, 31), fiscal_year=2022)
    
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
    f1 = FinancialFact(company_id=c.id, concept="Revenues", value=100.0, period_end=date(2021, 12, 31), fiscal_year=2021)
    # Sentinel date (should be dropped)
    f2 = FinancialFact(company_id=c.id, concept="Revenues", value=200.0, period_end=date(1970, 1, 1), fiscal_year=2019)
    # None value (should be dropped)
    f3 = FinancialFact(company_id=c.id, concept="Revenues", value=None, period_end=date(2022, 12, 31), fiscal_year=2022)
    # Valid
    f4 = FinancialFact(company_id=c.id, concept="Revenues", value=300.0, period_end=date(2023, 12, 31), fiscal_year=2023)
    
    repo.save_financial_facts([f1, f2, f3, f4])
    
    series = repo.get_financial_series(c.id, "Revenues")
    assert len(series) == 2
    assert series[0] == (date(2021, 12, 31), 100.0)
    assert series[1] == (date(2023, 12, 31), 300.0)

def test_rerun_does_not_create_duplicate_span():
    repo = Repository()
    c = repo.upsert_company(ticker="RERUN", cik="123")
    f = repo.upsert_filing(Filing(company_id=c.id, form_type="10-K", accession_number="001"))
    doc = repo.save_documents([Document(filing_id=f.id, section="1A", text="text1")])[0]

    # Save first span
    span1 = ExtractedSpan(company_id=c.id, category="risk_factor", label="Risk 1")
    cit1 = Citation(document_id=doc.id, quote="span", start_offset=0, end_offset=10)
    span1.citations.append(cit1)

    saved1 = repo.save_extracted_spans([span1])
    assert len(saved1) == 1

    # Save second span with a different label but the SAME citation span (re-run)
    span2 = ExtractedSpan(company_id=c.id, category="risk_factor", label="Risk 2")
    cit2 = Citation(document_id=doc.id, quote="span", start_offset=0, end_offset=10)
    span2.citations.append(cit2)

    saved2 = repo.save_extracted_spans([span2])
    # The citation insert for span2 collides with span1's citation, so span2
    # is a duplicate and must not be kept.
    assert len(saved2) == 0

    all_spans = repo.get_extracted_spans(company_id=c.id)
    for span in all_spans:
        assert len(span.citations) > 0

    assert len(all_spans) == 1
    assert all_spans[0].label == "Risk 1"
