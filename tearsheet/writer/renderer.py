"""Pure Markdown formatting — no DB, no math, no authored prose.

Every rendered string is either a verbatim source slice (labels, quotes) or
fixed structural scaffolding (section headers, provenance lines).
"""

from __future__ import annotations

from tearsheet.store.models import Company, ExtractedSpan, Filing
from tearsheet.writer.metrics import FinancialSummaryRow


def _render_span(span: ExtractedSpan) -> str:
    if span.label:
        lines = [f"- **{span.label}**"]
        quote_prefix = "  > "
    else:
        lines = []
        quote_prefix = "- > "

    if not span.citations:
        lines.append(f"{quote_prefix}[UNCITED — investigate]")
    else:
        for i, c in enumerate(span.citations):
            section = c.document.section if getattr(c, "document", None) else "?"
            prefix = quote_prefix if i == 0 and not span.label else "  > "
            lines.append(f'{prefix}"{c.quote}"')
            lines.append(f"  > — Item {section} · doc#{c.document_id} · chars {c.start_offset}–{c.end_offset}")
    return "\n".join(lines)

def _render_financial_table(summary: list[FinancialSummaryRow]) -> str:
    if not summary:
        return "*No financial data available.*"
        
    def fmt_pct(val):
        return f"{val * 100:.1f}%" if val is not None else "—"
        
    def fmt_curr(val):
        if val is None:
            return "—"
        return f"{val:,.0f}"
        
    def fmt_ratio(val):
        return f"{val:.2f}" if val is not None else "—"
        
    years = [str(r.period_end.year) for r in summary]
    
    header = "| Metric | " + " | ".join(years) + " |"
    separator = "|---|" + "|".join(["---" for _ in years]) + "|"
    
    rows = [header, separator]
    
    metrics = [
        ("Revenue", lambda r: fmt_curr(r.revenue)),
        ("Revenue YoY", lambda r: fmt_pct(r.revenue_yoy)),
        ("Gross Margin", lambda r: fmt_pct(r.gross_margin)),
        ("Operating Margin", lambda r: fmt_pct(r.operating_margin)),
        ("Net Margin", lambda r: fmt_pct(r.net_margin)),
        ("Free Cash Flow", lambda r: fmt_curr(r.fcf)),
        ("FCF Margin", lambda r: fmt_pct(r.fcf_margin)),
        ("Debt-to-Equity", lambda r: fmt_ratio(r.debt_to_equity)),
        ("ROE", lambda r: fmt_pct(r.roe))
    ]
    
    for name, extractor in metrics:
        values = [extractor(r) for r in summary]
        rows.append(f"| {name} | " + " | ".join(values) + " |")
        
    footnote = "*Source: Extracted from SEC XBRL companyfacts.*"
    return "\n".join(rows) + "\n\n" + footnote

def _render_section_3(spans: list[ExtractedSpan], summary: list[FinancialSummaryRow]) -> str:
    mda_cats = ["liquidity", "kpi", "forward_looking_sentiment"]
    mda_spans = [s for s in spans if s.category in mda_cats]

    blocks = ["## 3. Financial Shape\n"]
    blocks.append(_render_financial_table(summary))

    if mda_spans:
        blocks.append("\n### Management's Discussion & Analysis")
        for s in mda_spans:
            blocks.append(_render_span(s))

    return "\n".join(blocks)

def render_dossier(
    company: Company,
    filing: Filing | None,
    extracted_spans: list[ExtractedSpan],
    financial_summary: list[FinancialSummaryRow],
    *,
    errors: list[str] | None = None,
) -> str:
    """Render a fully-cited Markdown dossier of verbatim spans."""
    spans_by_cat = {}
    for span in extracted_spans:
        spans_by_cat.setdefault(span.category, []).append(span)

    blocks = []

    # Header
    filing_str = f" (Latest filing: {filing.filed_date} | {filing.accession_number})" if filing else ""
    blocks.append(f"# {company.name} ({company.ticker}){filing_str}\n")
    blocks.append(f"CIK: {company.cik}\n")

    # Section 1
    blocks.append("## 1. Business in Plain English")
    for s in spans_by_cat.get("revenue_stream", []):
        blocks.append(_render_span(s))

    # Section 2
    blocks.append("\n## 2. Competitive Position")
    blocks.append("### Competitors")
    for s in spans_by_cat.get("competitor", []):
        blocks.append(_render_span(s))
    blocks.append("\n### Moats / Durable Advantages")
    for s in spans_by_cat.get("competitive_moat", []):
        blocks.append(_render_span(s))

    # Section 3
    blocks.append("\n" + _render_section_3(extracted_spans, financial_summary))

    # Section 4
    blocks.append("\n## 4. Risks / Bear Case")
    for s in spans_by_cat.get("risk_factor", []):
        blocks.append(_render_span(s))

    # Footer
    blocks.append("\n---\n")
    blocks.append(f"**Total spans extracted:** {len(extracted_spans)}")
    if errors:
        blocks.append("\n**Pipeline Errors:**")
        for e in errors:
            blocks.append(f"- {e}")

    return "\n".join(blocks)
