"""Master orchestration pipeline."""

from __future__ import annotations

import logging
from tearsheet.edgar.tickers import resolve_ticker_to_cik
from tearsheet.edgar.submissions import get_filing_history
from tearsheet.edgar.filings import locate_filing, download_filing_documents
from tearsheet.edgar.xbrl import fetch_companyfacts
from tearsheet.parse.documents import build_documents
from tearsheet.extract.qualitative import extract_risk_factors, extract_business, extract_management_discussion
from tearsheet.extract.financials import extract_financial_facts
from tearsheet.store.repository import Repository
from tearsheet.store.models import Filing, QualitativeFact, FinancialFact

logger = logging.getLogger(__name__)

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
        errors = []
        
        # Financial Branch
        try:
            logger.info(f"Fetching XBRL companyfacts for CIK {cik}")
            companyfacts = fetch_companyfacts(cik)
            logger.info(f"Extracting financial facts for {ticker}")
            fin_facts = extract_financial_facts(company.id, companyfacts)
            logger.info(f"Saving {len(fin_facts)} financial facts to repository")
            saved_fin_facts = self.repo.save_financial_facts(fin_facts)
        except Exception as e:
            msg = f"Financials extraction failed: {str(e)}"
            logger.error(msg)
            errors.append(msg)
            
        logger.info(f"Downloading documents for {accession_number}")
        raw_html_path = download_filing_documents(cik, accession_number)
        
        logger.info(f"Parsing sections from {raw_html_path}")
        documents = build_documents(filing.id, raw_html_path)
        
        logger.info("Saving document sections to repository")
        saved_docs = self.repo.save_documents(documents)
        
        docs_by_section = {d.section: d for d in saved_docs}
        all_qual_facts = []
        routes = [
            ("1A", extract_risk_factors),
            ("1",  extract_business),
            ("7",  extract_management_discussion)
        ]
        
        for section, extractor in routes:
            doc = docs_by_section.get(section)
            if doc is None:
                msg = f"Section {section} not found for {ticker}"
                logger.warning(msg)
                errors.append(msg)
                continue
            
            logger.info(f"Extracting facts from Item {section} (ID: {doc.id})")
            try:
                facts = extractor(doc)
                all_qual_facts.extend(facts)
            except Exception as e:
                msg = f"{section} extraction failed: {e}"
                logger.error(msg)
                errors.append(msg)
                
        # Global span-deduplication across all categories
        seen_spans = set()
        unique_qual_facts = []
        discarded_uncited = 0
        for fact in all_qual_facts:
            if not fact.citations:
                discarded_uncited += 1
                continue
            cit = fact.citations[0]
            span_key = (cit.document_id, cit.start_offset, cit.end_offset)
            if span_key not in seen_spans:
                seen_spans.add(span_key)
                unique_qual_facts.append(fact)
                
        if discarded_uncited:
            logger.warning(f"Discarded {discarded_uncited} uncited qualitative facts before save")
        
        logger.info(f"Saving {len(unique_qual_facts)} qualitative facts to repository")
        saved_qual_facts = self.repo.save_qualitative_facts(unique_qual_facts)
        
        logger.info(f"Pipeline complete for {ticker}")
        
        return {
            "ticker": ticker.upper(),
            "cik": cik,
            "company_id": company.id,
            "accession_number": accession_number,
            "financial_facts": saved_fin_facts,
            "qualitative_facts": saved_qual_facts,
            "financial_facts_count": len(saved_fin_facts),
            "qualitative_facts_count": len(saved_qual_facts),
            "status": "success" if not errors else "completed_with_errors",
            "errors": errors,
        }
