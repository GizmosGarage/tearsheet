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
        raise NotImplementedError

    def get_company_by_ticker(self, ticker: str) -> Company | None:
        with self._session_ctx() as session:
            return session.scalar(select(Company).where(Company.ticker == ticker))

    # --- Filing ---

    def upsert_filing(self, filing: Filing) -> Filing:
        raise NotImplementedError

    # --- Document ---

    def save_documents(self, documents: list[Document]) -> list[Document]:
        raise NotImplementedError

    # --- Facts ---

    def save_financial_facts(self, facts: list[FinancialFact]) -> list[FinancialFact]:
        raise NotImplementedError

    def save_qualitative_facts(
        self,
        facts: list[QualitativeFact],
        citations: list[Citation],
    ) -> list[QualitativeFact]:
        raise NotImplementedError
