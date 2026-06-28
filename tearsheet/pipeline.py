"""Master orchestration pipeline."""

from __future__ import annotations

import logging
from tearsheet.edgar.tickers import resolve_ticker_to_cik
from tearsheet.edgar.submissions import get_filing_history
from tearsheet.edgar.filings import locate_filing, download_filing_documents
from tearsheet.parse.documents import build_documents
from tearsheet.extract.qualitative import extract_risk_factors
from tearsheet.store.repository import Repository
from tearsheet.store.models import Filing, QualitativeFact

logger = logging.getLogger(__name__)

class ExecutionPipeline:
    def __init__(self, repo: Repository | None = None):
        self.repo = repo or Repository()
        
    def run_for_ticker(self, ticker: str) -> list[QualitativeFact]:
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
        
        logger.info(f"Downloading documents for {accession_number}")
        raw_html_path = download_filing_documents(cik, accession_number)
        
        logger.info(f"Parsing sections from {raw_html_path}")
        documents = build_documents(filing.id, raw_html_path)
        
        logger.info("Saving document sections to repository")
        saved_docs = self.repo.save_documents(documents)
        
        # Find 1A
        doc_1a = None
        for d in saved_docs:
            if d.section == "1A":
                doc_1a = d
                break
                
        if not doc_1a:
            raise ValueError(f"Could not find Item 1A in the parsed documents for {ticker}")
            
        logger.info(f"Extracting risk factors from Item 1A (ID: {doc_1a.id})")
        facts = extract_risk_factors(doc_1a)
        
        logger.info(f"Saving {len(facts)} qualitative facts to repository")
        saved_facts = self.repo.save_qualitative_facts(facts)
        
        logger.info(f"Pipeline complete for {ticker}")
        return saved_facts
