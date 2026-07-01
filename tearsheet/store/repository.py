"""Read/write helpers — the query surface the writer uses later."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from tearsheet.store.db import session_scope
from tearsheet.store.models import (
    GAP_STATUSES,
    Citation,
    Company,
    Document,
    ExtractedSpan,
    ExtractionGap,
    ExtractionRun,
    Filing,
    FinancialFact,
    SourceDocument,
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

    def get_extracted_spans(
        self, company_id: int, category: str | None = None
    ) -> list[ExtractedSpan]:
        """All extracted spans for a company, optionally filtered to one category.

        Eager-loads ``citations -> document`` so the renderer can show spans and
        section outside the session (mirrors ``save_extracted_spans``).

        Results are ordered by ``(category, id)``.
        """
        from sqlalchemy.orm import selectinload
        with self._session_ctx() as session:
            stmt = select(ExtractedSpan).where(ExtractedSpan.company_id == company_id)
            if category is not None:
                stmt = stmt.where(ExtractedSpan.category == category)
            stmt = stmt.options(
                selectinload(ExtractedSpan.citations).selectinload(Citation.document)
            )
            stmt = stmt.order_by(ExtractedSpan.category, ExtractedSpan.id)
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
        - Restatements coexist as rows under different accessions; per
          ``period_end`` the **latest accession's view wins** (accession numbers
          for a company's own filings sort chronologically).
        """
        facts = self.get_financial_facts(company_id=company_id, concept=concept)
        sentinel_date = date(1970, 1, 1)

        best: dict[date, FinancialFact] = {}
        for f in facts:
            if f.period_end == sentinel_date or f.value is None:
                continue
            current = best.get(f.period_end)
            if current is None or (f.accession_number or "") > (current.accession_number or ""):
                best[f.period_end] = f

        return [(d, float(best[d].value)) for d in sorted(best)]

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

    # --- ExtractionRun / ExtractionGap ---

    def create_extraction_run(
        self, *, company_id: int, extractor_version: str
    ) -> ExtractionRun:
        with self._session_ctx() as session:
            run = ExtractionRun(company_id=company_id, extractor_version=extractor_version)
            session.add(run)
            session.flush()
            return run

    def finish_extraction_run(self, run_id: int) -> None:
        from datetime import datetime, timezone
        from sqlalchemy import update
        with self._session_ctx() as session:
            session.execute(
                update(ExtractionRun)
                .where(ExtractionRun.id == run_id)
                .values(finished_at=datetime.now(timezone.utc))
            )

    def save_extraction_gaps(self, gaps: list[ExtractionGap]) -> list[ExtractionGap]:
        if not gaps:
            return []
        for g in gaps:
            if g.status not in GAP_STATUSES:
                raise ValueError(f"Unknown gap status: {g.status}")
        with self._session_ctx() as session:
            session.add_all(gaps)
            session.flush()
            return gaps

    def get_extraction_gaps(self, run_id: int) -> list[ExtractionGap]:
        with self._session_ctx() as session:
            stmt = (
                select(ExtractionGap)
                .where(ExtractionGap.run_id == run_id)
                .order_by(ExtractionGap.id)
            )
            return list(session.scalars(stmt).all())

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

    # --- SourceDocument ---

    def upsert_source_documents(
        self, source_documents: list[SourceDocument]
    ) -> list[SourceDocument]:
        """Insert or refresh archived-file records, keyed by (filing_id, filename)."""
        if not source_documents:
            return []

        from sqlalchemy.dialects.sqlite import insert

        doc_ids = []
        with self._session_ctx() as session:
            for sd in source_documents:
                stmt = insert(SourceDocument).values(
                    filing_id=sd.filing_id,
                    filename=sd.filename,
                    sequence=sd.sequence,
                    doc_type=sd.doc_type,
                    sha256=sd.sha256,
                    byte_size=sd.byte_size,
                    edgar_url=sd.edgar_url,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["filing_id", "filename"],
                    set_=dict(
                        sequence=stmt.excluded.sequence,
                        doc_type=stmt.excluded.doc_type,
                        sha256=stmt.excluded.sha256,
                        byte_size=stmt.excluded.byte_size,
                        edgar_url=stmt.excluded.edgar_url,
                    ),
                ).returning(SourceDocument.id)
                doc_ids.append(session.scalar(stmt))

            return list(session.scalars(
                select(SourceDocument).where(SourceDocument.id.in_(doc_ids))
            ).all())

    def get_source_documents(self, filing_id: int) -> list[SourceDocument]:
        with self._session_ctx() as session:
            stmt = (
                select(SourceDocument)
                .where(SourceDocument.filing_id == filing_id)
                .order_by(SourceDocument.filename)
            )
            return list(session.scalars(stmt).all())

    # --- Document ---

    def save_documents(self, documents: list[Document]) -> list[Document]:
        if not documents:
            return []

        import hashlib
        from sqlalchemy.dialects.sqlite import insert
        from sqlalchemy.orm import selectinload

        doc_ids = []
        with self._session_ctx() as session:
            for doc in documents:
                computed = hashlib.sha256(doc.text.encode("utf-8")).hexdigest()
                if doc.text_sha256 is not None and doc.text_sha256 != computed:
                    raise ValueError(
                        f"Custody violation: text hash mismatch for section {doc.section} "
                        f"(stamped {doc.text_sha256}, computed {computed})"
                    )
                stmt = insert(Document).values(
                    filing_id=doc.filing_id,
                    source_document_id=doc.source_document_id,
                    run_id=doc.run_id,
                    section=doc.section,
                    title=doc.title,
                    text=doc.text,
                    text_sha256=computed,
                    extraction_method=doc.extraction_method,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["filing_id", "section"],
                    set_=dict(
                        source_document_id=stmt.excluded.source_document_id,
                        run_id=stmt.excluded.run_id,
                        title=stmt.excluded.title,
                        text=stmt.excluded.text,
                        text_sha256=stmt.excluded.text_sha256,
                        extraction_method=stmt.excluded.extraction_method,
                    )
                ).returning(Document.id)
                doc_ids.append(session.scalar(stmt))
                
            return list(session.scalars(
                select(Document)
                .where(Document.id.in_(doc_ids))
                .options(selectinload(Document.filing))
            ).all())

    # --- Facts ---

    def save_financial_facts(self, facts: list[FinancialFact]) -> list[FinancialFact]:
        """Upsert facts on their restatement-safe identity
        ``(company, xbrl_concept, fiscal_year, fiscal_period, accession)``.
        Missing identity parts coalesce to sentinels so re-runs stay idempotent
        (SQLite treats NULLs in a unique constraint as always-distinct)."""
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
                    run_id=f.run_id,
                    concept=f.concept,
                    xbrl_concept=f.xbrl_concept or f.concept,
                    accession_number=f.accession_number or "",
                    context_ref=f.context_ref,
                    unit_ref=f.unit_ref,
                    fiscal_year=f.fiscal_year if f.fiscal_year is not None else 0,
                    fiscal_period=f.fiscal_period or "",
                    label=f.label,
                    unit=f.unit,
                    period_end=p_end,
                    value=f.value,
                    as_filed_value=f.as_filed_value,
                    derivation=f.derivation,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=[
                        "company_id", "xbrl_concept", "fiscal_year",
                        "fiscal_period", "accession_number",
                    ],
                    set_=dict(
                        run_id=stmt.excluded.run_id,
                        context_ref=stmt.excluded.context_ref,
                        unit_ref=stmt.excluded.unit_ref,
                        label=stmt.excluded.label,
                        unit=stmt.excluded.unit,
                        period_end=stmt.excluded.period_end,
                        value=stmt.excluded.value,
                        as_filed_value=stmt.excluded.as_filed_value,
                        derivation=stmt.excluded.derivation,
                    )
                ).returning(FinancialFact.id)
                fact_ids.append(session.scalar(stmt))

            return list(session.scalars(
                select(FinancialFact).where(FinancialFact.id.in_(fact_ids))
            ).all())

    def save_extracted_spans(
        self,
        spans: list[ExtractedSpan],
    ) -> list[ExtractedSpan]:
        """Persist extracted spans. Identity is the citation span itself:
        a span whose citations all collide with rows owned by other
        ExtractedSpans is a re-run duplicate and is not kept."""
        if not spans:
            return []

        from sqlalchemy import delete
        from sqlalchemy.dialects.sqlite import insert
        from sqlalchemy.orm import selectinload

        with self._session_ctx() as session:
            saved_ids = []
            for s in spans:
                if not s.citations:
                    continue

                stmt = insert(ExtractedSpan).values(
                    company_id=s.company_id,
                    run_id=s.run_id,
                    category=s.category,
                    label=s.label,
                    label_start_offset=s.label_start_offset,
                    label_end_offset=s.label_end_offset,
                ).returning(ExtractedSpan.id)
                s_id = session.scalar(stmt)

                attached = False
                for c in s.citations:
                    c_stmt = insert(Citation).values(
                        extracted_span_id=s_id,
                        document_id=c.document_id,
                        quote=c.quote,
                        start_offset=c.start_offset,
                        end_offset=c.end_offset
                    )
                    c_stmt = c_stmt.on_conflict_do_nothing(
                        index_elements=["document_id", "start_offset", "end_offset"]
                    ).returning(Citation.id)
                    inserted_id = session.scalar(c_stmt)
                    if inserted_id is not None:
                        attached = True

                if attached:
                    saved_ids.append(s_id)
                else:
                    # Every citation collided with a span already stored (re-run
                    # duplicate) — discard the freshly inserted row.
                    session.execute(delete(ExtractedSpan).where(ExtractedSpan.id == s_id))

            return list(session.scalars(
                select(ExtractedSpan)
                .where(ExtractedSpan.id.in_(saved_ids))
                .options(
                    selectinload(ExtractedSpan.company),
                    selectinload(ExtractedSpan.citations).selectinload(Citation.document)
                )
            ).all())
