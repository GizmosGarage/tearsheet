# Tearsheet — Writer Layer Specification (Deterministic Dossier Renderer)

**Status:** Approved-for-scaffolding blueprint. No core code written.
**Goal:** Render a trustworthy, fully-cited Markdown dossier (Sections 1–4 + derived financials) from the existing grounded store — **deterministically, no LLM**. This validates the analysis machine and adds zero hallucination risk. LLM synthesis (the top sheet / bull-bear) is an explicit follow-on, not in scope here.

**Design philosophy:** The writer is a pure *consumer* of `repository.py`. It never re-reads filings, never calls an LLM, and can only render what the extractor already grounded. Three layers, cleanly separated so DB/math is testable apart from formatting:

```
repository.py (reads)  →  writer/metrics.py (pure math)  →  writer/renderer.py (pure formatting)
                                         ↘  writer/dossier.py (orchestration glue)  ↗
                                                         ↓
                                              cli.py  render <TICKER>
```

---

## 0. Current State (what the writer builds on)

- **Read surface is nearly empty.** `repository.py` exposes only `get_company_by_ticker`; everything else is upsert/write. The writer needs new, read-only query methods (§1).
- **Available render data** (models, [store/models.py](../tearsheet/store/models.py)):
  - `Company(id, ticker, cik, name)`
  - `FinancialFact(company_id, concept, label, unit, period_end, value)` — **no `source` column**; provenance is the `concept` tag + `period_end`.
  - `QualitativeFact(company_id, category, summary)` + `citations`
  - `Citation(document_id, quote, start_offset, end_offset)`
- **The seven categories** (the writer's query vocabulary): `risk_factor`, `revenue_stream`, `competitor`, `competitive_moat`, `liquidity`, `kpi`, `forward_looking_sentiment`.
- **Sentinel trap awareness:** missing-date financial facts are persisted with `period_end = 1970-01-01`. The metrics layer **must exclude** the sentinel epoch from all trajectory math (§2.4) — it is not a real fiscal period.

---

## 1. Read-Surface API (`repository.py` additions)

All methods are read-only, reuse the existing `_session_ctx`, and **eager-load** relationships needed outside the session (mirroring the deep `selectinload` already used in `save_qualitative_facts`) to avoid `DetachedInstanceError` in the renderer.

```python
# --- already exists ---
def get_company_by_ticker(self, ticker: str) -> Company | None: ...

# --- new: qualitative ---
def get_qualitative_facts(
    self, company_id: int, category: str | None = None
) -> list[QualitativeFact]:
    """All qualitative facts for a company, optionally filtered to one category.
    Eager-loads citations -> document so the renderer can show spans + section."""
    # selectinload(QualitativeFact.citations).selectinload(Citation.document)
    # order_by(QualitativeFact.category, QualitativeFact.id)

# --- new: financial ---
def get_financial_facts(
    self, company_id: int, concept: str | None = None
) -> list[FinancialFact]:
    """Raw financial facts, optionally for one concept, ordered by period_end ASC."""

def get_financial_series(
    self, company_id: int, concept: str
) -> list[tuple[date, float]]:
    """Convenience: (period_end, value) points for one concept, sorted ASC,
    EXCLUDING the 1970-01-01 sentinel and any NULL value. The metrics layer's
    primary input."""

# --- new: header metadata (optional but recommended) ---
def get_latest_filing(self, company_id: int) -> Filing | None:
    """Most recent filing (by filed_date, then id) for dossier header provenance."""
```

**Contract notes:**
- `get_financial_series` is the workhorse for §2 — it centralizes sentinel/NULL exclusion in one place so the math layer never re-implements it.
- These methods return persisted, eager-loaded ORM objects; the writer treats them as read-only DTOs.

---

## 2. Derived Financial Metrics Layer (`tearsheet/writer/metrics.py`)

**Pure functions only — no DB, no I/O, no formatting.** Input: raw series (lists of `(date, float)`). Output: structured numeric results. This is the most unit-testable module in the project and should be tested exhaustively with hand-built series.

### 2.1 Canonical concept resolution (the revenue drift gotcha)
Revenue is tagged inconsistently across filers. The layer resolves a canonical series by **priority order**, taking the first concept that yields data:

```python
REVENUE_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
]
# helper: resolve_series(repo_series_by_concept, REVENUE_CONCEPTS) -> first non-empty
```

Other concepts are stable single tags (from the financials whitelist): `GrossProfit`, `OperatingIncomeLoss`, `NetIncomeLoss`, `Assets`, `Liabilities`, `StockholdersEquity`, `CashAndCashEquivalentsAtCarryingValue`, `NetCashProvidedByUsedInOperatingActivities`, `PaymentsToAcquirePropertyPlantAndEquipment` (capex), `LongTermDebtNoncurrent`.

### 2.2 Period alignment (the correctness keystone)
Every ratio combines two concepts and **must align them on identical `period_end`**. Build a date→value map per concept and only compute a metric for periods present in *both*. Never assume positional alignment between two series.

```python
def align_by_period(*series: list[tuple[date, float]]) -> list[tuple[date, tuple[float, ...]]]:
    """Inner-join multiple series on period_end; only dates present in ALL series survive."""
```

### 2.3 Metric functions (deterministic, guard every edge)
Per fiscal year, produce a `FinancialSummaryRow` (a frozen dataclass), each field `Optional[float]` — `None` when inputs are missing or a denominator is zero/None. **No function may raise on missing data.**

| Metric | Formula | Inputs |
|---|---|---|
| Revenue YoY growth | `(rev_t - rev_{t-1}) / rev_{t-1}` | revenue series (consecutive periods) |
| Gross margin | `GrossProfit / Revenue` | aligned |
| Operating margin | `OperatingIncomeLoss / Revenue` | aligned |
| Net margin | `NetIncomeLoss / Revenue` | aligned |
| Free cash flow (FCF) | `OperatingCashFlow - Capex` | aligned; see sign note |
| FCF margin | `FCF / Revenue` | aligned |
| Debt-to-equity | `LongTermDebtNoncurrent / StockholdersEquity` | aligned |
| Return on equity (ROE) | `NetIncomeLoss / StockholdersEquity` | aligned |

```python
@dataclass(frozen=True)
class FinancialSummaryRow:
    period_end: date
    revenue: float | None
    revenue_yoy: float | None
    gross_margin: float | None
    operating_margin: float | None
    net_margin: float | None
    fcf: float | None
    fcf_margin: float | None
    debt_to_equity: float | None
    roe: float | None

def build_financial_summary(
    series_by_concept: dict[str, list[tuple[date, float]]]
) -> list[FinancialSummaryRow]:
    """Deterministic trajectory table, one row per fiscal year, sorted ASC."""
```

### 2.4 Hard rules (flag for the builder)
- **Exclude the 1970-01-01 sentinel** and NULL values — enforced upstream in `get_financial_series`, re-asserted defensively here.
- **Division guards:** denominator `None` or `0` → metric `None`, never `ZeroDivisionError`.
- **Sign convention:** XBRL reports `PaymentsToAcquirePropertyPlantAndEquipment` as a positive outflow magnitude → `FCF = OCF - capex`. Document this assumption inline; it is the one place a sign error silently corrupts a number.
- **No annualization / no quarter mixing:** inputs are already 10-K annual facts; the layer assumes annual periods and does not interpolate.

---

## 3. The Markdown Renderer (`tearsheet/writer/renderer.py`)

**Pure formatting — takes structured data, returns a Markdown string. No DB, no math.** It receives the company, the qualitative facts (already grouped by category), and the `FinancialSummaryRow` list, and emits the dossier.

### 3.1 The non-negotiable citation mandate
**Every qualitative claim renders alongside its full citation provenance.** A claim with no citation is a bug, not a render — the renderer must surface it as a visible `[UNCITED — investigate]` marker rather than printing the summary bare (this should never happen given "no span, no claim," so it doubles as a data-integrity canary).

Per-claim block format:

```markdown
- **<summary>**
  > "<citation.quote>"
  > — Item <document.section> · doc#<citation.document_id> · chars <start_offset>–<end_offset>
```

The citation line carries all four mandated fields: document ID, start offset, end offset, and the extracted quote. When a fact has multiple citations, render each as its own blockquote line.

### 3.2 Section → category layout

| Dossier section | Source | Notes |
|---|---|---|
| **Header** | `Company` + `get_latest_filing` | Name, ticker, CIK, latest accession/filed date. Provenance line. |
| **1. Business in Plain English** | `revenue_stream` | What the company sells / how money flows. |
| **2. Competitive Position** | `competitor`, `competitive_moat` | Two subsections: "Competitors", "Moats / Durable Advantages". |
| **3. Financial Shape** | `FinancialSummaryRow[]` **+** `liquidity`, `kpi`, `forward_looking_sentiment` | Derived-metrics table first, then cited MD&A narrative subsections. |
| **4. Risks / Bear Case** | `risk_factor` | The grounded red-flag list. |
| **Footer** | counts | Fact counts per section + any `errors` carried from the pipeline run. |

**Design decision (flag §6):** MD&A's three categories don't belong to Sections 1–4 cleanly, but they're in the store and shouldn't be stranded. They render as *cited narrative* under Section 3 (Financial Shape) — numbers from XBRL, context from management. This consumes all seven categories.

### 3.3 Financial table rendering
- Render `FinancialSummaryRow[]` as a Markdown table, columns = fiscal years (period_end), rows = metrics.
- Format: currency in millions/billions with thousands separators; margins/growth as percentages to 1 decimal; `None` → `—` (em dash), never `0` or blank.
- **Provenance for financials** (no `Citation` objects exist for XBRL): a footnote naming the source concepts and that values are SEC XBRL companyfacts for the stated `period_end`. This keeps the "everything is traceable" promise even though financials use tag-provenance, not span-provenance.

### 3.4 Output
`render_dossier(...) -> str`. Pure string out; the caller (dossier orchestrator / CLI) decides where it goes (stdout and/or `data/dossiers/<TICKER>.md`).

---

## 4. Orchestration & Pipeline Integration

### 4.1 Orchestrator (`tearsheet/writer/dossier.py`)
The glue that wires reads → math → formatting. The only writer module that touches the repository:

```python
def build_dossier(ticker: str, repo: Repository | None = None) -> str:
    repo = repo or Repository()
    company = repo.get_company_by_ticker(ticker.upper())
    if company is None:
        raise ValueError(f"No data for {ticker}. Run `tearsheet run {ticker}` first.")
    qual = repo.get_qualitative_facts(company.id)          # grouped by category in renderer
    series = {c: repo.get_financial_series(company.id, c) for c in NEEDED_CONCEPTS}
    summary = build_financial_summary(series)              # metrics.py
    filing = repo.get_latest_filing(company.id)
    return render_dossier(company, filing, qual, summary)  # renderer.py
```

### 4.2 CLI command (primary integration)
A **standalone, read-only** `render` subcommand — decoupled from extraction so a dossier can be regenerated from the DB with zero network calls:

```
python -m tearsheet.cli render NVDA            # prints to stdout
python -m tearsheet.cli render NVDA --out FILE # also writes data/dossiers/NVDA.md
```

Add to the existing `argparse` subparser block in [cli.py](../tearsheet/cli.py): a `render` parser with a `ticker` arg and optional `--out`. It calls `build_dossier(ticker)` and prints / writes the result. Errors (no data for ticker) exit non-zero with a helpful "run extraction first" message.

### 4.3 Optional chained flag on `run` (secondary, deferred-friendly)
Optionally add `--render` to the existing `run` command so `tearsheet run NVDA --render` extracts *then* renders in one shot. Keep this thin — it just calls `build_dossier` after `run_for_ticker` returns. **Recommendation: ship the standalone `render` command first; the chained flag is a convenience, not a dependency.** Keeping render decoupled means the renderer is always testable against a fixture DB without touching the pipeline.

---

## 5. Execution Task List (builder agent)

> Reuse the store, models, and grounding unchanged. The writer adds read methods + a new `tearsheet/writer/` package + a CLI command. **Split DB/math from formatting** — they are tested separately.

### Part A — DB / Math logic (no formatting)
**A1. Read surface — `store/repository.py`**
- [ ] `get_qualitative_facts(company_id, category=None)` — eager-load `citations -> document`; ordered.
- [ ] `get_financial_facts(company_id, concept=None)` — ordered by `period_end` ASC.
- [ ] `get_financial_series(company_id, concept)` — `(date, value)` sorted ASC, **excluding** the `1970-01-01` sentinel and NULL values.
- [ ] `get_latest_filing(company_id)` — newest filing for header provenance.
- [ ] Tests in `tests/store/test_repository.py`: seed a company with multi-year facts incl. a sentinel row + a NULL value; assert series excludes both, ordering correct, category filter works, eager-load survives outside session.

**A2. Metrics — `tearsheet/writer/metrics.py`**
- [ ] `REVENUE_CONCEPTS` priority list + `resolve_series` helper.
- [ ] `align_by_period(*series)` inner-join on `period_end`.
- [ ] `build_financial_summary(series_by_concept) -> list[FinancialSummaryRow]` implementing the §2.3 metrics with §2.4 guards (no raise on missing/zero, sentinel excluded, capex sign documented).
- [ ] Tests in `tests/writer/test_metrics.py` (pure, no DB): YoY across consecutive years; margins align on shared periods only; FCF sign; every metric returns `None` (not error) on missing denominator / zero / single-year series.

### Part B — Formatting logic (no DB/math)
**B1. Renderer — `tearsheet/writer/renderer.py`**
- [ ] `render_dossier(company, filing, qualitative_facts, financial_summary) -> str`.
- [ ] Group qualitative facts by category; enforce the §3.1 citation block on every claim; emit `[UNCITED — investigate]` for any citation-less fact.
- [ ] Section 1–4 layout per §3.2, MD&A narrative under Section 3, financial table per §3.3 (`None → —`, % formatting, XBRL provenance footnote).
- [ ] Tests in `tests/writer/test_renderer.py` (pure strings, hand-built inputs): assert every qualitative claim line is followed by a citation line containing doc#, offsets, and quote; assert `None` metrics render as `—`; assert a citation-less fact triggers the canary marker.

### Part C — Orchestration & CLI
**C1. Orchestrator — `tearsheet/writer/dossier.py`**
- [ ] `build_dossier(ticker, repo=None)` wiring reads → metrics → renderer; clear error when the ticker has no stored data.
- [ ] Test with an in-memory DB seeded end-to-end (no network, no LLM): assert a non-empty dossier string with all expected section headers.

**C2. CLI — `cli.py`**
- [ ] Add `render` subparser (`ticker`, optional `--out`); print to stdout, optionally write `data/dossiers/<TICKER>.md`.
- [ ] (Optional) `--render` flag on `run`.
- [ ] Test in `tests/test_cli.py`: `render` on a seeded DB prints a dossier; `render` on an unknown ticker exits non-zero with the "run extraction first" hint.

- [ ] Full suite green, zero network calls.

---

## 6. Decisions & Flags
- **Deterministic-only** — no LLM in the writer. The synthesis layer (top sheet, drafted bull/bear) is a clean follow-on that reads the same store; this spec deliberately stops short of it.
- **Three-layer split (reads / math / formatting)** keeps `metrics.py` a pure, exhaustively-testable unit and lets the renderer be verified on hand-built inputs with no DB.
- **MD&A categories render under Section 3** so the `liquidity`/`kpi`/`forward_looking_sentiment` feedstock isn't stranded while staying within the "Sections 1–4 + financials" scope. Confirm this placement.
- **Two provenance models coexist** — qualitative facts cite span offsets (§3.1); financials cite concept-tag + period (§3.3). Both are surfaced; neither is rendered bare.
- **`render` is standalone and read-only** — decoupled from extraction by design, so dossiers regenerate from the DB offline and the renderer is always testable against a fixture DB.
- **Known data gaps surfaced by this build** (expected, not blockers): no current-ratio (current assets/liabilities not in the financials whitelist); Section 5 (management/capital allocation) and Section 6 (valuation) still need new data sources (proxy/Form 4, price/multiples) — out of scope here, but the renderer's section skeleton should leave obvious room for them.
