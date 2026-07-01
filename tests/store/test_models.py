import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import date
from tearsheet.store.models import Base, Company, Filing, Document, ExtractedSpan, FinancialFact, Citation

@pytest.fixture(scope="function")
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)

@pytest.fixture(scope="function")
def session(engine):
    with Session(engine) as session:
        yield session

def test_company_creation(session: Session):
    company = Company(ticker="AAPL", cik="0000320193", name="Apple Inc.")
    session.add(company)
    session.commit()
    
    assert company.id is not None
    assert company.created_at is not None

def test_company_unique_constraints(session: Session):
    c1 = Company(ticker="AAPL", cik="0000320193")
    session.add(c1)
    session.commit()
    
    # Test ticker uniqueness
    c2 = Company(ticker="AAPL", cik="0000320194")
    session.add(c2)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    
    # Test cik uniqueness
    c3 = Company(ticker="MSFT", cik="0000320193")
    session.add(c3)
    with pytest.raises(IntegrityError):
        session.commit()

def test_filing_relationships(session: Session):
    company = Company(ticker="AAPL", cik="0000320193")
    filing = Filing(
        company=company,
        form_type="10-K",
        accession_number="0000320193-23-000106",
        filed_date=date(2023, 11, 3)
    )
    session.add(filing)
    session.commit()
    
    assert filing.id is not None
    assert filing.company_id == company.id
    assert len(company.filings) == 1
    assert company.filings[0].accession_number == "0000320193-23-000106"

def test_document_and_citation_relationships(session: Session):
    company = Company(ticker="AAPL", cik="0000320193")
    filing = Filing(
        company=company,
        form_type="10-K",
        accession_number="0000320193-23-000106"
    )
    doc = Document(
        filing=filing,
        section="1A",
        title="Risk Factors",
        text="Lots of text here."
    )
    span = ExtractedSpan(
        company=company,
        category="risk_factor",
        label="Lots of text",
        label_start_offset=0,
        label_end_offset=12,
    )
    citation = Citation(
        extracted_span=span,
        document=doc,
        quote="Lots of text",
        start_offset=0,
        end_offset=12
    )
    session.add_all([company, filing, doc, span, citation])
    session.commit()

    assert len(doc.citations) == 1
    assert doc.citations[0].extracted_span_id == span.id
    assert len(span.citations) == 1
    assert span.citations[0].document_id == doc.id
    assert len(company.extracted_spans) == 1

def test_financial_fact(session: Session):
    company = Company(ticker="AAPL", cik="0000320193")
    fact = FinancialFact(
        company=company,
        concept="Revenues",
        label="Total net sales",
        unit="USD",
        period_end=date(2023, 9, 30),
        value=383285000000.0
    )
    session.add(fact)
    session.commit()
    
    assert fact.id is not None
    assert fact.company_id == company.id
    assert company.financial_facts[0].concept == "Revenues"

def test_document_unique_constraint(session: Session):
    c = Company(ticker="TESTD", cik="0002")
    session.add(c)
    session.flush()
    f = Filing(company_id=c.id, form_type="10-K", accession_number="0002")
    session.add(f)
    session.flush()
    
    d1 = Document(filing_id=f.id, section="1A", text="a")
    session.add(d1)
    session.commit()
    
    d2 = Document(filing_id=f.id, section="1A", text="b")
    session.add(d2)
    with pytest.raises(IntegrityError):
        session.commit()
