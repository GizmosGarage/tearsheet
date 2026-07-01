"""Master orchestration pipeline."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import tearsheet
from tearsheet.edgar.tickers import resolve_ticker_to_cik
from tearsheet.edgar.submissions import get_filing_history
from tearsheet.edgar.filings import locate_filing, acquire_filing
from tearsheet.edgar.xbrl import fetch_companyfacts
from tearsheet.parse.documents import build_documents
from tearsheet.extract.qualitative import extract_risk_factors, extract_business, extract_management_discussion
from tearsheet.extract.financials import extract_financial_facts, FINANCIAL_CONCEPTS
from tearsheet.store.repository import Repository
from tearsheet.store.models import ExtractionGap, Filing, FinancialFact, SourceDocument

logger = logging.getLogger(__name__)


def _extractor_version() -> str:
    """Git commit of the extractor producing this corpus; package version as fallback."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=Path(__file__).resolve().parent,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return tearsheet.__version__


class ExecutionPipeline:
    def __init__(self, repo: Repository | None = None):
        self.repo = repo or Repository()

    def run_for_ticker(self, ticker: str) -> dict:
        """Run the end-to-end extraction pipeline for a ticker."""
        logger.info(f"Resolving ticker {ticker}")
        cik = resolve_ticker_to_cik(ticker)

        logger.info(f"Fetching filing history for CIK {cik}")
        history = get_filing_history(cik)
        company_name = history.get("name", ticker)

        # Upsert company
        company = self.repo.upsert_company(ticker=ticker.upper(), cik=cik, name=company_name)

        run = self.repo.create_extraction_run(
            company_id=company.id, extractor_version=_extractor_version()
        )
        gaps: list[ExtractionGap] = []
        logger.info(f"Extraction run {run.id} (version {run.extractor_version})")

        logger.info(f"Locating latest 10-K for {ticker}")
        filing_meta = locate_filing(cik, "10-K")
        accession_number = filing_meta["accessionNumber"]

        # Upsert filing
        filing_obj = Filing(
            company_id=company.id,
            form_type="10-K",
            accession_number=accession_number
        )
        filing = self.repo.upsert_filing(filing_obj)

        saved_fin_facts = []

        # Financial Branch
        try:
            logger.info(f"Fetching XBRL companyfacts for CIK {cik}")
            companyfacts = fetch_companyfacts(cik)
            logger.info(f"Extracting financial facts for {ticker}")
            fin_facts = extract_financial_facts(company.id, companyfacts)
            for f in fin_facts:
                f.run_id = run.id
            logger.info(f"Saving {len(fin_facts)} financial facts to repository")
            saved_fin_facts = self.repo.save_financial_facts(fin_facts)

            found_concepts = {f.concept for f in saved_fin_facts if f.derivation is None}
            for concept in FINANCIAL_CONCEPTS:
                if concept not in found_concepts:
                    gaps.append(ExtractionGap(
                        run_id=run.id,
                        filing_id=filing.id,
                        target=f"us-gaap:{concept}",
                        status="not_found",
                        detail=f"Concept absent from companyfacts annual data for {ticker.upper()}",
                    ))
        except Exception as e:
            logger.error(f"Financials extraction failed: {e}")
            gaps.append(ExtractionGap(
                run_id=run.id,
                filing_id=filing.id,
                target="financials",
                status="failed",
                detail=f"Financials extraction failed: {e}",
            ))
            
        logger.info(f"Archiving accession {accession_number}")
        stored_sources = self.repo.get_source_documents(filing.id)
        known_hashes = {sd.filename: sd.sha256 for sd in stored_sources}
        acquisition = acquire_filing(cik, accession_number, known_hashes=known_hashes)

        source_docs = [
            SourceDocument(
                filing_id=filing.id,
                filename=d["filename"],
                sequence=d["sequence"],
                doc_type=d["doc_type"],
                sha256=d["sha256"],
                byte_size=d["byte_size"],
                edgar_url=d["edgar_url"],
            )
            for d in acquisition["documents"]
        ]
        saved_sources = self.repo.upsert_source_documents(source_docs)
        logger.info(f"Archived {len(saved_sources)} source documents for {accession_number}")

        raw_html_path = acquisition["primary_path"]
        primary_source_id = next(
            sd.id for sd in saved_sources
            if sd.filename == acquisition["primary_document"]
        )

        logger.info(f"Parsing sections from {raw_html_path}")
        documents = build_documents(
            filing.id, raw_html_path, source_document_id=primary_source_id
        )
        for d in documents:
            d.run_id = run.id

        logger.info("Saving document sections to repository")
        saved_docs = self.repo.save_documents(documents)

        docs_by_section = {d.section: d for d in saved_docs}
        all_spans = []
        routes = [
            ("1A", extract_risk_factors),
            ("1",  extract_business),
            ("7",  extract_management_discussion)
        ]

        for section, extractor in routes:
            doc = docs_by_section.get(section)
            if doc is None:
                logger.warning(f"Section {section} not found for {ticker}")
                gaps.append(ExtractionGap(
                    run_id=run.id,
                    filing_id=filing.id,
                    target=f"Item {section}",
                    status="not_found",
                    detail=f"Section {section} not found for {ticker.upper()}",
                ))
                continue

            logger.info(f"Extracting spans from Item {section} (ID: {doc.id})")
            try:
                extraction = extractor(doc)
                all_spans.extend(extraction.spans)
                for rejected in extraction.rejected:
                    gaps.append(ExtractionGap(
                        run_id=run.id,
                        filing_id=filing.id,
                        target=f"Item {section} span",
                        status="rejected_by_gate",
                        detail=rejected.exact_quote[:200],
                    ))
            except Exception as e:
                logger.error(f"{section} extraction failed: {e}")
                gaps.append(ExtractionGap(
                    run_id=run.id,
                    filing_id=filing.id,
                    target=f"Item {section}",
                    status="failed",
                    detail=f"{section} extraction failed: {e}",
                ))

        # Global span-deduplication across all categories
        seen_spans = set()
        unique_spans = []
        discarded_uncited = 0
        for span in all_spans:
            if not span.citations:
                discarded_uncited += 1
                continue
            cit = span.citations[0]
            span_key = (cit.document_id, cit.start_offset, cit.end_offset)
            if span_key not in seen_spans:
                seen_spans.add(span_key)
                unique_spans.append(span)

        if discarded_uncited:
            logger.warning(f"Discarded {discarded_uncited} uncited spans before save")

        for span in unique_spans:
            span.run_id = run.id

        logger.info(f"Saving {len(unique_spans)} extracted spans to repository")
        saved_spans = self.repo.save_extracted_spans(unique_spans)

        saved_gaps = self.repo.save_extraction_gaps(gaps)
        self.repo.finish_extraction_run(run.id)

        logger.info(f"Pipeline complete for {ticker} ({len(saved_gaps)} gaps)")

        gap_counts: dict[str, int] = {}
        for g in saved_gaps:
            gap_counts[g.status] = gap_counts.get(g.status, 0) + 1

        return {
            "ticker": ticker.upper(),
            "cik": cik,
            "company_id": company.id,
            "run_id": run.id,
            "accession_number": accession_number,
            "financial_facts": saved_fin_facts,
            "extracted_spans": saved_spans,
            "financial_facts_count": len(saved_fin_facts),
            "extracted_spans_count": len(saved_spans),
            "gaps_count": len(saved_gaps),
            "gaps_by_status": gap_counts,
            "status": "success" if not saved_gaps else "completed_with_errors",
            "errors": [f"[{g.status}] {g.target}: {g.detail}" for g in saved_gaps],
        }
