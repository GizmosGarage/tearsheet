"""Pure Markdown formatting — no DB, no math."""

from __future__ import annotations

from tearsheet.store.models import Company, Filing, QualitativeFact
from tearsheet.writer.metrics import FinancialSummaryRow


def _render_fact(fact: QualitativeFact) -> str:
    lines = [f"- **{fact.summary}**"]
    if not fact.citations:
        lines.append("  > [UNCITED — investigate]")
    else:
        for c in fact.citations:
            section = c.document.section if getattr(c, "document", None) else "?"
            lines.append(f'  > "{c.quote}"')
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

def _render_section_3(facts: list[QualitativeFact], summary: list[FinancialSummaryRow]) -> str:
    mda_cats = ["liquidity", "kpi", "forward_looking_sentiment"]
    mda_facts = [f for f in facts if f.category in mda_cats]
    
    blocks = ["## 3. Financial Shape\n"]
    blocks.append(_render_financial_table(summary))
    
    if mda_facts:
        blocks.append("\n### Management's Discussion & Analysis")
        for f in mda_facts:
            blocks.append(_render_fact(f))
            
    return "\n".join(blocks)

def render_dossier(
    company: Company,
    filing: Filing | None,
    qualitative_facts: list[QualitativeFact],
    financial_summary: list[FinancialSummaryRow],
    *,
    errors: list[str] | None = None,
) -> str:
    """Render a fully-cited Markdown dossier."""
    blocks = []
    
    mda_cats = ["liquidity", "kpi", "forward_looking_sentiment"]
    other_facts = [f for f in qualitative_facts if f.category not in mda_cats]
    
    for fact in other_facts:
        blocks.append(_render_fact(fact))
        
    blocks.append(_render_section_3(qualitative_facts, financial_summary))
    
    return "\n\n".join(blocks)
