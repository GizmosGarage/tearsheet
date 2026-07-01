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


def _make_span(category: str, label: str | None, citations=None):
    span = MagicMock()
    span.category = category
    span.label = label
    span.citations = citations or []
    return span


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
        out = render_dossier(_make_company(), None, [], [])
        assert "# NVIDIA Corporation (NVDA)" in out
        assert "## 1. Business in Plain English" in out
        assert "## 2. Competitive Position" in out
        assert "## 3. Financial Shape" in out
        assert "## 4. Risks / Bear Case" in out
        assert "Total spans extracted:" in out

    def test_competitive_position_subsections(self):
        # - [ ] "Competitors" and "Moats / Durable Advantages" under Section 2
        out = render_dossier(_make_company(), None, [], [])
        assert "### Competitors" in out
        assert "### Moats / Durable Advantages" in out

    def test_mda_categories_under_section_3(self):
        # - [ ] liquidity, kpi, forward_looking_sentiment render under Financial Shape
        s = _make_span("liquidity", "Liquidity and Capital Resources")
        s.citations.append(_make_citation(1, "quote", 1, 2))
        out = render_dossier(_make_company(), None, [s], [])
        assert "## 3. Financial Shape" in out
        assert "### Management's Discussion & Analysis" in out
        assert "- **Liquidity and Capital Resources**" in out


class TestCitationFormatting:
    """§3.1 citation mandate."""

    def test_every_claim_followed_by_citation_line(self):
        # - [ ] Label, quote, doc#, offsets, and section appear in output
        span = _make_span("risk_factor", "Risk A")
        cit = _make_citation(99, "quote text", 100, 200, "1A")
        span.citations.append(cit)

        out = render_dossier(_make_company(), None, [span], [])
        assert "- **Risk A**" in out
        assert '> "quote text"' in out
        assert "> — Item 1A · doc#99 · chars 100–200" in out

    def test_unlabelled_span_renders_quote_as_bullet(self):
        span = _make_span("risk_factor", None)
        cit = _make_citation(99, "verbatim only", 5, 18, "1A")
        span.citations.append(cit)

        out = render_dossier(_make_company(), None, [span], [])
        assert '- > "verbatim only"' in out
        assert "> — Item 1A · doc#99 · chars 5–18" in out

    def test_multiple_citations_render_separate_blockquotes(self):
        span = _make_span("risk_factor", "Risk B")
        cit1 = _make_citation(1, "quote 1", 10, 20, "1")
        cit2 = _make_citation(2, "quote 2", 30, 40, "1A")
        span.citations.extend([cit1, cit2])

        out = render_dossier(_make_company(), None, [span], [])
        assert '> "quote 1"' in out
        assert "> — Item 1 · doc#1 · chars 10–20" in out
        assert '> "quote 2"' in out
        assert "> — Item 1A · doc#2 · chars 30–40" in out

    def test_uncited_span_triggers_canary_marker(self):
        # - [ ] Citation-less span → [UNCITED — investigate], label not bare
        span = _make_span("risk_factor", "Risk C")
        # No citations
        out = render_dossier(_make_company(), None, [span], [])
        assert "- **Risk C**" in out
        assert "> [UNCITED — investigate]" in out


class TestFinancialTableFormatting:
    """§3.3 financial table rendering."""

    def test_none_metrics_render_as_em_dash(self):
        # - [ ] None → —, never 0 or blank
        row = FinancialSummaryRow(
            period_end=date(2021, 12, 31),
            revenue=None, revenue_yoy=None, gross_margin=None, operating_margin=None,
            net_margin=None, fcf=None, fcf_margin=None, debt_to_equity=None, roe=None
        )
        out = render_dossier(_make_company(), None, [], [row])
        # all cells should have —, check a few
        assert "| Revenue | — |" in out
        assert "| Gross Margin | — |" in out
        assert "| Free Cash Flow | — |" in out
        assert "| ROE | — |" in out

    def test_percentage_formatting_one_decimal(self):
        row = FinancialSummaryRow(
            period_end=date(2021, 12, 31),
            revenue=1000.0, revenue_yoy=0.155, gross_margin=0.45, operating_margin=0.2,
            net_margin=0.1, fcf=100.0, fcf_margin=0.1, debt_to_equity=1.5, roe=0.123
        )
        out = render_dossier(_make_company(), None, [], [row])
        assert "| Revenue YoY | 15.5% |" in out
        assert "| Gross Margin | 45.0% |" in out
        assert "| Debt-to-Equity | 1.50 |" in out
        assert "| Revenue | 1,000 |" in out

    def test_xbrl_provenance_footnote_present(self):
        # - [ ] Footnote names source concepts and SEC XBRL period
        row = FinancialSummaryRow(
            period_end=date(2021, 12, 31),
            revenue=1000.0, revenue_yoy=0.1, gross_margin=0.4, operating_margin=0.2,
            net_margin=0.1, fcf=100.0, fcf_margin=0.1, debt_to_equity=1.5, roe=0.1
        )
        out = render_dossier(_make_company(), None, [], [row])
        assert "*Source: Extracted from SEC XBRL companyfacts.*" in out
