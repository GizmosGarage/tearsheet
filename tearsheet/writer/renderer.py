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
    for fact in qualitative_facts:
        blocks.append(_render_fact(fact))
    return "\n".join(blocks)
