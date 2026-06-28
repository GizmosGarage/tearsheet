"""Pure string tests for tearsheet.writer.renderer — no DB."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from tearsheet.writer.metrics import FinancialSummaryRow
from tearsheet.writer.renderer import render_dossier


def _make_company(**kwargs):
    company = MagicMock()
    company.ticker = kwargs.get("ticker", "NVDA")
    company.cik = kwargs.get("cik", "0001045810")
    company.name = kwargs.get("name", "NVIDIA Corporation")
    return company


def _make_qual_fact(category: str, summary: str, citations=None):
    fact = MagicMock()
    fact.category = category
    fact.summary = summary
    fact.citations = citations or []
    return fact


def _make_citation(document_id: int, quote: str, start: int, end: int, section: str = "7"):
    citation = MagicMock()
    citation.document_id = document_id
    citation.quote = quote
    citation.start_offset = start
    citation.end_offset = end
    citation.document = MagicMock()
    citation.document.section = section
    return citation


class TestRenderDossierSections:
    """Section layout and headers."""

    def test_section_headers_present(self):
        # - [ ] Header, Sections 1–4, footer
        pass

    def test_competitive_position_subsections(self):
        # - [ ] "Competitors" and "Moats / Durable Advantages" under Section 2
        pass

    def test_mda_categories_under_section_3(self):
        # - [ ] liquidity, kpi, forward_looking_sentiment render under Financial Shape
        pass


class TestCitationFormatting:
    """§3.1 citation mandate."""

    def test_every_claim_followed_by_citation_line(self):
        # - [ ] Quote, doc#, offsets, and section appear in output
        fact = _make_qual_fact("risk_factor", "Risk A")
        cit = _make_citation(99, "quote text", 100, 200, "1A")
        fact.citations.append(cit)
        
        out = render_dossier(_make_company(), None, [fact], [])
        assert "- **Risk A**" in out
        assert '> "quote text"' in out
        assert "> — Item 1A · doc#99 · chars 100–200" in out

    def test_multiple_citations_render_separate_blockquotes(self):
        fact = _make_qual_fact("risk_factor", "Risk B")
        cit1 = _make_citation(1, "quote 1", 10, 20, "1")
        cit2 = _make_citation(2, "quote 2", 30, 40, "1A")
        fact.citations.extend([cit1, cit2])
        
        out = render_dossier(_make_company(), None, [fact], [])
        assert '> "quote 1"' in out
        assert "> — Item 1 · doc#1 · chars 10–20" in out
        assert '> "quote 2"' in out
        assert "> — Item 1A · doc#2 · chars 30–40" in out

    def test_uncited_fact_triggers_canary_marker(self):
        # - [ ] Citation-less fact → [UNCITED — investigate], summary not bare
        fact = _make_qual_fact("risk_factor", "Risk C")
        # No citations
        out = render_dossier(_make_company(), None, [fact], [])
        assert "- **Risk C**" in out
        assert "> [UNCITED — investigate]" in out


class TestFinancialTableFormatting:
    """§3.3 financial table rendering."""

    def test_none_metrics_render_as_em_dash(self):
        # - [ ] None → —, never 0 or blank
        pass

    def test_percentage_formatting_one_decimal(self):
        pass

    def test_xbrl_provenance_footnote_present(self):
        # - [ ] Footnote names source concepts and SEC XBRL period
        pass
