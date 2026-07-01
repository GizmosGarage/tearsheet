# Dossier Hotfixes — Bug-Fix Specification

**Status:** Ready for implementation
**Author:** Architect
**Scope:** Two data-hygiene defects exposed by the deterministic renderer on the first NVDA dossier.
**Blast radius:** `tearsheet/pipeline.py`, `tearsheet/writer/metrics.py` (+ targeted tests). No schema migration. No renderer changes.

---

## 0. Context the builder needs before touching code

The deterministic Writer Layer is doing its job: it is *surfacing* upstream defects rather than hiding them. Two symptoms appeared in the rendered NVDA dossier:

1. **`[UNCITED — investigate]` canaries** — emitted by `renderer._render_fact()` ([renderer.py:11-12](../tearsheet/writer/renderer.py)) whenever a persisted `QualitativeFact` has an empty `citations` list. A fact with no span should never have reached the database.
2. **Column bloat in the financial table** — `renderer._render_financial_table()` ([renderer.py:35](../tearsheet/writer/renderer.py)) builds one column per `FinancialSummaryRow.period_end.year`. `build_financial_summary` is emitting *multiple rows that share a year* (e.g. four "2009" columns), each mostly `—`, because the math layer keys on exact `period_end` dates.

Neither symptom is a renderer bug. Both fixes live strictly **upstream of rendering**.

> **Verification rule for the builder:** Do not write the core code until you have read the two target files end-to-end. The diff sketches below are *illustrative guidance for intent and shape* — match the surrounding style, do not paste them verbatim without reconciling against the current source.

---

## Bug 1 — The Grounding Leak (Pipeline)

### 1.1 Symptom
Rendered dossier contains `[UNCITED — investigate]` under one or more fact bullets.

### 1.2 Root-cause analysis (what the Architect actually found)

There are **two** distinct ways an uncited `QualitativeFact` can land in the DB. The directive's "No span, no save" rule must be enforced at **both** the producer (pipeline) and the persistence boundary (repository):

**(A) Producer assumption — `tearsheet/pipeline.py:96-108`.**
The global span-dedup loop assumes every fact carries exactly one citation:
```python
cit = fact.citations[0]   # line 102 — IndexError / silent leak if citations == []
```
Today the extractors only ever build facts from `accepted` spans, so each has one citation — but this invariant is **implicit and unguarded**. Any future extractor path, or a partially-constructed fact, leaks straight through to `save_qualitative_facts`. The directive requires this be made explicit: *a fact that exits the dedup phase with empty citations must be discarded.*

**(B) Persistence drop — `tearsheet/store/repository.py:224-277` (`save_qualitative_facts`).**
This is the mechanism most likely responsible for the **observed NVDA canary**. The `Citation` table has a **global** uniqueness constraint on `(document_id, start_offset, end_offset)` ([models.py:91](../tearsheet/store/models.py)). The save loop:
- Upserts the `QualitativeFact` with `on_conflict_do_nothing`, then re-selects its id and appends it to `saved_facts` **unconditionally** (lines 246-256).
- Inserts each `Citation` with `on_conflict_do_nothing` on the span (lines 265-268).

On a **re-run** (or when the LLM returns the same span under a slightly different summary), the parent fact is treated as new (`(company_id, category, summary)` differs) but its citation span collides with a pre-existing citation row → the citation insert is **silently skipped** → the fact is surfaced by `get_qualitative_facts` with **zero citations** → canary.

### 1.3 Required fix

Enforce **"No span, no save"** at two layers.

#### Fix 1A — Pipeline guard (primary, matches directive)
File: `tearsheet/pipeline.py`, the dedup block at lines **96-108**.

- Guard the `citations[0]` access so a fact with empty citations is **skipped, not crashed**.
- Produce a `cited_facts` list that contains only facts with ≥1 citation, and pass *that* to `save_qualitative_facts`.

Illustrative shape:
```python
# Global span-deduplication + strict "no span, no save" gate
seen_spans = set()
unique_qual_facts = []
discarded_uncited = 0
for fact in all_qual_facts:
    if not fact.citations:                 # NEW: discard before DB insertion
        discarded_uncited += 1
        continue
    cit = fact.citations[0]
    span_key = (cit.document_id, cit.start_offset, cit.end_offset)
    if span_key not in seen_spans:
        seen_spans.add(span_key)
        unique_qual_facts.append(fact)

if discarded_uncited:
    logger.warning(f"Discarded {discarded_uncited} uncited qualitative facts before save")
```
Keep passing `unique_qual_facts` to `self.repo.save_qualitative_facts(...)` unchanged.

#### Fix 1B — Repository transactional consistency (closes the re-run leak)
File: `tearsheet/store/repository.py`, `save_qualitative_facts` (lines **224-277**).

The rule: **a `QualitativeFact` may only be surfaced if it ends the save with at least one attached citation row.** Two changes:

1. **Defensive skip** at the top of the per-fact loop: `if not f.citations: continue`.
2. **Do not surface citation-less parents.** Only append the fact id to `saved_facts` once at least one of its citations was actually persisted *or already exists for this fact*. Concretely: capture the result of each `Citation` insert (use `.returning(Citation.id)`), and additionally treat a span that already belongs to **this same** `qualitative_fact_id` as "attached." If, after attempting all citations, the fact has **no** citation row pointing at it, **omit it from `saved_facts`** (it will not be returned, and on the next read it will not surface a bare canary).

Illustrative shape for the inner logic (reconcile against current code):
```python
if f_id:
    attached = False
    for c in f.citations:
        c_stmt = insert(Citation).values(
            qualitative_fact_id=f_id,
            document_id=c.document_id, quote=c.quote,
            start_offset=c.start_offset, end_offset=c.end_offset,
        ).on_conflict_do_nothing(
            index_elements=["document_id", "start_offset", "end_offset"]
        ).returning(Citation.id)
        inserted_id = session.scalar(c_stmt)
        if inserted_id is not None:
            attached = True
    if not attached:
        # Span collided with a citation owned by a DIFFERENT fact, or no spans.
        # Verify whether THIS fact already owns a citation row before giving up:
        existing = session.scalar(
            select(Citation.id).where(Citation.qualitative_fact_id == f_id).limit(1)
        )
        attached = existing is not None
    if attached:
        saved_facts.append(f_id)
```

> **Architect's note on the residual:** the deeper cause of (B) is that `Citation` uniqueness is **global on span** rather than scoped to `(qualitative_fact_id, document_id, start_offset, end_offset)`. Scoping it would let two distinct facts legitimately cite the same span. That is a **schema migration and out of scope for this hotfix** — log it as a follow-up. For the immediate NVDA regeneration, see the execution checklist step to rebuild qualitative facts from a clean slate so no stale spans block new citations.

### 1.4 Acceptance criteria (Bug 1)
- A `QualitativeFact` with empty `citations` is **never** inserted (pipeline) and **never** surfaced (repository).
- Re-running the pipeline for an already-populated company produces **zero** `[UNCITED — investigate]` canaries in the rendered dossier.
- Existing pipeline tests (`tests/test_pipeline.py`) still pass unchanged (both still assert `len(citations) == 1` per fact).

---

## Bug 2 — XBRL Period Bloat (Metrics Layer)

### 2.1 Symptom
The financial table renders dozens of columns — multiple per calendar year (e.g. four "2009", five "2010") — mostly filled with `—`.

### 2.2 Root-cause analysis
`tearsheet/writer/metrics.py` keys **everything** on the exact `period_end` `date`:
- `align_by_period` ([metrics.py:57-78](../tearsheet/writer/metrics.py)) inner-joins series on the exact `date` object.
- `build_financial_summary` ([metrics.py:107-124](../tearsheet/writer/metrics.py)) builds `all_dates` as the **union of every distinct `period_end`** across all concepts, then emits one row per distinct date.

NVDA's fiscal year ends on a **floating last-Sunday-of-January** (e.g. `2009-01-25` vs `2010-01-31`), and XBRL **restatements** persist multiple `period_end` values that fall in the **same fiscal year** (e.g. `2009-01-25` and `2009-01-26`). Because:
1. the `all_dates` union treats each distinct date as its own row → horizontal bloat, and
2. the inner-join in `align_by_period` rarely finds a date shared across *all* concepts (each concept restated to a slightly different day) → most cells resolve to `—`,

the table explodes into many near-empty columns.

### 2.3 Required fix — re-key the math on **Fiscal Year**, not exact date

The decisive fix must move the **join key** from `date` to **fiscal year (an `int`)**. Collapsing each series to one-point-per-year is *necessary but not sufficient*: two concepts in the same FY can still carry different representative dates, so the join itself must be year-based.

**Fiscal-year definition (deterministic, no schema change):** `fiscal_year(d) := d.year`. For January-ending fiscals (NVDA) and December-ending fiscals this equals the conventional FY label; for any FYE it is internally consistent and collision-free. Document this as the chosen convention.

**Within-year resolution rule:** when a concept has multiple values in the same fiscal year, **keep the value at the latest `period_end`** (`max(date)` within the year). This is deterministic and requires no `filed_date` threading.

> The directive permits "latest `filed_date`" as an alternative. `get_financial_series` currently drops `filed_date` from its `(date, value)` tuples, so a true latest-filed resolution would require threading `filed_date` through the read surface. **Out of scope for this hotfix** — note it as a follow-up; use latest-`period_end` now.

#### Implement entirely inside `tearsheet/writer/metrics.py`
Keeping this in the math layer (not the repository read surface) minimizes blast radius — `get_financial_series` and `dossier.py` stay untouched.

**Step 1 — Add a collapse helper.**
```python
def collapse_series_by_fiscal_year(
    series: list[tuple[date, float]],
) -> dict[int, tuple[date, float]]:
    """One representative (period_end, value) per fiscal year (latest period_end wins)."""
    by_year: dict[int, tuple[date, float]] = {}
    for d, v in series:
        if d.year not in by_year or d > by_year[d.year][0]:
            by_year[d.year] = (d, v)
    return by_year
```

**Step 2 — Add a year-keyed join** (new function; **leave `align_by_period` in place** so existing tests and ratio call-sites that rely on date semantics are not silently broken — migrate call-sites deliberately).
```python
def align_by_fiscal_year(
    *series: list[tuple[date, float]],
) -> list[tuple[date, tuple[float, ...]]]:
    """Inner-join multiple series on fiscal year. Representative date = max period_end
    among the joined series for that year. Only years present in ALL series survive."""
    if not series:
        return []
    collapsed = [collapse_series_by_fiscal_year(s) for s in series]
    common_years = set(collapsed[0])
    for c in collapsed[1:]:
        common_years &= set(c)
    result = []
    for y in sorted(common_years):
        rep_date = max(c[y][0] for c in collapsed)
        result.append((rep_date, tuple(c[y][1] for c in collapsed)))
    return result
```

**Step 3 — Rewrite `build_financial_summary` to be year-keyed** (lines **81-148**):
- Replace every `align_by_period(...)` call used for ratio computation with `align_by_fiscal_year(...)`.
- Replace the `all_dates` union (lines 107-109) with an **`all_years`** set built from `{d.year for d, _ in series}` across every concept.
- Collapse the revenue series with `collapse_series_by_fiscal_year` → build a `rev_by_year: dict[int, (date, value)]` so each year yields exactly one revenue point and one representative date.
- Iterate `sorted(all_years)`; for each year set `FinancialSummaryRow.period_end` to that year's **representative date** (the max `period_end` seen for that year across concepts — pick a single deterministic source, e.g. the revenue rep-date, falling back to the max across all concepts when revenue is absent).
- Re-key the ratio lookup dicts (`gross_margin_data`, etc.) by **year** instead of `date`, since `align_by_fiscal_year` returns representative dates that won't equal a naive `.get(d)` keyed on the row date. Cleanest: have the ratio dicts keyed by `rep_date.year` (or return year directly from the helper for internal use) and look them up by year in the row loop.

**Step 4 — Fix the YoY guard.**
The current YoY proximity check uses `(d - prev_d).days <= 400` (line 132). With one row per fiscal year, change this to a **year-adjacency** check: `year - prev_year == 1`. This keeps the existing "non-consecutive gap → `revenue_yoy is None`" behavior (`tests/writer/test_metrics.py::test_revenue_yoy_single_year_returns_none`).

**Step 5 — Preserve existing invariants.**
- Keep `filter_defensive` (sentinel `1970-01-01` + `None` exclusion).
- `FinancialSummaryRow.period_end` stays a `date` so `renderer` `r.period_end.year` keeps working.
- Output stays **sorted ascending by fiscal year**, one row per year.

### 2.4 Acceptance criteria (Bug 2)
- For a concept set containing multiple `period_end` dates within the same year, `build_financial_summary` emits **exactly one** `FinancialSummaryRow` for that year.
- The rendered table has **one column per fiscal year**, no duplicate-year columns.
- Ratios (gross/op/net margin, FCF margin, D/E, ROE) compute when the underlying concepts exist **in the same fiscal year**, even if their exact `period_end` dates differ by a few days (the original bloat-and-blank failure).
- All existing `tests/writer/test_metrics.py` cases still pass **except** those that assert exact-date join semantics — see test plan.

---

## 3. Test plan (builder writes these)

### Bug 1 — `tests/test_pipeline.py` (extend)
- [ ] **`test_uncited_fact_discarded_before_save`**: feed `run_for_ticker` (or directly construct the dedup input) a `QualitativeFact` with `citations == []`; assert it is absent from `result["qualitative_facts"]` and that `qualitative_facts_count` excludes it. No `IndexError`.
- [ ] **`tests/store/test_repository.py::test_rerun_does_not_create_uncited_fact`**: save a fact; then save a *second* fact with a **different summary** but the **same citation span**; assert the second fact is **not surfaced** by `get_qualitative_facts` as a citation-less row (it is either dropped or carries a citation), i.e. no fact with empty `citations` is ever returned.

### Bug 2 — `tests/writer/test_metrics.py` (extend + adjust)
- [ ] **`test_same_fiscal_year_restatements_collapse_to_one_row`**: `Revenues = [(2009-01-25, 100), (2009-01-26, 105)]` → exactly one row, year 2009, value from the latest `period_end` (105).
- [ ] **`test_cross_concept_floating_fye_still_aligns`**: `Revenues @ 2010-01-31`, `GrossProfit @ 2010-01-25` → one 2010 row with a non-`None` `gross_margin` (the original "blank because dates differ" bug).
- [ ] **`test_yoy_uses_year_adjacency`**: consecutive fiscal years compute YoY; a one-year gap yields `None` (port the existing `400-day` intent to year adjacency).
- [ ] **Adjust** `TestAlignByPeriod` expectations only if the ratio call-sites are migrated to `align_by_fiscal_year`; if `align_by_period` is retained unchanged, leave those tests as-is and add new `TestAlignByFiscalYear` cases.
- [ ] Re-confirm `test_sentinel_period_excluded`, `test_missing_denominator_returns_none`, `test_fcf_sign_convention_ocf_minus_capex` still pass.

---

## 4. Step-by-step execution checklist

**Phase A — Bug 1 (pipeline + repository)**
1. [ ] Read `tearsheet/pipeline.py` lines 96-108 and `tearsheet/store/repository.py` lines 224-277 in full.
2. [ ] **Fix 1A:** add the empty-citations guard + `cited_facts` filter in the pipeline dedup loop; add the `discarded_uncited` warning log.
3. [ ] **Fix 1B:** in `save_qualitative_facts`, add `if not f.citations: continue`; capture `Citation` insert results via `.returning(Citation.id)`; only append a fact to `saved_facts` when at least one citation is attached (newly inserted or already owned by this fact id).
4. [ ] Add the two Bug-1 tests (§3); run `pytest tests/test_pipeline.py tests/store/test_repository.py`.

**Phase B — Bug 2 (metrics)**
5. [ ] Read `tearsheet/writer/metrics.py` lines 57-148 in full.
6. [ ] Add `collapse_series_by_fiscal_year` and `align_by_fiscal_year`; **leave `align_by_period` intact**.
7. [ ] Rewrite `build_financial_summary`: year-keyed `all_years`, representative date per year, ratio dicts keyed by year, YoY year-adjacency guard. Preserve `filter_defensive` and ASC ordering.
8. [ ] Add/adjust the Bug-2 tests (§3); run `pytest tests/writer/`.

**Phase C — Integration & regeneration**
9. [ ] Run the full suite: `pytest`.
10. [ ] **Regenerate the NVDA dossier from a clean slate** (the global-citation-span residual means stale citation rows can still block new spans on an *in-place* re-run): clear this company's `qualitative_facts` + `citations` (or rebuild the DB), re-run the pipeline for `NVDA`, then re-render via the CLI `render` command.
11. [ ] **Manual verification gates:**
    - [ ] Grep the rendered `nvda_dossier.md` for `[UNCITED — investigate]` → **zero matches**.
    - [ ] Inspect the financial table header → **one column per fiscal year**, no duplicates, ratio rows populated (not all `—`).
12. [ ] Log the two **out-of-scope follow-ups** (not fixed here): (a) scope `Citation` uniqueness to include `qualitative_fact_id`; (b) thread `filed_date` through `get_financial_series` for true latest-filed within-year resolution.

---

## 5. Explicitly out of scope
- Any change to `renderer.py` / `dossier.py` (the canary and the columns are *correct* reflections of bad input).
- Schema migrations (`Citation` uniqueness, `FinancialFact` columns).
- Threading `filed_date` into the metrics read surface.
- Touching the grounding gate (`grounding.py`) — it is already correctly rejecting bad quotes; the leak is downstream of it.
