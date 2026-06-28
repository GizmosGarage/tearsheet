"""Read/write helpers — the query surface the writer uses later."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.orm import Session

from tearsheet.store.db import session_scope
from tearsheet.store.models import (
    Citation,
    Company,
    Document,
    Filing,
    FinancialFact,
    QualitativeFact,
)


class Repository:
    """Thin persistence layer over SQLAlchemy models."""

    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    @contextmanager
    def _session_ctx(self) -> Generator[Session, None, None]:
        if self._session is not None:
            yield self._session
        else:
            with session_scope() as session:
                yield session

    # --- Company ---

    def upsert_company(self, *, ticker: str, cik: str, name: str | None = None) -> Company:
        """Insert or update a company by ticker."""
        with self._session_ctx() as session:
            company = session.scalar(select(Company).where(Company.ticker == ticker))
            if company:
                company.cik = cik
                if name is not None:
                    company.name = name
            else:
                company = Company(ticker=ticker, cik=cik, name=name)
                session.add(company)
            session.flush()
            return company

    def get_company_by_ticker(self, ticker: str) -> Company | None:
        with self._session_ctx() as session:
            return session.scalar(select(Company).where(Company.ticker == ticker))

    # --- Filing ---

    def upsert_filing(self, filing: Filing) -> Filing:
        with self._session_ctx() as session:
            existing = session.scalar(select(Filing).where(Filing.accession_number == filing.accession_number))
            if existing:
                existing.company_id = filing.company_id
                existing.form_type = filing.form_type
                existing.filed_date = filing.filed_date
                existing.raw_cache_path = filing.raw_cache_path
                session.flush()
                return existing
            else:
                session.add(filing)
                session.flush()
                return filing

    # --- Document ---

    def save_documents(self, documents: list[Document]) -> list[Document]:
        with self._session_ctx() as session:
            session.add_all(documents)
            session.flush()
            return documents

    # --- Facts ---

    def save_financial_facts(self, facts: list[FinancialFact]) -> list[FinancialFact]:
        with self._session_ctx() as session:
            session.add_all(facts)
            session.flush()
            return facts

    def save_qualitative_facts(
        self,
        facts: list[QualitativeFact],
    ) -> list[QualitativeFact]:
        with self._session_ctx() as session:
            session.add_all(facts)
            session.flush()
            return facts
