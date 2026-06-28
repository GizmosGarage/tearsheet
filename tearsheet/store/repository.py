"""Read/write helpers — the query surface the writer uses later."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import date

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
        from sqlalchemy.dialects.sqlite import insert
        with self._session_ctx() as session:
            stmt = insert(Company).values(ticker=ticker, cik=cik, name=name)
            set_dict = {"cik": stmt.excluded.cik}
            if name is not None:
                set_dict["name"] = stmt.excluded.name
                
            stmt = stmt.on_conflict_do_update(
                index_elements=["ticker"],
                set_=set_dict
            ).returning(Company.id)
            
            c_id = session.scalar(stmt)
            return session.scalar(select(Company).where(Company.id == c_id))

    def get_company_by_ticker(self, ticker: str) -> Company | None:
        with self._session_ctx() as session:
            return session.scalar(select(Company).where(Company.ticker == ticker))

    # --- Read surface (writer layer) ---

    def get_qualitative_facts(
        self, company_id: int, category: str | None = None
    ) -> list[QualitativeFact]:
        """All qualitative facts for a company, optionally filtered to one category.

        Eager-loads ``citations -> document`` so the renderer can show spans and
        section outside the session (mirrors ``save_qualitative_facts``).

        Results are ordered by ``(category, id)``.
        """
        from sqlalchemy.orm import selectinload
        with self._session_ctx() as session:
            stmt = select(QualitativeFact).where(QualitativeFact.company_id == company_id)
            if category is not None:
                stmt = stmt.where(QualitativeFact.category == category)
            stmt = stmt.options(
                selectinload(QualitativeFact.citations).selectinload(Citation.document)
            )
            stmt = stmt.order_by(QualitativeFact.category, QualitativeFact.id)
            return list(session.scalars(stmt).all())

    def get_financial_facts(
        self, company_id: int, concept: str | None = None
    ) -> list[FinancialFact]:
        """Raw financial facts, optionally filtered to one concept.

        Results are ordered by ``period_end`` ascending.
        """
        with self._session_ctx() as session:
            stmt = select(FinancialFact).where(FinancialFact.company_id == company_id)
            if concept is not None:
                stmt = stmt.where(FinancialFact.concept == concept)
            stmt = stmt.order_by(FinancialFact.period_end.asc())
            return list(session.scalars(stmt).all())

    def get_financial_series(
        self, company_id: int, concept: str
    ) -> list[tuple[date, float]]:
        """Convenience wrapper: ``(period_end, value)`` points for one concept.

        Sorted ascending by ``period_end``. This is the metrics layer's primary
        input and **must centralize data hygiene** so math never re-implements it:

        - **Exclude** the ``1970-01-01`` sentinel (missing-date facts persisted by
          ``save_financial_facts`` when ``period_end`` is NULL).
        - **Exclude** rows where ``value`` is NULL.

        Checklist (Part A1):
        - [ ] Delegate to ``get_financial_facts`` or equivalent query
        - [ ] Filter out ``period_end == date(1970, 1, 1)``
        - [ ] Filter out ``value is None``
        - [ ] Return ``list[tuple[date, float]]`` sorted ASC
        """
        pass

    def get_latest_filing(self, company_id: int) -> Filing | None:
        """Most recent filing for dossier header provenance.

        Ordered by ``filed_date`` descending, then ``id`` descending as tiebreaker.
        """
        with self._session_ctx() as session:
            stmt = (
                select(Filing)
                .where(Filing.company_id == company_id)
                .order_by(Filing.filed_date.desc(), Filing.id.desc())
            )
            return session.scalars(stmt).first()

    # --- Filing ---

    def upsert_filing(self, filing: Filing) -> Filing:
        from sqlalchemy.dialects.sqlite import insert
        from sqlalchemy.orm import selectinload
        with self._session_ctx() as session:
            stmt = insert(Filing).values(
                company_id=filing.company_id,
                form_type=filing.form_type,
                accession_number=filing.accession_number,
                filed_date=filing.filed_date,
                raw_cache_path=filing.raw_cache_path
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["accession_number"],
                set_=dict(
                    form_type=stmt.excluded.form_type,
                    filed_date=stmt.excluded.filed_date,
                    raw_cache_path=stmt.excluded.raw_cache_path
                )
            ).returning(Filing.id)
            f_id = session.scalar(stmt)
            
            return session.scalar(
                select(Filing)
                .where(Filing.id == f_id)
                .options(selectinload(Filing.company))
            )

    # --- Document ---

    def save_documents(self, documents: list[Document]) -> list[Document]:
        if not documents:
            return []
            
        from sqlalchemy.dialects.sqlite import insert
        from sqlalchemy.orm import selectinload
        
        doc_ids = []
        with self._session_ctx() as session:
            for doc in documents:
                stmt = insert(Document).values(
                    filing_id=doc.filing_id,
                    section=doc.section,
                    title=doc.title,
                    text=doc.text
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["filing_id", "section"],
                    set_=dict(title=stmt.excluded.title, text=stmt.excluded.text)
                ).returning(Document.id)
                doc_ids.append(session.scalar(stmt))
                
            return list(session.scalars(
                select(Document)
                .where(Document.id.in_(doc_ids))
                .options(selectinload(Document.filing))
            ).all())

    # --- Facts ---

    def save_financial_facts(self, facts: list[FinancialFact]) -> list[FinancialFact]:
        if not facts:
            return []
            
        from sqlalchemy.dialects.sqlite import insert
        from datetime import date
        fact_ids = []
        with self._session_ctx() as session:
            for f in facts:
                p_end = f.period_end or date(1970, 1, 1)
                stmt = insert(FinancialFact).values(
                    company_id=f.company_id,
                    concept=f.concept,
                    label=f.label,
                    unit=f.unit,
                    period_end=p_end,
                    value=f.value
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["company_id", "concept", "period_end"],
                    set_=dict(
                        label=stmt.excluded.label,
                        unit=stmt.excluded.unit,
                        value=stmt.excluded.value
                    )
                ).returning(FinancialFact.id)
                fact_ids.append(session.scalar(stmt))
                
            return list(session.scalars(
                select(FinancialFact).where(FinancialFact.id.in_(fact_ids))
            ).all())

    def save_qualitative_facts(
        self,
        facts: list[QualitativeFact],
    ) -> list[QualitativeFact]:
        if not facts:
            return []
            
        from sqlalchemy.dialects.sqlite import insert
        from sqlalchemy.orm import selectinload
        
        with self._session_ctx() as session:
            saved_facts = []
            for f in facts:
                stmt = insert(QualitativeFact).values(
                    company_id=f.company_id,
                    category=f.category,
                    summary=f.summary
                )
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=["company_id", "category", "summary"]
                ).returning(QualitativeFact.id)
                
                f_id = session.scalar(stmt)
                if not f_id:
                    f_id = session.scalar(
                        select(QualitativeFact.id)
                        .where(QualitativeFact.company_id == f.company_id)
                        .where(QualitativeFact.category == f.category)
                        .where(QualitativeFact.summary == f.summary)
                    )
                
                if f_id:
                    saved_facts.append(f_id)
                    for c in f.citations:
                        c_stmt = insert(Citation).values(
                            qualitative_fact_id=f_id,
                            document_id=c.document_id,
                            quote=c.quote,
                            start_offset=c.start_offset,
                            end_offset=c.end_offset
                        )
                        c_stmt = c_stmt.on_conflict_do_nothing(
                            index_elements=["document_id", "start_offset", "end_offset"]
                        )
                        session.execute(c_stmt)
                        
            return list(session.scalars(
                select(QualitativeFact)
                .where(QualitativeFact.id.in_(saved_facts))
                .options(
                    selectinload(QualitativeFact.company),
                    selectinload(QualitativeFact.citations).selectinload(Citation.document)
                )
            ).all())
