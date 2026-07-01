# The Foundation Build Guide

## Brick-by-brick instructions for constructing Tearsheet's zero-hallucination extraction foundation

---

## Part I — Context you must internalize before touching anything

**The project.** Tearsheet, at `C:\Users\ethan\Desktop\Tearsheet`, is a Python 3.11 package (`tearsheet/`) that extracts data from SEC filings. Current pipeline: `edgar/` fetches from EDGAR APIs → `parse/documents.py` sections the filing HTML → `extract/financials.py` pulls XBRL numbers and `extract/qualitative.py` uses an LLM → `store/` persists via SQLAlchemy ORM to SQLite → `writer/` renders a markdown dossier. CLI entry is `tearsheet/cli.py`, orchestration is `tearsheet/pipeline.py`, tests live in `tests/`.

**The mission.** Rebuild the foundation so it satisfies this identity: *a notarized evidence file for a single company — every byte either came from an SEC filing verbatim or was derived from XBRL by visible arithmetic, and the corpus can prove it on demand, offline, forever.*

**The five invariants.** Every brick serves these. If an instruction ever seems to conflict with an invariant, the invariant wins and you must stop and report the conflict rather than proceed.

1. **No authored content.** No stored field contains text an LLM wrote. Labels are extracted text; values are as-filed or visibly derived.
2. **Self-contained provenance.** Every claim resolves to bytes archived inside the corpus. Verification never requires EDGAR.
3. **Verbatim-or-nothing.** Text enters the corpus only as an exact slice of an archived source. Non-resolving spans are rejected *and recorded as rejected*.
4. **Transparent gaps.** "Sought but not found" is a first-class record with a reason, never a silent absence or a log line.
5. **Versioned output.** Every corpus records the extractor version that made it.

**Global rules for the whole build:**

- **The dev database is disposable.** The corpus is always rebuildable from EDGAR, so schema changes are destructive-by-design: delete the SQLite file and re-extract. Do NOT introduce Alembic or migrations.
- **Tests run offline.** Unit tests use small synthetic fixtures (short HTML strings, hand-built XBRL dicts). Never call the network in a unit test. Real EDGAR data is fetched only in the golden-fixture bricks, then hash-pinned and reused from disk.
- **Match existing code style.** Read neighboring code before writing; mirror its naming, typing (`from __future__ import annotations`, `Mapped[...]` ORM style), and comment density (which is low — module docstrings, few inline comments).
- Work on a branch named `foundation`. Create it from `main` before Brick 0's commit.
- Commit messages use the repo's prefix style (`fix:`, `writer:`): use `foundation:` for this work, and end each commit message with the co-author line your harness specifies.

---

## Part II — The Ritual (execute this for every single brick, no exceptions)

For each brick, in order:

1. **UNDERSTAND.** Read every file listed in the brick's *Read first* line, plus any file you're about to modify. Then write, in your working notes, one paragraph stating what you are about to build and which invariant(s) it serves. If what you find in the code contradicts what this guide says the code contains, stop and re-derive the correct approach from the invariants before building.
2. **BUILD.** Implement exactly the brick's scope. Do not pull work forward from later bricks, even when it's tempting — later bricks depend on earlier ones being committed and green in isolation.
3. **TEST.** Write the brick's specified tests, then run **the full test suite** (`python -m pytest tests/ -x -q`), not just the new tests. A brick is not done while any test fails.
4. **FIX.** If tests fail, diagnose and fix until green. If you genuinely cannot make it green, stop the entire build and report what's blocking — do not skip, weaken, or delete a failing test to proceed.
5. **COMMIT.** `git add` the brick's files and commit with the brick's specified message. One brick = one commit.
6. Only after the commit exists may you read the next brick.

---

## Part III — The Bricks

### Brick 0 — Baseline

**Goal:** Know the true starting state before changing anything.
**Read first:** `tearsheet/pipeline.py`, `tearsheet/store/models.py`, `tearsheet/store/repository.py`, `tearsheet/config.py`, `tearsheet/cli.py`, everything under `tests/`.
**Build:** Nothing. Create branch `foundation`. Run the full test suite and record which tests pass. If the suite fails at baseline, fix only what's needed to get a green baseline (or document pre-existing failures in a `docs/foundation-baseline.md` note).
**Test:** `python -m pytest tests/ -q` — record the output.
**Commit:** `foundation: record green baseline before foundation rebuild` (include the baseline note if you made one).

---

### Brick 1 — The archive: `SourceDocument` + accession-keyed raw storage

**Goal:** Invariant 2's anchor. Every filing's raw bytes archived, hashed, collision-proof.
**Read first:** `tearsheet/edgar/filings.py`, `tearsheet/edgar/client.py`, `tearsheet/config.py`, `tearsheet/store/models.py`, `tearsheet/store/repository.py`.
**Build:**

1. In `models.py`, add `SourceDocument`: `id`, `filing_id` (FK, indexed), `filename` (String), `sequence` (Integer, nullable), `doc_type` (String, nullable), `sha256` (String(64), indexed), `byte_size` (Integer), `edgar_url` (Text), `fetched_at` (DateTime, server default now). Unique constraint on `(filing_id, filename)`. Relationship to `Filing`.
2. Replace the body of `download_filing_documents` in `filings.py` (keep a compatible signature or update all callers) with an `acquire_filing(cik, accession_number)` function that:
   - Fetches the accession's **document index** (`https://www.sec.gov/Archives/edgar/data/{cik_stripped}/{accession_nodash}/index.json`) to enumerate *all* documents in the accession, not just the primary one.
   - Downloads each document to `{RAW_FILINGS_DIR}/{cik}/{accession_number}/{filename}`. This fixes the existing bug where files were cached by bare filename (`cache_dir / primary_doc`), letting two companies' `form10-k.htm` collide.
   - Computes `sha256` of each file's bytes. Idempotency: if the file exists on disk, re-hash it; if the hash matches a stored `SourceDocument`, skip re-download; if it mismatches, re-download and treat the stored record as stale (overwrite it).
   - Returns metadata for all documents plus which one is primary.
3. Add repository methods to upsert `SourceDocument` rows.
4. Wire the pipeline's download step to `acquire_filing`, persisting `SourceDocument` rows and keeping the primary document path flowing to the parser as before.

**Test:** Unit tests with a mocked HTTP client (fake index.json + two fake documents): correct on-disk layout; correct sha256 stored; second call performs zero downloads; a tampered on-disk file triggers re-download; two different CIKs with identically-named primary docs land in different directories.
**Commit:** `foundation: archive full accessions with hashed, accession-keyed source documents`

---

### Brick 2 — Chain of custody on extracted text

**Goal:** Offsets must point into text whose lineage is hash-verifiable back to archived bytes.
**Read first:** `tearsheet/parse/documents.py`, `tearsheet/store/models.py`, `tearsheet/pipeline.py`.
**Build:**

1. `Document` gains: `source_document_id` (FK to `SourceDocument`), `text_sha256` (String(64)) — sha256 of the exact `text` string (UTF-8 encoded), `extraction_method` (String: `"sectioner"` or `"llm_locator"`; the sectioner path sets `"sectioner"`).
2. `build_documents` must accept/receive the `SourceDocument` id of the file it parsed and stamp all three new fields on every `Document` it produces.
3. In the repository save path, recompute `text_sha256` from `text` at save time and refuse (raise) if it doesn't match the stamped value — cheap custody check at the write boundary.

**Test:** Unit test: parse a small synthetic HTML fixture, assert every returned `Document` carries the source document id and a `text_sha256` that equals `hashlib.sha256(doc.text.encode()).hexdigest()`. Test the repository raises on a deliberately corrupted hash.
**Commit:** `foundation: hash-chain extracted section text to archived source documents`

---

### Brick 3 — Purge authored content; `QualitativeFact` becomes `ExtractedSpan`

**Goal:** Invariant 1. This is the identity-defining breaking change.
**Read first:** `tearsheet/extract/schemas.py`, `tearsheet/extract/qualitative.py`, `tearsheet/extract/grounding.py`, `tearsheet/extract/prompts/*.txt`, `tearsheet/store/models.py`, `tearsheet/store/repository.py`, `tearsheet/pipeline.py`, and all of `tearsheet/writer/` (it renders summaries today and must not break).
**Build:**

1. **Schemas** (`schemas.py`): delete every `summary` field. The LLM's output shape becomes locator-only: for each item, `exact_quote` (the span to find) and optionally `label_quote` (a short verbatim phrase from the source — e.g. a risk factor's bold lead-in sentence — that will serve as the item's label). Update field descriptions to say, explicitly: *"Copy characters exactly from the source. You are a locator, not a writer. Any text not present verbatim in the source will be discarded."* Update the three prompt files to match — remove all instructions to summarize or paraphrase.
2. **Grounding** (`grounding.py`): `GroundedSpan` loses `summary`, gains `label`, `label_start_offset`, `label_end_offset` (nullable). Verify `label_quote` through the *same* span-resolution used for `exact_quote` (keep the whitespace-flexible locator regex; keep storing the *source slice*, never the LLM string — this pattern already exists and is correct). A span whose label doesn't resolve keeps the span and drops the label; a span whose `exact_quote` doesn't resolve is rejected entirely.
3. **Model** (`models.py`): rename `QualitativeFact` → `ExtractedSpan`, table `extracted_spans`. Drop `summary`. Add `label` (Text, nullable — always a source slice). Keep `category` (it's structural routing, not interpretation). Uniqueness moves off authored text: identity is the span itself, via the existing `Citation` unique constraint on `(document_id, start_offset, end_offset)`. Update `Company` relationships, repository methods, and `pipeline.py` accordingly.
4. **Writer**: update the dossier renderer to display verbatim quotes with their extracted labels (label as the bullet/heading text where it exists, quote beneath). Nothing in the writer may generate prose beyond fixed structural scaffolding ("Item 1A — Risk Factors" headers etc.).
5. Grep the whole repo for `summary` when done; the only survivors should be unrelated usages (if any), which you list in the commit body.

**Test:** Update all existing tests referencing `summary`/`QualitativeFact`. New tests: grounding accepts a good quote + good label; accepts a good quote + bad label (label becomes None); rejects a bad quote outright. Writer test: render from `ExtractedSpan`s and assert output contains only source-derived strings from the fixture.
**Commit:** `foundation: purge LLM-authored summaries; spans are verbatim-or-nothing with extracted labels`

---

### Brick 4 — `FinancialFact` gets ancestry and loses Float

**Goal:** Invariant 2 for numbers; restatement-safe identity.
**Read first:** `tearsheet/extract/financials.py`, `tearsheet/edgar/xbrl.py`, `tearsheet/store/models.py`, the writer's financial table code, and the recent commit `ae065ea` (fiscal-year alignment) via `git show`.
**Build:**

1. `FinancialFact` new columns: `accession_number` (String, indexed), `xbrl_concept` (String — full taxonomy-qualified tag, e.g. `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`), `context_ref` (String, nullable), `unit_ref` (String, nullable), `fiscal_year` (Integer), `fiscal_period` (String: FY/Q1–Q4), `as_filed_value` (String — the untouched value exactly as it appears in companyfacts JSON), and `derivation` (Text, nullable — JSON, see below). Change `value` from `Float` to `Numeric` (SQLite stores it fine via SQLAlchemy; precision matters for the verify brick).
2. Uniqueness becomes `(company_id, xbrl_concept, fiscal_year, fiscal_period, accession_number)` — a restatement creates a second row under its own accession instead of overwriting history.
3. `extract_financial_facts` populates all ancestry fields straight from the companyfacts payload. Any value the extractor *computes* (margins, ratios, growth) must instead emit a fact with `derivation` set to machine-readable JSON: `{"op": "div", "inputs": [<fact identity>, <fact identity>]}` where fact identity is `(xbrl_concept, fiscal_year, fiscal_period, accession_number)` — enough to re-resolve the inputs later. As-filed facts have `derivation` NULL. **If a derivation's inputs are not all present, the derived fact must not be emitted at all** (this kills the blank-revenue-with-populated-margin bug class at the source).
4. Update the writer's table code for the changed model.

**Test:** Unit tests with a hand-built companyfacts dict: ancestry fields populated; a derived margin's `derivation` JSON re-resolves to its input facts; a margin with a missing input is not emitted; a huge value (e.g. 2,464,000,000,000) round-trips through save/load without precision loss.
**Commit:** `foundation: financial facts carry full XBRL ancestry and visible derivations`

---

### Brick 5 — `ExtractionRun` and `ExtractionGap`

**Goal:** Invariants 4 and 5. Absences become records; runs become identities.
**Read first:** `tearsheet/pipeline.py`, `tearsheet/store/models.py`, `tearsheet/store/repository.py`.
**Build:**

1. `ExtractionRun` model: `id`, `company_id` (FK), `extractor_version` (String — populate with `git rev-parse --short HEAD` at runtime, falling back to a package `__version__`), `started_at`, `finished_at`.
2. `ExtractionGap` model: `id`, `run_id` (FK), `filing_id` (FK), `target` (String — e.g. `"Item 7"`, `"us-gaap:Revenues FY2025"`), `status` (String enum: `not_present`, `not_found`, `rejected_by_gate`, `failed`), `detail` (Text).
3. Add `run_id` (FK, indexed) to `ExtractedSpan`, `FinancialFact`, and `Document`.
4. Pipeline: create the run at start, stamp `run_id` on everything saved, finalize `finished_at` at end. Convert every current silent/logged absence into a gap record: missing section (currently a `logger.warning` + `errors.append` around `pipeline.py:82`) → `not_found`; extractor exception → `failed`; every span rejected by grounding (currently only counted in a log line) → one `rejected_by_gate` gap carrying the rejected quote's first 200 chars in `detail`; each XBRL concept sought but absent → `not_found`. The `errors` list in the return dict now derives from gap records.

**Test:** Pipeline-level unit test with mocked EDGAR + mocked LLM: run against a fixture missing Item 7 and with one non-resolving quote; assert exactly the expected gap rows exist with correct statuses, and every saved artifact carries the run's id.
**Commit:** `foundation: extraction runs and typed gap records replace silent absences`

---

### Brick 6 — Numeric validators

**Goal:** The gate for numbers. Make the historical NVDA bugs (126% operating margin; ratio rows with missing inputs) structurally impossible.
**Read first:** `tearsheet/extract/financials.py` (post-Brick-4), `nvda_dossier.md` in the repo root (the artifact exhibiting the original bugs), `tearsheet/store/models.py`.
**Build:** New module `tearsheet/validate/financial.py` (new `validate/` package). Pure functions taking a list of `FinancialFact`-shaped inputs and returning a list of `ValidationFailure(target, rule, detail)` dataclasses. Rules:

1. **Margin bounds:** any fact whose concept/derivation marks it as a margin must lie in (-300%, 100%] — outside means an input misalignment, fail it.
2. **Derivation integrity:** every derived fact's inputs must exist in the fact set and the derivation must re-execute to the stored value (within a relative tolerance of 1e-6).
3. **Unit consistency:** all facts of one concept across periods share a unit.
4. **Period alignment:** within one `(fiscal_year, fiscal_period)`, income-statement facts must share the same underlying period end dates (catches the fiscal-alignment bug class addressed in commit `ae065ea`).
5. **Concept consistency:** where both are present, cross-statement identities hold (e.g. `NetIncomeLoss` consistent wherever it appears) within tolerance.

Failures do not raise — they return, so the caller (next brick) decides.
**Test:** This brick is test-heavy, deliberately. One test per rule proving it catches a synthetic bad input, one per rule proving it passes good input. Include a regression test reproducing each of the two known NVDA bug shapes and asserting the validator catches them.
**Commit:** `foundation: numeric validators — margins, derivations, units, periods, cross-statement consistency`

---

### Brick 7 — The Gate assembled: pipeline refuses unverifiable output

**Goal:** Restructure the pipeline into ACQUIRE → DERIVE → GATE → EMIT, where EMIT only happens after the gate.
**Read first:** `tearsheet/pipeline.py`, `tearsheet/validate/financial.py`, `tearsheet/extract/grounding.py`.
**Build:**

1. Refactor `run_for_ticker` into four private stage methods matching the names above (behavior-preserving where not specified).
2. GATE runs: (a) span gate — every `GroundedSpan` re-resolves exactly (exact string slice equality) against its `Document.text`, and the document's `text_sha256` re-verifies; (b) numeric validators from Brick 6 over all facts of the run.
3. Gate failures become `ExtractionGap(status=rejected_by_gate)` records and **the failing artifact is withheld from EMIT** — a fact failing margin-bounds is not saved as a fact; it's saved as a gap. Validation never silently repairs a value.
4. EMIT writes spans, facts, gaps atomically for the run and returns the run summary including a `gaps_count` and per-status breakdown.

**Test:** Pipeline test with mocked inputs engineered so one fact violates margin bounds and one span mismatches its hash: assert the bad fact and bad span are absent from saved output, present as gaps, and everything clean is saved. Full suite green.
**Commit:** `foundation: staged pipeline with gate — invalid artifacts become gaps, never output`

---

### Brick 8 — `tearsheet verify`, part 1: custody checks

**Goal:** The product feature begins — offline re-proof of hashes and spans.
**Read first:** `tearsheet/cli.py`, `tearsheet/store/repository.py`, all models.
**Build:** New module `tearsheet/verify/engine.py` + CLI command `tearsheet verify --ticker X` (match existing CLI conventions). Checks, run entirely offline from DB + archive directory:

1. Every `SourceDocument`: re-hash the archived file; compare to stored `sha256`. Missing file or mismatch = failure.
2. Every `Document`: recompute `text_sha256`.
3. Every `ExtractedSpan` citation and label: re-slice `Document.text[start:end]`, byte-compare to stored quote/label.

Produce a `VerificationReport` model (persisted: `run_id`, `passed` bool, `checks_total`, `failures` as JSON, `created_at`) and human-readable console output listing failures. Exit code nonzero on any failure.
**Test:** Build a tiny corpus via mocked pipeline into a temp dir; verify passes. Then corrupt one byte of one archived file → verify fails naming that file. Flip one offset in the DB → verify fails naming that span.
**Commit:** `foundation: verify command part 1 — offline custody checks for archives, text, and spans`

---

### Brick 9 — `tearsheet verify`, part 2: numeric re-proof + report

**Goal:** Complete verification: numbers re-derived, validators re-run, coverage reported.
**Read first:** `tearsheet/verify/engine.py`, `tearsheet/extract/financials.py`, `tearsheet/edgar/xbrl.py`.
**Build:** For this to work offline, the companyfacts JSON must be part of the archive: extend ACQUIRE (small addition to Brick 1's code) to save the raw companyfacts response to `{RAW_FILINGS_DIR}/{cik}/companyfacts.json` with its own `SourceDocument`-style hash record. Then add checks:

4. Every as-filed `FinancialFact`: re-locate in archived companyfacts by `(xbrl_concept, fiscal_year, fiscal_period, accession_number)`; compare `as_filed_value` exactly.
5. Every derived fact: re-execute `derivation` from its stored inputs; compare within tolerance.
6. Re-run all Brick 6 validators over the stored facts.
7. Coverage section in the report: from `ExtractionGap` — concepts/sections sought vs. found vs. rejected, itemized.

**Test:** Corrupt one value in archived companyfacts → check 4 fails. Tamper one stored derived value → check 5 fails. Clean corpus → full pass with coverage stats present.
**Commit:** `foundation: verify command part 2 — numeric re-proof and coverage reporting`

---

### Brick 10 — Golden fixture #1: NVDA, end to end

**Goal:** First real-world proof. This brick uses the network once, then pins everything.
**Read first:** `tests/` layout; `tearsheet/cli.py`.
**Build:** Run the real pipeline for NVDA (latest 10-K). Copy the archived accession + companyfacts into `tests/fixtures/golden/nvda/` (check sizes; if the repo shouldn't carry them, store hashes + a fetch script instead — decide based on size, document the choice). Write `tests/golden/test_nvda.py`: run the pipeline against the fixture (EDGAR client mocked to serve fixture files), then run verify programmatically, assert full pass. Create `tests/fixtures/golden/nvda/expectations.json` — hand-check against the actual filing at least: revenue, net income, operating margin for the latest FY, and the count of top-level sections found — and assert against it. **You must open the archived filing and confirm those numbers yourself before writing them into expectations; the expectations file is the human-verified anchor, so record in its header which document and page you checked.** Add the corruption test: flip one byte in a copy of the fixture archive → verify fails.
**Test:** The golden test itself, plus full suite.
**Commit:** `foundation: NVDA golden corpus — pipeline + verify pass against hand-checked expectations`

---

### Brick 11 — Golden fixtures #2–4: the hostile three

**Goal:** Prove generality and graceful failure.
**Build:** Same procedure as Brick 10 for: **a large bank** (JPM — expect non-standard concepts; extend the concept map only as needed, with validators still green), **a recent IPO** (pick one S-1→10-K graduate with sparse XBRL; expect gaps — the test asserts gaps are *typed and correct*, not absent), and **a foreign private issuer** (a 20-F filer — this one is *supposed to be out of scope*: the test asserts the pipeline declines cleanly with a typed gap/status, not a stack trace). Three sub-commits are acceptable here (one per company) if that keeps the ritual honest — treat each company as a mini-brick with its own test-then-commit cycle.
**Test:** Each company's golden test + full suite after each.
**Commit(s):** `foundation: golden corpus — JPM`, `... — <IPO ticker>`, `foundation: out-of-scope 20-F declines with typed gaps`

---

### Brick 12 — Sectioner-primary structure; LLM demoted to fallback

**Goal:** Determinism where achievable. The sectioner owns Item boundaries and sub-structure; the LLM survives only as a flagged locator fallback.
**Read first:** `tearsheet/parse/documents.py` (deeply), `tearsheet/extract/qualitative.py`, the archived NVDA/JPM filings' actual HTML.
**Build:**

1. Extend the sectioner to extract, deterministically from HTML structure: Item boundaries (already exists — harden it), sub-headings within Items, and for Item 1A each risk factor's bold/emphasized lead-in sentence as its `label` with real offsets. Emit `ExtractedSpan`s with `extraction_method="sectioner"` directly — no LLM involved.
2. The LLM locator path runs only for targets the sectioner could not structure, its spans marked `extraction_method="llm_locator"` (field exists since Brick 2/3 — ensure it's stamped on spans, adding the column to `ExtractedSpan` if you attached it only to `Document`).
3. Add a pipeline mode (env/flag) that disables the LLM entirely; the run must still produce a valid, verifiable corpus (fewer spans, correctly reported gaps).

**Test:** Sectioner unit tests on synthetic HTML covering: bold lead-ins, `<div>`-styled headings, and a pathological flat document (falls through to fallback). Golden tests updated: assert all top-level Items in NVDA/JPM extract with `extraction_method="sectioner"`. New test: LLM disabled → pipeline completes, verify passes.
**Commit:** `foundation: deterministic sectioner owns structure; LLM demoted to flagged locator fallback`

---

### Brick 13 — Coverage growth

**Goal:** The charter's full concept list inside the now-fixed architecture.
**Read first:** `tearsheet/extract/financials.py`, current concept list.
**Build:** Extend extraction to: shares outstanding, EPS (basic + diluted), dividends, buybacks, fuller balance sheet (current/total assets & liabilities, equity, cash, debt), fuller cash flow (operating/investing/financing, capex, FCF as a *derived* fact), and XBRL-tagged segment/geographic revenue (these are dimensional — extend the model minimally with a nullable `dimension` JSON column on `FinancialFact` if needed). Every new concept: ancestry populated, validators apply, absence → typed gap. Update writer tables. Update golden expectations files (re-hand-check the new numbers against the filings, same discipline as Brick 10).
**Test:** Unit tests for each new concept family with synthetic companyfacts; golden tests re-verified for all fixtures.
**Commit:** `foundation: full retail-diligence concept coverage with ancestry and validation`

---

### Brick 14 — Final acceptance: the stranger test

**Goal:** Prove the definition of done.
**Build:** Nothing new — this brick is pure verification. On a machine state with **network access disabled** (unset any API keys, block or mock the HTTP client), starting from only the repo + one golden corpus directory + its SQLite DB: run `tearsheet verify` for each of the three in-scope golden companies. All must pass. Then run the full test suite one final time. Write `docs/foundation-acceptance.md` recording: the verify output for each company, the extractor version, the date, and a one-paragraph statement that the five invariants hold and where each is enforced in code.
**Test:** Everything, offline.
**Commit:** `foundation: acceptance — corpus self-verifies offline; foundation complete`

---

## Part IV — What you must never do at any point

- Never store a string an LLM generated (invariant 1 — grep for it before every commit that touches `extract/`).
- Never let a validator "fix" a value; validators only reject into gaps.
- Never weaken, skip, or delete a failing test to get to a commit. Stop and report instead.
- Never add filing types (10-Q, 8-K, proxies), multi-year history, or any interpretation/summarization feature — all explicitly out of scope for the foundation.
- Never merge bricks. One brick, one green suite, one commit.

Finished means: Brick 14's document exists, and a stranger with no network, given one company's corpus, can run one command and confirm every statement in it is exactly what the company filed.
