# Tearsheet — Option B: XBRL Financial Extraction Specification

**Status:** Approved blueprint — ready for scaffolding.
**Scope:** Populate `FinancialFact` from SEC XBRL companyfacts (Item 8 financials), deterministically, with no LLM in the path.
**Role of this document:** Architecture + execution contract handed to the coding agent. It is the source of truth for the scaffolding phase.

**Approved decisions baked into this spec:**
1. The pipeline (`run_for_ticker`) return signature changes to a **structured dictionary execution summary** (see §5).
2. The curated financial concept whitelist in §2.1 is **locked**.

---

## 1. Audit — Current State

The financial layer is **partially scaffolded, not flowing.** No financial fact has ever reached the store. The two hard deterministic halves (fetch + idempotent persistence) are already built and tested; the gap is concentrated in one function plus orchestration wiring.

| Stage | File | Status | Evidence |
|---|---|---|---|
| **Fetch** | `edgar/xbrl.py` → `fetch_companyfacts(cik)` | Built & tested | Hits `data.sec.gov/api/xbrl/companyfacts/CIK{10-digit}.json`; covered by `tests/edgar/test_xbrl.py` |
| **Parse** | `extract/financials.py` → `extract_financial_facts(company_id, companyfacts)` | **STUB** | Body is `raise NotImplementedError` |
| **Model** | `store/models.py` → `FinancialFact` | Built | Unique `(company_id, concept, period_end)`; `period_end` non-null with `default=date(1970,1,1)` sentinel baked in |
| **Persist** | `store/repository.py` → `save_financial_facts(facts)` | Built & tested | Atomic `on_conflict_do_update`, coerces missing date via `p_end = f.period_end or date(1970,1,1)`; covered by `test_save_financial_facts*` |
| **Orchestrate** | `pipeline.py` → `ExecutionPipeline.run_for_ticker` | **Not wired** | Resolves CIK → history → 10-K → parse → Item 1A qualitative only. Never calls `fetch_companyfacts`, `extract_financial_facts`, or `save_financial_facts` |
| **Test** | `tests/extract/test_financials.py` | **Absent** | No such file exists |

**Verdict:** Item 8 / XBRL financials do not populate `FinancialFact`. The remaining work is one parser, one pipeline edit, and one test file. The NULL-trap sentinel is already solved twice over (model default + repository coercion), so the parser must not invent dates — it leaves `period_end` unset and the persistence layer handles it.

---

## 2. Data-Flow Design (the missing parser)

No LLM anywhere in this path — pure dict traversal.

```
cik ──fetch_companyfacts──▶ companyfacts JSON
                              │
                              ▼
              facts["us-gaap"][CONCEPT]["units"][UNIT] = [ datapoint, ... ]
                              │
              extract_financial_facts(company_id, companyfacts)
                 • walk a CURATED concept whitelist (not all ~hundreds of tags)
                 • keep annual datapoints only (form=="10-K" or fp=="FY")
                 • newest-filed wins per (concept, period_end)
                              │
                              ▼
              list[FinancialFact]  ──save_financial_facts──▶ SQLite
```

**The companyfacts shape** (relevant slice):

```json
{
  "facts": {
    "us-gaap": {
      "NetIncomeLoss": {
        "label": "Net Income (Loss)",
        "units": {
          "USD": [
            {"start":"2022-09-25","end":"2023-09-30","val":96995000000,
             "fy":2023,"fp":"FY","form":"10-K","filed":"2023-11-03","frame":"CY2023"}
          ]
        }
      }
    }
  }
}
```

### 2.1 Locked concept whitelist (the dossier's financial spine)

Define as a module-level constant in `extract/financials.py`. Absent tags are skipped silently.

- `Revenues`
- `RevenueFromContractWithCustomerExcludingAssessedTax`  *(revenue tag varies by filer — include both)*
- `GrossProfit`
- `OperatingIncomeLoss`
- `NetIncomeLoss`
- `Assets`
- `Liabilities`
- `StockholdersEquity`
- `CashAndCashEquivalentsAtCarryingValue`
- `NetCashProvidedByUsedInOperatingActivities`
- `PaymentsToAcquirePropertyPlantAndEquipment`  *(capex)*
- `LongTermDebtNoncurrent`

### 2.2 Parser design rules

1. **Curated whitelist, not firehose.** Companyfacts carries hundreds of tags; extract only the fixed spine above so the store holds a clean, reviewable series.
2. **Annual only.** Each datapoint list mixes quarterly + annual + restated history. Filter to `form == "10-K"` (or `fp == "FY"`) so the store holds year-over-year series, not Q-noise.
3. **Newest-filed wins.** A given `(concept, period_end)` recurs across filings (originals + restatements). Sort datapoints by `filed` ascending and let the repository's idempotent upsert overwrite — the last write is the most recently restated value.
4. **Concept tag drift is expected.** Revenue especially is `Revenues` for some filers and `RevenueFromContractWithCustomerExcludingAssessedTax` for others. Both are whitelisted; absent tags are skipped. Guard every dict access — never assume a concept or unit key exists.

---

## 3. Database Schema Mapping

`us-gaap[concept]["units"][unit][i]` datapoint → `FinancialFact` row:

| Source (companyfacts) | → | `FinancialFact` field | Notes |
|---|---|---|---|
| concept key (e.g. `"NetIncomeLoss"`) | → | `concept` | The us-gaap tag verbatim |
| `us-gaap[concept]["label"]` | → | `label` | Human-readable; nullable |
| unit key (e.g. `"USD"`, `"shares"`) | → | `unit` | From the `units` dict key, not the datapoint |
| `datapoint["val"]` | → | `value` | `Float`, nullable |
| `datapoint["end"]` (parsed `date.fromisoformat`) | → | `period_end` | See sentinel rule below |
| *(constructor arg)* | → | `company_id` | Passed into `extract_financial_facts` |
| auto | → | `id`, `created_at` | DB-assigned |

### 3.1 `period_end` handling — the SQLite NULL trap (already mitigated, do not re-solve)

- Every real companyfacts datapoint has an `"end"`, so `period_end` is normally populated from `datapoint["end"]`.
- The danger is a malformed/missing `end`. **The parser must NOT manufacture `1970-01-01` itself.** Instead, leave `period_end=None` (or omit it) when `end` is absent or unparseable. Two existing layers catch it:
  - `repository.save_financial_facts` coerces `f.period_end or date(1970,1,1)`,
  - and `FinancialFact.period_end` carries `default=date(1970,1,1)`.
- This preserves the unique constraint `(company_id, concept, period_end)` — `NULL != NULL` can never silently duplicate, because by persist time the value is a concrete sentinel date. `test_save_financial_facts_null_dedupe` already proves this round-trips and de-dupes.
- **Contract to keep intact:** the parser owns "real date or `None`," the store owns "`None` → sentinel."

---

## 4. Execution Task List (hand-off to coding agent)

> Scope: implement `extract_financial_facts`, wire it into the pipeline, and test it. Do **not** touch `models.py`, `repository.py`, or the sentinel mechanics — they are load-bearing and already correct. All network I/O stays mocked (token-free, offline test suite).

### A. Parsing — `extract/financials.py`
- [ ] Add module-level `FINANCIAL_CONCEPTS` whitelist (§2.1), including both revenue tag variants.
- [ ] Implement `extract_financial_facts(company_id, companyfacts)`:
  - [ ] Safely descend `companyfacts.get("facts", {}).get("us-gaap", {})`; return `[]` if absent.
  - [ ] For each whitelisted concept present: iterate its `units` dict (capture the unit key).
  - [ ] Filter datapoints to annual (`form == "10-K"` or `fp == "FY"`).
  - [ ] Parse `end` via `date.fromisoformat`; on missing/invalid, set `period_end=None` (let the store apply the sentinel — do **not** hardcode 1970 here).
  - [ ] Sort by `filed` ascending so newest restatement wins on upsert.
  - [ ] Build `FinancialFact(company_id=…, concept=…, label=…, unit=…, value=…, period_end=…)`; guard every dict access.
  - [ ] Return `list[FinancialFact]`.

### B. Fetch wiring (already built — just confirm)
- [ ] Confirm `edgar/xbrl.fetch_companyfacts` is the single fetch entry point; no changes expected.

### C. Repository inserts (already built — do not modify)
- [ ] Confirm `save_financial_facts` is the persistence call; rely on its existing upsert + sentinel coercion.

### D. Pipeline integration — `pipeline.py`
- [ ] In `run_for_ticker`, after `upsert_company` (so `company.id` exists) add a financial branch:
  - [ ] `companyfacts = fetch_companyfacts(cik)`
  - [ ] `fin_facts = extract_financial_facts(company.id, companyfacts)`
  - [ ] `self.repo.save_financial_facts(fin_facts)`
  - [ ] Log the count; **isolate failures** so a financials hiccup doesn't abort the qualitative path (wrap in try/except + log, matching the existing logging style).
- [ ] Change the return value to the structured execution summary (§5).
- [ ] Add the two new imports (`fetch_companyfacts`, `extract_financial_facts`).

### E. Integration testing — `tests/extract/test_financials.py` (new) + pipeline test update
- [ ] Build a small fixture companyfacts dict: 2–3 concepts, one with two `units`, a mix of `10-K`/`10-Q` datapoints, one restated `(concept, period_end)` pair, and one datapoint with a missing `end`.
- [ ] Assert: only annual datapoints survive; concept/label/unit/value map correctly; the missing-`end` row yields `period_end=None` pre-persist; the restated pair resolves to the newest-filed value.
- [ ] Round-trip test through `save_financial_facts` (reuse the in-memory `sqlite:///:memory:` autouse fixture pattern from `tests/store/test_repository.py`) — assert the missing-`end` row lands as `date(1970,1,1)` and de-dupes.
- [ ] Update `tests/test_pipeline.py`: patch `fetch_companyfacts` + `extract_financial_facts`, assert `save_financial_facts` is invoked with `company.id`, assert a financials failure does **not** break the qualitative run, and assert the new dictionary return contract (§5).
- [ ] Run full suite — expect the current count **+** the new financial tests, all green, zero network calls.

---

## 5. Pipeline Return Signature — Structured Execution Summary (APPROVED)

`run_for_ticker` no longer returns a bare `list[QualitativeFact]`. It returns a structured dictionary summarizing the run, so financial and qualitative results are both visible to callers (and to the future dossier writer) without a signature break each time a stage is added.

**Shape:**

```python
{
    "ticker": str,                       # e.g. "MSFT"
    "cik": str,                          # 10-digit
    "company_id": int,
    "accession_number": str,
    "financial_facts": list[FinancialFact],     # persisted financial rows
    "qualitative_facts": list[QualitativeFact], # persisted qualitative rows (Item 1A)
    "errors": list[str],                 # isolated stage failures, e.g. financials hiccup
}
```

**Contract notes:**
- Both fact lists are the **persisted** objects returned by the repository (eager-loaded), not the pre-save candidates.
- `errors` is empty on a fully clean run. A failure in the financial branch appends a message here rather than raising — the qualitative path must still complete and its facts must still appear.
- Callers that previously consumed the bare list must read `result["qualitative_facts"]`. Update `cli.py` accordingly during scaffolding (call this out — it is a downstream consumer of the changed signature).

---

## 6. Open Items for the Scaffolding Phase
- `cli.py` consumes `run_for_ticker`'s old return value; it must be updated to the dictionary contract (§5) when scaffolding lands.
- The `FINANCIAL_CONCEPTS` whitelist is locked for v1 but is a product surface — future dossier sections may extend it; keep it in one editable constant.
```
