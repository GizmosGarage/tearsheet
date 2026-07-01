"""ORM models: Company, Filing, SourceDocument, Document, FinancialFact,
ExtractedSpan, Citation, ExtractionRun, ExtractionGap."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

GAP_STATUSES = ("not_present", "not_found", "rejected_by_gate", "failed")


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    cik: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    filings: Mapped[list[Filing]] = relationship(back_populates="company")
    financial_facts: Mapped[list[FinancialFact]] = relationship(back_populates="company")
    extracted_spans: Mapped[list[ExtractedSpan]] = relationship(back_populates="company")


class ExtractionRun(Base):
    """One pipeline execution: which extractor version produced what, when."""

    __tablename__ = "extraction_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    extractor_version: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    gaps: Mapped[list[ExtractionGap]] = relationship(back_populates="run")


class ExtractionGap(Base):
    """A typed record of something sought but not emitted. Statuses:
    not_present | not_found | rejected_by_gate | failed (see GAP_STATUSES)."""

    __tablename__ = "extraction_gaps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("extraction_runs.id"), index=True)
    filing_id: Mapped[int | None] = mapped_column(ForeignKey("filings.id"), index=True, nullable=True)
    target: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    run: Mapped[ExtractionRun] = relationship(back_populates="gaps")


class Filing(Base):
    __tablename__ = "filings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    form_type: Mapped[str] = mapped_column(String(16))
    accession_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    filed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    raw_cache_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    company: Mapped[Company] = relationship(back_populates="filings")
    documents: Mapped[list[Document]] = relationship(back_populates="filing")
    source_documents: Mapped[list[SourceDocument]] = relationship(back_populates="filing")


class SourceDocument(Base):
    """An archived raw file from an accession; the provenance anchor for all extracted content."""

    __tablename__ = "source_documents"
    __table_args__ = (UniqueConstraint("filing_id", "filename", name="uix_source_document_filing_filename"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id"), index=True)
    filename: Mapped[str] = mapped_column(String(256))
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doc_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    byte_size: Mapped[int] = mapped_column(Integer)
    edgar_url: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    filing: Mapped[Filing] = relationship(back_populates="source_documents")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("filing_id", "section", name="uix_document_filing_section"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id"), index=True)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id"), index=True, nullable=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("extraction_runs.id"), index=True, nullable=True
    )
    section: Mapped[str] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    text_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extraction_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    filing: Mapped[Filing] = relationship(back_populates="documents")
    source_document: Mapped[SourceDocument | None] = relationship()
    citations: Mapped[list[Citation]] = relationship(back_populates="document")


class FinancialFact(Base):
    """A financial value with full XBRL ancestry. ``derivation`` is NULL for
    as-filed facts; derived facts carry machine-readable arithmetic over
    other facts' identities and have no ``as_filed_value``. Restatements
    coexist as separate rows keyed by accession."""

    __tablename__ = "financial_facts"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "xbrl_concept", "fiscal_year", "fiscal_period",
            "accession_number", name="uix_financial_fact_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("extraction_runs.id"), index=True, nullable=True
    )
    concept: Mapped[str] = mapped_column(String(128), index=True)
    xbrl_concept: Mapped[str | None] = mapped_column(String(256), index=True, nullable=True)
    accession_number: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    context_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    unit_ref: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_period: Mapped[str | None] = mapped_column(String(8), nullable=True)
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False, default=date(1970, 1, 1))
    value: Mapped[float | None] = mapped_column(Numeric(asdecimal=False), nullable=True)
    as_filed_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    derivation: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    company: Mapped[Company] = relationship(back_populates="financial_facts")


class ExtractedSpan(Base):
    """A verbatim span extracted from a filing. Never carries authored text:
    ``label`` is always a source slice, located by its own offsets."""

    __tablename__ = "extracted_spans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("extraction_runs.id"), index=True, nullable=True
    )
    category: Mapped[str] = mapped_column(String(64), index=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    label_start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label_end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    company: Mapped[Company] = relationship(back_populates="extracted_spans")
    citations: Mapped[list[Citation]] = relationship(back_populates="extracted_span")


class Citation(Base):
    __tablename__ = "citations"
    __table_args__ = (UniqueConstraint("document_id", "start_offset", "end_offset", name="uix_citation_document_span"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    extracted_span_id: Mapped[int] = mapped_column(
        ForeignKey("extracted_spans.id"), index=True
    )
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    quote: Mapped[str] = mapped_column(Text)
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    extracted_span: Mapped[ExtractedSpan] = relationship(back_populates="citations")
    document: Mapped[Document] = relationship(back_populates="citations")
