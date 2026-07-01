# Tearsheet — Semantic Chunking Specification (Emergency Pivot)

**Status:** Approved-for-scaffolding blueprint. No code written.
**Trigger:** Production failure on **NVDA**. `extract_risk_factors` raised `ValueError: Document text exceeds maximum context window.` NVDA's Item 1A overflows the single-prompt path.
**Goal:** Split oversized Item 1A text into overlapping, semantically-clean chunks; extract per chunk; aggregate and ground into the existing fact store **without corrupting citation offsets or creating duplicates.**

---

## 0. Root Cause (what actually fails today)

The failure is a deliberate guard, not an SDK error:

```
# extract/qualitative.py (current)
if len(document.text) > 100000:
    raise ValueError("Document text exceeds maximum context window.")
```

The current `extract_risk_factors` design assumes one document = one prompt = one grounding pass. NVDA's Item 1A breaks that assumption. Chunking replaces this guard; the guard line must be **removed** as part of this work.

### The single most important correctness invariant

The Grounding Gate computes offsets relative to whatever string it is given:

```
# extract/grounding.py (current)
match = re.search(pattern_str, source_text, re.IGNORECASE)
return GroundedSpan(start_offset=match.start(), end_offset=match.end(), ...)
```

Those offsets are written verbatim into `Citation.start_offset / end_offset`, and the future dossier writer renders citations by slicing **`Document.text`** (the frozen full section). Therefore:

> **Chunks are fed to the LLM only. Grounding MUST run against the full `document.text`, never against a chunk substring.**

If grounding ran against a chunk, every offset would be chunk-local and point into the wrong part of the frozen document. Running the gate against the whole `document.text` makes all offsets inherently document-global and eliminates any offset-translation math. The chunk's only job is to fit the model's context so it can *find* risks and return `exact_quote` strings; the gate then locates those strings in the full text on its own. This is the design's keystone.

---

## 1. Chunking Math

### 1.1 Units and sizes

Chunk by **characters**, not tokens — it matches the existing char-based guard, needs no tokenizer dependency, and is deterministic for testing. A token sanity check is folded into the choice of size.

| Parameter | Value | Rationale |
|---|---|---|
| `MAX_CHUNK_CHARS` | **40,000** | ≈ 10k tokens at ~4 chars/token. Leaves ample headroom under any modern context window for the system prompt **and** the structured-output response. Comfortably below the old 100k ceiling, so no single chunk can re-trigger the overflow. |
| `CHUNK_OVERLAP_CHARS` | **4,000** | The overlap window must exceed the largest realistic single risk factor so no risk is ever cut in half across a boundary (see §1.3). |
| Split boundary | **paragraph (`\n\n`)** | "Semantic" = never cut mid-sentence/mid-paragraph. Chunks are packed from whole paragraphs. |

### 1.2 Semantic (paragraph-aware) packing

Do **not** slice at a raw character index — that splits sentences and produces fragment quotes the gate may reject. Instead:

1. Split `document.text` into paragraphs on blank-line boundaries, **preserving original text** (so the gate's whitespace-flexible match still resolves).
2. Greedily accumulate whole paragraphs into the current chunk until adding the next paragraph would exceed `MAX_CHUNK_CHARS`.
3. Start the next chunk by **carrying over trailing paragraphs from the previous chunk** totaling ~`CHUNK_OVERLAP_CHARS`, then continue packing.
4. Edge case: a single paragraph larger than `MAX_CHUNK_CHARS` (rare). Fall back to a hard character split **for that paragraph only**, on a sentence boundary if possible; it is the one place a clean paragraph cut is impossible. Log it.

### 1.3 Why 4,000-char overlap is enough (the anti-split proof)

A 10-K risk factor is a bounded unit: a bold lead-in sentence plus an explanatory paragraph, almost always under ~3,000 characters. Setting overlap to **4,000 > max realistic risk length** guarantees that any risk straddling a chunk boundary appears **whole** inside the following chunk's leading overlap region. Consequences:

- The LLM always sees at least one complete copy of every risk → it never has to reconstruct an unseen second half, which is exactly what produces a hallucinated `exact_quote` that **fails the gate**.
- Because grounding runs against the full document (§0), even a quote drawn from the overlap resolves to the same global span regardless of which chunk surfaced it.

Overlap is a tunable constant; if a filer is found with unusually long risk prose, raise `CHUNK_OVERLAP_CHARS`, not the architecture.

---

## 2. Looping Logic

Separation of concerns: **chunks drive the LLM; the full document drives the gate; spans drive the facts.**

```
extract_risk_factors(document):
    text = document.text
    chunks = semantic_chunks(text, MAX_CHUNK_CHARS, CHUNK_OVERLAP_CHARS)

    candidates = []                      # raw RiskFactor objects, all chunks
    for chunk in chunks:
        parsed = llm.complete_structured(system_prompt, chunk, RiskList)
        candidates.extend(parsed.risks)  # aggregate BEFORE grounding

    # Gate runs ONCE, against the FULL frozen text -> global offsets
    result = verify_quotes(text, candidates, document_id=document.id)

    spans = dedupe_by_span(result.accepted)   # see Section 3
    return [build_fact(span) for span in spans]
```

Key points:
- **Sequential** chunk calls (simple, ordered, cheap to reason about; parallelism is a later optimization, not needed to fix NVDA).
- Candidates from all chunks are pooled **before** grounding, so grounding and dedup see the complete set at once.
- The gate is invoked a **single time** over `document.text`. This both gives global offsets and lets the span-dedup collapse overlap duplicates in one place.
- Fact construction is unchanged from today's accepted-span loop (`category="risk_factor"`, one `Citation` per span).

---

## 3. Deduplication — Confirmation + One Required Safeguard

**Question posed:** will the existing `Repository.save_qualitative_facts` (atomic upserts on unique constraints) absorb the duplicate risks that overlapping windows inevitably produce, without throwing?

**Answer: No errors will ever be thrown — confirmed — but DB constraints alone are _not sufficient_ to dedupe correctly. A pre-persistence span-dedup pass is required.** Details:

### 3.1 What the repository guarantees (confirmed safe)
- `save_qualitative_facts` upserts facts with `on_conflict_do_nothing` on `(company_id, category, summary)`, then re-selects the existing id. Citations insert with `on_conflict_do_nothing` on `(document_id, start_offset, end_offset)`.
- **Therefore: duplicate inserts are idempotent no-ops. No `IntegrityError` can surface from overlap duplicates.** That part of the question is a clean yes.
- **Exact-duplicate facts** (identical summary string) collapse to one row. **Exact-duplicate citations** (identical span) collapse to one row.

### 3.2 The wrinkle the constraints do NOT solve
Two failure modes survive pure DB-level dedup:

1. **Summary drift.** The same underlying risk, surfaced from two overlapping chunks, can come back with *slightly different* summary wording. Different summary strings → the `(company_id, category, summary)` constraint sees them as **distinct** → two near-duplicate facts persist.
2. **Span is the citation's only key.** `Citation`'s unique constraint is the span alone — `(document_id, start_offset, end_offset)` — **not** `(fact_id, span)`. So a given span can attach to exactly **one** fact. If summary drift creates two facts that ground to the *same span*, the first fact wins the citation and the second fact's citation insert is silently skipped — leaving a **citation-less, unverifiable fact**, which violates "no span, no claim."

### 3.3 Required safeguard: dedupe by grounded span before building facts
Collapse accepted spans on the global offset key **before** constructing `QualitativeFact` objects:

- Key candidates on `(start_offset, end_offset)` after grounding.
- For collisions, keep one (e.g. the first / shortest summary) and discard the rest.
- Result: **one grounded span → exactly one fact → exactly one citation**, which is the invariant the store wants and the dossier writer depends on.

With this pass in place, the repository's idempotent upserts become a clean *second* line of defense rather than the *only* one. The two layers together: span-dedup removes semantic duplicates in memory; DB constraints absorb any exact repeats and guarantee no throw.

---

## 4. Execution Task List (builder agent)

> Scope: make `extract_risk_factors` chunk-aware. Do **not** modify `grounding.py`, `repository.py`, `models.py`, or `schemas.py` — they are correct and load-bearing. Grounding still runs against full `document.text`. All LLM I/O stays mocked (offline, token-free suite).

### A. Chunker — `extract/qualitative.py` (or a small new helper module)
- [ ] Add constants `MAX_CHUNK_CHARS = 40000`, `CHUNK_OVERLAP_CHARS = 4000`.
- [ ] Implement `semantic_chunks(text, max_chars, overlap_chars) -> list[str]`:
  - [ ] Split into paragraphs on blank lines, preserving original characters.
  - [ ] Greedily pack whole paragraphs up to `max_chars`.
  - [ ] Begin each next chunk with trailing paragraphs (~`overlap_chars`) carried over from the previous chunk.
  - [ ] Handle the oversized-single-paragraph edge case with a logged sentence-boundary fallback split.
  - [ ] Guarantee: every chunk ≤ `max_chars` (so the overflow can't recur); short docs yield exactly one chunk (back-compat).

### B. Rewire `extract_risk_factors` — `extract/qualitative.py`
- [ ] **Remove** the `if len(document.text) > 100000: raise ValueError(...)` guard.
- [ ] Keep the existing validity checks (`document.id`, `document.filing`, `company_id`).
- [ ] Chunk `document.text`; loop chunks sequentially calling `llm.complete_structured(..., user_prompt=chunk, response_model=RiskList)`.
- [ ] Aggregate all `parsed.risks` into one candidate list.
- [ ] Call `verify_quotes(document.text, candidates, document_id=document.id)` **once, against the full text** (global offsets — do not pass a chunk here).
- [ ] Add `dedupe_by_span(accepted)` keyed on `(start_offset, end_offset)`; one span → one fact (§3.3).
- [ ] Build `QualitativeFact` + single `Citation` per deduped span (unchanged construction logic).

### C. Persistence (already built — do not modify)
- [ ] Confirm facts still flow through `repository.save_qualitative_facts`; rely on its idempotent upserts as the second dedup layer.

### D. Pipeline (verify only)
- [ ] Confirm `pipeline.py` calls `extract_risk_factors(doc_1a)` unchanged — the new internals are transparent to the orchestrator.

### E. Tests — `tests/extract/test_qualitative.py` (extend) + a chunker unit test
- [ ] **Chunker units:** a short text → exactly one chunk; a >40k-char text → multiple chunks, each ≤ 40k; assert consecutive chunks share overlap; assert no chunk cuts a paragraph except the logged oversized-paragraph fallback.
- [ ] **Anti-split:** craft a risk paragraph positioned to straddle a boundary; assert it appears whole in the next chunk's overlap and grounds to a single global span.
- [ ] **Offset integrity:** with a multi-chunk doc, assert every accepted `start/end_offset` indexes into `document.text` such that `document.text[start:end]` equals the stored `quote` (proves global, not chunk-local, offsets).
- [ ] **Dedup:** mock the LLM to emit the same risk from two overlapping chunks (incl. a summary-drift variant grounding to the same span); assert `dedupe_by_span` yields one fact with one citation; assert a second `save_qualitative_facts` call is an idempotent no-op (no `IntegrityError`).
- [ ] **No-overflow regression:** feed an NVDA-sized (>100k char) synthetic Item 1A; assert it no longer raises and produces grounded facts.
- [ ] Run full suite — all green, zero network calls.

---

## 5. Decisions & Flags
- **Char-based, paragraph-aware chunking** chosen over token-based to avoid a tokenizer dependency and stay deterministic for tests. Token budget is respected via the conservative 40k/4k sizing.
- **Grounding against full `document.text`** is non-negotiable — it is what keeps citation offsets valid (§0). Any future "ground per chunk for speed" optimization MUST add offset translation (`chunk_start + match.start()`) and is explicitly out of scope here.
- **Span-dedup is required, not optional** — DB constraints prevent crashes but cannot prevent summary-drift duplicates or the silent citation-loss described in §3.2.
- Sequential chunk calls accepted for v1; parallelization deferred.
