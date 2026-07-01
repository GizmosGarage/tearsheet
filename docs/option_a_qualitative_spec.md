# Tearsheet — Option A: Qualitative Expansion Specification (Item 1 + Item 7)

**Status:** Approved-for-scaffolding blueprint. No code written.
**Goal:** Extend the proven Item 1A risk-factor engine to extract structured, grounded facts from **Item 1 (Business)** and **Item 7 (MD&A)**, reusing the existing chunker, Grounding Gate, and `QualitativeFact` store unchanged.

**Extraction targets:**
- **Item 1 (Business):** Core Revenue Streams, Competitors, Competitive Moats/Advantages.
- **Item 7 (MD&A):** Liquidity & Capital Resources, Key Performance Indicators (KPIs), Management's Forward-Looking Sentiment.

---

## 0. Current State (what we build on)

The risk-factor path is the template to generalize. As of this audit it does, in order ([qualitative.py](../tearsheet/extract/qualitative.py)):
1. Validity checks (`document.id`, `document.filing`, `company_id`).
2. `_chunk_text(text, chunk_size=40000, overlap=4000)` — semantic paragraph chunker, already in production.
3. Per-chunk `llm.complete_structured(system_prompt, user_prompt=chunk, response_model=RiskList)`.
4. Aggregate candidates → `verify_quotes(document.text, candidates, document_id)` **once, against full text** (global offsets).
5. Dedupe accepted spans on `(start_offset, end_offset)`.
6. Build `QualitativeFact(category="risk_factor")` + one `Citation` per span.

**Three invariants Option A must not break:**
- **Grounding is duck-typed on two fields.** `verify_quote_span` reads only `quote.exact_quote` and `quote.summary` ([grounding.py:36,52](../tearsheet/extract/grounding.py)). Therefore *every* new item model MUST expose `summary: str` and `exact_quote: str`. This is the "strict grounding requirement" the directive mandates.
- **The gate runs against full `document.text`**, never a chunk — that is what keeps `Citation` offsets global and valid.
- **`Citation`'s unique key is the span alone** — `(document_id, start_offset, end_offset)`. A given quote span can attach to exactly **one** fact across the whole document, regardless of category (see §2.3 — this drives a required global span-dedup).

**Two latent issues found during this audit (flagged, see §6):**
- The prompt files end with a literal `Source text:\n{source_text}` placeholder that is **never substituted** — `extract_risk_factors` passes the file as `system_prompt` and the chunk as a separate `user_prompt`. New prompts must omit the placeholder.
- `extract_business` / `extract_management_discussion` currently have the wrong return type annotation (`-> RiskList`); they should return `list[QualitativeFact]`.

---

## 1. Pydantic Schemas

### 1.1 Shared grounded base (the grounding contract)

Every extractable item inherits one base so the global gate verifies it with zero changes:

```python
class GroundedItem(BaseModel):
    summary: str = Field(description="A concise plain-English summary of this item.")
    exact_quote: str = Field(
        description="Exact verbatim substring copied from the source text. No paraphrase.",
        min_length=3,
    )
```

`RiskFactor` already has this exact shape; it may optionally be refactored to inherit `GroundedItem`, but that is not required and is out of scope for this work.

### 1.2 Item 1 — Business

A grouped schema with one named list per target. Grouping (rather than a single self-labeled list) lets the *structure* carry the category, removing reliance on the LLM to label correctly:

```python
class BusinessProfile(BaseModel):
    revenue_streams: list[GroundedItem] = Field(default_factory=list,
        description="Core products/services/segments the company earns revenue from.")
    competitors: list[GroundedItem] = Field(default_factory=list,
        description="Named or described competitors and competitive pressures.")
    moats: list[GroundedItem] = Field(default_factory=list,
        description="Durable competitive advantages: scale, IP, switching costs, brand, network effects.")
```

### 1.3 Item 7 — MD&A

```python
class MDAnalysis(BaseModel):
    liquidity: list[GroundedItem] = Field(default_factory=list,
        description="Liquidity & capital resources: cash position, debt, credit facilities, capital allocation.")
    kpis: list[GroundedItem] = Field(default_factory=list,
        description="Key performance indicators and operating metrics management emphasizes.")
    forward_sentiment: list[GroundedItem] = Field(default_factory=list,
        description="Management's forward-looking statements, outlook, guidance, and tone.")
```

**Why grouped lists, not one flat `category`-tagged list:** the named-list structure maps each field deterministically to a `QualitativeFact.category` at the call site (§4), so the gate and the store never need to know about categories. `default_factory=list` lets the model legitimately return empty groups (e.g. a filing with no disclosed KPIs) without failing structured parsing.

---

## 2. Database Schema Mapping

### 2.1 No model change required

`QualitativeFact(company_id, category, summary)` + `Citation(span)` already accommodate every new fact type. The discriminator is the existing **`category` string**. No migration, no new columns. Each `GroundedItem` becomes exactly one `QualitativeFact` + one `Citation`, identical to the risk path.

### 2.2 Category string values (the new enum)

| Source | Schema field | `QualitativeFact.category` |
|---|---|---|
| Item 1A | (risk) | `risk_factor` *(existing)* |
| Item 1 | `revenue_streams` | `revenue_stream` |
| Item 1 | `competitors` | `competitor` |
| Item 1 | `moats` | `competitive_moat` |
| Item 7 | `liquidity` | `liquidity` |
| Item 7 | `kpis` | `kpi` |
| Item 7 | `forward_sentiment` | `forward_looking_sentiment` |

Define these as a module-level constant (e.g. `Category` string constants or a `StrEnum`) so the field→category mapping lives in one reviewable place and the dossier writer can query by a known vocabulary.

### 2.3 Deduplication across categories — required global span-dedup

The risk path dedupes spans within a single category. Option A introduces **multiple categories per document**, which collides with `Citation`'s span-only unique key:

- If the LLM cites the *same sentence* for, say, a `competitor` and a `competitive_moat`, both facts ground to the same `(document_id, start, end)`.
- `save_qualitative_facts` inserts citations with `on_conflict_do_nothing` on the span — so the **first** fact claims the citation and the **second fact is persisted citation-less**, violating "no span, no claim."

**Required safeguard:** dedupe accepted spans **globally across all categories** for a document before building facts — one span → one fact, with deterministic precedence (e.g. first category processed wins). This guarantees the one-span-one-fact-one-citation invariant. Consequence to accept for v1: a quote that genuinely supports two categories is recorded once; prompts (§3) instruct the model to prefer distinct quotes per item to minimize this. The repository's idempotent upserts remain the second line of defense and guarantee no `IntegrityError`.

---

## 3. LLM Prompt Strategy

**Format rule (from the audit):** prompts are sent as the **system message**; the chunk text arrives as a **separate user message**. Therefore the new prompt files MUST NOT contain a `{source_text}` placeholder or any trailing "Source text:" block. They are pure instruction.

**Shared grounding clause** (include verbatim in every prompt):

```
GROUNDING RULES (mandatory):
- For every item, `exact_quote` MUST be copied verbatim, character-for-character, from the
  source text provided in the user message — including original punctuation and capitalization.
- Never paraphrase, summarize, translate, or alter text inside `exact_quote`. Summaries belong
  only in the `summary` field.
- If you cannot find a verbatim quote for a claim, do not emit that item.
- Prefer a distinct quote for each item; do not reuse the same sentence for multiple items.
- If a category has nothing in this text, return an empty list for it. Do not invent content.
```

### 3.1 `prompts/business.txt` (Item 1) — replace existing

```
You are a financial analyst extracting the BUSINESS PROFILE from Item 1 of an SEC 10-K filing.

Extract three groups, each as a list of grounded items:
1. revenue_streams — the core products, services, and segments the company earns money from.
   Capture HOW the company makes money, not generic mission statements.
2. competitors — specific competitors named or described, and the nature of competitive pressure.
3. moats — durable competitive advantages: scale, proprietary technology/IP, switching costs,
   brand, regulatory barriers, network effects. Only include advantages the text actually asserts.

Be selective and material. One item per distinct idea.

<shared GROUNDING RULES clause here>
```

### 3.2 `prompts/management_discussion.txt` (Item 7) — replace existing

```
You are a financial analyst extracting MANAGEMENT'S DISCUSSION & ANALYSIS from Item 7 of an SEC 10-K.

Extract three groups, each as a list of grounded items:
1. liquidity — liquidity and capital resources: cash and equivalents, debt levels, credit
   facilities, ability to fund operations, and capital allocation (buybacks, dividends, capex).
2. kpis — the key performance indicators and operating metrics management uses to explain
   results (e.g. growth rates, margins, segment metrics, unit economics).
3. forward_sentiment — management's forward-looking outlook, guidance, expectations, and tone.
   Capture statements about the future, not historical recaps.

Be selective and material. One item per distinct idea.

<shared GROUNDING RULES clause here>
```

(The existing `prompts/competition.txt` was superseded — competition is now a group inside the Business schema, not a separate extractor. **DECISION (locked): deleted.** The file has been removed from the repo. The orphaned `extract_competition` stub in `qualitative.py` should also be removed during scaffolding.)

---

## 4. Pipeline Routing

### 4.1 Generalized extractor helper (new, in `extract/qualitative.py`)

Refactor the proven risk flow into one reusable helper so each section extractor is a thin wrapper:

```
def _extract_grouped(document, system_prompt, response_model, field_to_category, llm):
    validity checks (id / filing / company_id)
    chunks = _chunk_text(document.text)
    per category: candidates[category] = []
    for chunk in chunks:
        parsed = llm.complete_structured(system_prompt, chunk, response_model)
        for field, category in field_to_category.items():
            candidates[category].extend(getattr(parsed, field))
    accepted_by_span = {}                       # global, across categories
    for category, items in candidates.items():
        result = verify_quotes(document.text, items, document_id=document.id)
        for span in result.accepted:
            key = (span.start_offset, span.end_offset)
            if key not in accepted_by_span:     # global span-dedup (§2.3)
                accepted_by_span[key] = (category, span)
    build one QualitativeFact(category=...) + one Citation per surviving span
    return list[QualitativeFact]
```

Then:

```
def extract_business(document, *, llm=None) -> list[QualitativeFact]:
    return _extract_grouped(document, _load_prompt("business.txt"), BusinessProfile,
        {"revenue_streams":"revenue_stream","competitors":"competitor","moats":"competitive_moat"}, llm)

def extract_management_discussion(document, *, llm=None) -> list[QualitativeFact]:
    return _extract_grouped(document, _load_prompt("management_discussion.txt"), MDAnalysis,
        {"liquidity":"liquidity","kpis":"kpi","forward_sentiment":"forward_looking_sentiment"}, llm)
```

`extract_risk_factors` may optionally be re-expressed on `_extract_grouped` (single field → `risk_factor`), but since it is in production and working, refactoring it is optional and lower priority than adding the two new extractors.

### 4.2 `pipeline.py` routing

Replace the single `doc_1a` lookup with a section map and route each present section through its extractor, accumulating facts before one save:

```
docs_by_section = {d.section: d for d in saved_docs}   # keys are "1", "1A", "7" (sectioner output)

all_qual_facts = []
routes = [("1A", extract_risk_factors),
          ("1",  extract_business),
          ("7",  extract_management_discussion)]
for section, extractor in routes:
    doc = docs_by_section.get(section)
    if doc is None:
        errors.append(f"Section {section} not found for {ticker}")
        continue
    try:
        all_qual_facts.extend(extractor(doc))
    except Exception as e:
        errors.append(f"{section} extraction failed: {e}")

saved_qual_facts = self.repo.save_qualitative_facts(all_qual_facts)
```

**Behavioral change to confirm:** today a missing Item 1A *raises*. Under the new routing, a missing section is logged to `errors` and skipped (matching the financials branch's resilience), so an absent Item 7 never aborts the whole run. The structured `run_for_ticker` return dict (already in place) carries the combined `qualitative_facts` and `errors`. Per-category counts can be added to the summary if the dossier layer wants them.

---

## 5. Execution Task List (builder agent)

> Reuse the chunker, Grounding Gate, and repository **unchanged**. All LLM I/O stays mocked (offline, token-free suite).

### A. Schemas — `extract/schemas.py`
- [ ] Add `GroundedItem(summary, exact_quote min_length=3)` base.
- [ ] Add `BusinessProfile(revenue_streams, competitors, moats)` — each `list[GroundedItem]`, `default_factory=list`.
- [ ] Add `MDAnalysis(liquidity, kpis, forward_sentiment)` — each `list[GroundedItem]`, `default_factory=list`.
- [ ] (Optional) Make `RiskFactor` inherit `GroundedItem`; do not change its field shape.

### B. Category vocabulary — `extract/qualitative.py` (or `schemas.py`)
- [ ] Add constants for the seven category strings (§2.2) in one place.

### C. Generalized extractor — `extract/qualitative.py`
- [ ] Implement `_extract_grouped(document, system_prompt, response_model, field_to_category, llm)` per §4.1, including **global span-dedup across categories** (§2.3).
- [ ] Implement `extract_business` → `BusinessProfile` + field map; fix return type to `list[QualitativeFact]`.
- [ ] Implement `extract_management_discussion` → `MDAnalysis` + field map; fix return type to `list[QualitativeFact]`.
- [ ] Leave `extract_risk_factors` working; optional refactor onto the helper.

### D. Prompts — `extract/prompts/`
- [ ] Rewrite `business.txt` (§3.1) — **no `{source_text}` placeholder**, include shared grounding clause.
- [ ] Rewrite `management_discussion.txt` (§3.2) — same rules.
- [ ] Decide fate of `competition.txt` (superseded) — delete or leave unused.

### E. Pipeline routing — `pipeline.py`
- [ ] Build `docs_by_section` map; route `1A`/`1`/`7` through their extractors (§4.2).
- [ ] Accumulate facts, single `save_qualitative_facts` call.
- [ ] Convert missing-section hard failure into a logged `errors` entry (resilient, like the financials branch). **DECISION (locked): missing sections — including Item 1A — are non-fatal. Log, skip, continue so partial filings still yield whatever sections are present.**
- [ ] Remove the orphaned `extract_competition` stub from `qualitative.py` (its prompt file is already deleted).

### F. Tests
- [ ] `tests/extract/test_schemas.py` — `GroundedItem`/`BusinessProfile`/`MDAnalysis` validate; empty groups allowed; `exact_quote` min_length enforced.
- [ ] `tests/extract/test_qualitative.py` — mock LLM returning grouped output across two chunks; assert correct category assignment per field; assert global span-dedup (same quote in two categories → one fact); assert offsets index into `document.text`.
- [ ] `tests/test_pipeline.py` — patch all three extractors; assert routing finds `1`/`1A`/`7`; assert a missing Item 7 yields an `errors` entry but does not abort; assert combined facts saved once.
- [ ] Full suite green, zero network calls.

---

## 6. Decisions & Flags
- **No DB migration** — category-string discrimination reuses `QualitativeFact` as-is; the dossier writer queries by the §2.2 vocabulary.
- **Grouped schemas over self-labeled flat lists** — structure carries the category, reducing LLM labeling error.
- **Global span-dedup is required** (§2.3), not optional — `Citation`'s span-only unique key means a quote can ground only one fact; without global dedup, cross-category quote reuse silently drops citations.
- **Prompt placeholder bug (pre-existing)** — `{source_text}` in `risk_factors.txt`/`business.txt` is never substituted and is shipped to the model literally. New prompts omit it; recommend cleaning the risk prompt too (small, separate).
- **`competition.txt` deleted (locked)** — competition folds into the Business schema; no standalone competition extractor. The `extract_competition` stub is now orphaned and slated for removal during scaffolding.
- **Routing resilience (locked)** — missing sections become logged `errors` entries instead of aborting the run, **including Item 1A** (previously fatal). Rationale: a company that mis-filed Item 7 should still yield its Item 1 and Item 1A data.
- **Section keys verified against the sectioner** — `Document.section` values are bare codes `"1"`, `"1A"`, `"7"` (uppercased, spaces stripped); routing matches these exactly.
