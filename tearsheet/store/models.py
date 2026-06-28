"""ORM models: Company, Filing, Document, FinancialFact, QualitativeFact, Citation."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, func, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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
    qualitative_facts: Mapped[list[QualitativeFact]] = relationship(back_populates="company")


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


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("filing_id", "section", name="uix_document_filing_section"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id"), index=True)
    section: Mapped[str] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    filing: Mapped[Filing] = relationship(back_populates="documents")
    citations: Mapped[list[Citation]] = relationship(back_populates="document")


class FinancialFact(Base):
    __tablename__ = "financial_facts"
    __table_args__ = (UniqueConstraint("company_id", "concept", "period_end", name="uix_financial_fact_concept"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    concept: Mapped[str] = mapped_column(String(128), index=True)
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    company: Mapped[Company] = relationship(back_populates="financial_facts")


class QualitativeFact(Base):
    __tablename__ = "qualitative_facts"
    __table_args__ = (UniqueConstraint("company_id", "category", "summary", name="uix_qualitative_fact"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    company: Mapped[Company] = relationship(back_populates="qualitative_facts")
    citations: Mapped[list[Citation]] = relationship(back_populates="qualitative_fact")


class Citation(Base):
    __tablename__ = "citations"
    __table_args__ = (UniqueConstraint("document_id", "start_offset", "end_offset", name="uix_citation_document_span"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    qualitative_fact_id: Mapped[int] = mapped_column(
        ForeignKey("qualitative_facts.id"), index=True
    )
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    quote: Mapped[str] = mapped_column(Text)
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    qualitative_fact: Mapped[QualitativeFact] = relationship(back_populates="citations")
    document: Mapped[Document] = relationship(back_populates="citations")
