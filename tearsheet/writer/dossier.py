"""Orchestrator to build the dossier from stored data."""

from __future__ import annotations

from tearsheet.store.repository import Repository
from tearsheet.writer.metrics import build_financial_summary
from tearsheet.writer.renderer import render_dossier

def build_dossier(ticker: str) -> str | None:
    repo = Repository()
    company = repo.get_company_by_ticker(ticker)
    if not company:
        return None
        
    filing = repo.get_latest_filing(company.id)
    qualitative_facts = repo.get_qualitative_facts(company.id)
    
    series_by_concept = {}
    for concept in [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "GrossProfit",
        "OperatingIncomeLoss",
        "NetIncomeLoss",
        "Assets",
        "Liabilities",
        "StockholdersEquity",
        "CashAndCashEquivalentsAtCarryingValue",
        "NetCashProvidedByUsedInOperatingActivities",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "LongTermDebtNoncurrent",
    ]:
        series_by_concept[concept] = repo.get_financial_series(company.id, concept)
        
    financial_summary = build_financial_summary(series_by_concept)
    
    return render_dossier(company, filing, qualitative_facts, financial_summary)
