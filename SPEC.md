# Show Me The Money — Constraint Cost Tracker: Implementation Spec

**Status:** v1.3. M0–M7 implemented and green. All API endpoints verified live on 2026-07-19. No API keys required. No blockers. Amendment §10 (full history + live provisional today) adds milestone M8 — implement it next.

**Audience:** an autonomous coding agent (Codex) implementing this end-to-end. Every task has acceptance criteria and a verification command. When in doubt, follow this spec literally; record any forced deviation in `METHODOLOGY.md` under "Deviations".

---

## 1. What we are building

A public tracker of Great Britain's grid **constraint costs**, built on Elexon Balancing Mechanism settlement data.

- **Phase A — Replication engine:** reproduce the daily/monthly figures published by wastedwind.energy, as a validation harness. We have decompiled the site's exact client-side methodology (§4) — replication means implementing that algorithm faithfully, then comparing our monthly aggregates against the site's own summary API (§6). Target: within ±2% on monthly figures (we run the *same algorithm on the same data*, so deviation should be near zero; tolerance covers data revisions).
- **Phase B — Follow the money:** attribute the **turn-up** side (payments to generators, mostly gas, for replacing curtailed wind) to stations and parent companies. Output: "who got paid" league tables per day/month/year.
- **Phase C (out of scope here):** public site. The engine must export tidy JSON per day (§8) that a static site can consume later. Hosting will be Cloudflare R2 + Pages; the pipeline runs as a scheduled batch job (GitHub Actions). Do not build the site.

### The story in one paragraph (mental model)

GB's wind is concentrated in Scotland; transmission boundaries can't always carry it south. When a boundary binds, NESO uses the Balancing Mechanism to pay wind farms to **stop** generating (accepted *bids* at negative prices — the farm loses subsidy so it charges to turn down) and simultaneously pays generators south of the constraint (mostly CCGT gas) to **start** (accepted *offers* at positive prices). Consumers pay both sides via BSUoS. One curtailed MWh is therefore paid for twice. `soFlag` on an action marks it as "potentially taken for reasons other than energy balancing" — i.e. a constraint action.

---

## 2. Tech stack & repo layout (fixed decisions — do not relitigate)

- Python **3.12**, package manager **uv** (`uv init`, `uv add`), single package `tracker`.
- HTTP: **httpx** (sync client). Validation: **pydantic v2**. Store: **DuckDB** (single file `data/tracker.duckdb`). CLI: **typer**. Tests: **pytest**.
- Raw API responses cached as JSON files under `raw/` — the cache is the source of truth for re-computation; never re-hit the API for data already on disk (except explicit `--refresh`).
- Lint/format: **ruff** (`ruff check`, `ruff format`). Type check: **mypy** (non-strict is acceptable).
- **Purity rule:** `wastedwind.py` and `turnup.py` contain pure calculation functions only (data in, results out, no I/O, no clock reads). All other modules may perform I/O appropriate to their role (HTTP in `api.py`; DB in `store.py`; files in `export.py`, `owners.py`, `reference.py`; orchestration in `ingest.py`, `validate.py`, `cli.py`).

```
show-me-the-money/
├── SPEC.md                  # this file
├── AGENTS.md                # agent operating instructions
├── METHODOLOGY.md           # every calculation choice + divergences (agent maintains)
├── PROGRESS.md              # agent maintains (see AGENTS.md)
├── pyproject.toml
├── src/tracker/
│   ├── __init__.py
│   ├── config.py            # constants: BASE_URL, EARLIEST_DATE, throttle params
│   ├── api.py               # Elexon client: throttle, retry, disk cache
│   ├── models.py            # pydantic models (§3 shapes)
│   ├── store.py             # DuckDB schema + load/query
│   ├── ingest.py            # per-date ingestion + compute orchestration
│   ├── wastedwind.py        # replication algorithm (§4) — pure functions
│   ├── turnup.py            # Phase B attribution calc — pure functions
│   ├── reference.py         # BMU reference data + fuel typing
│   ├── owners.py            # station → parent company mapping
│   ├── validate.py          # comparison vs wastedwind summary API (§6)
│   ├── export.py            # per-day JSON export (§8)
│   └── cli.py               # typer app, entry point `tracker`
├── data/
│   └── owners.csv           # seeded from §7.1 table
├── validation/
│   └── waivers.yml          # explicit validation waivers (§5 M4); starts empty
├── raw/                     # cached API JSON (gitignored)
├── out/                     # exported JSON (gitignored)
└── tests/
    ├── fixtures/            # small JSON fixtures cut from real responses
    └── test_*.py
```

`.gitignore`: `raw/`, `out/`, `data/*.duckdb`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`.

`config.py` constants: `BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"`, `WASTEDWIND_BASE = "https://wastedwind.energy"`, `EARLIEST_DATE = date(2026, 1, 1)`, `MIN_ATTEMPT_INTERVAL_S = 0.25`, `MAX_RETRIES = 3`. All CLI commands reject dates before `EARLIEST_DATE` with a clear error (tested).

**Date bounds (Europe/London):** "today" always means the current Europe/London date. `ingest`/`fetch` accept dates in `[EARLIEST_DATE, today−1]`; `validate` only considers dates ≤ `today−2` (data too fresh otherwise). Future or too-fresh dates are rejected with an error **before** any HTTP request — future dates must never be requested or cached.

---

## 3. Verified API reference (tested live 2026-07-19; no key, no auth)

Base: `https://data.elexon.co.uk/bmrs/api/v1`

### 3.0 Client behaviour (applies to every request)

- **Pacing:** a single process-wide lock enforces ≥ `MIN_ATTEMPT_INTERVAL_S` (0.25 s) between the *starts of consecutive HTTP attempts, including retries*. This guarantees ≤ 4 requests in any rolling second. No burst allowance.
- **Retries:** up to 3 retries (4 attempts total) on: HTTP 5xx, HTTP 429, timeouts, connection errors. Backoff before retry n = 1 s, 2 s, 4 s; for 429, sleep `max(backoff, Retry-After header)` if the header is present. 4xx other than 429 is not retried.
- **404 on settlement-stack and BOAV/EBOCF period endpoints is normal** (period doesn't exist that day): treat as empty (`{"data": []}`) and cache that. 404 elsewhere is an error.
- **Disk cache:** canonical cache key = `{host}{path}?{query params sorted by key, k=v joined with &}`. File path: `raw/{host}/{path with "/" → "__"}{"?" + sorted query if any, with "/" and ":" percent-encoded}.json`; if the resulting filename exceeds 180 chars, replace it with `sha256(canonical_key).hexdigest() + ".json"` in the same directory. Writes are atomic (write `*.tmp`, then `os.replace`). A cache hit makes zero HTTP attempts. `refresh=True` bypasses the cache for reads and overwrites it on success (never deletes on failure).
- **Named cache-path exceptions** (override the canonical rule, same atomic-write semantics): BMU reference → `raw/reference/bmunits.json`; wastedwind summary → `raw/wastedwind/summary-{year}-{today}.json` (the response changes over time, so the key includes the **fetch date**; a same-day file is a hit, otherwise fetch).

### 3.1 Settlement stack — THE primary dataset (both phases)

```
GET /balancing/settlement/stack/all/bid/{settlementDate}/{settlementPeriod}
GET /balancing/settlement/stack/all/offer/{settlementDate}/{settlementPeriod}
```
- `settlementDate` = `YYYY-MM-DD` (a **Europe/London calendar day** — no timezone conversion needed).
- `settlementPeriod` = 1..50. Normal days have 48 periods; clock-change days 46 or 50. **Always request 1..50** and accept 404s (this is what wastedwind does).
- Response: `{"data": [ ... ]}` — one element per (acceptance × bid-offer pair) settlement line. Verified element shape:

```json
{
  "settlementDate": "2026-07-10", "settlementPeriod": 20,
  "startTime": "2026-07-10T08:30:00Z", "createdDateTime": "2026-07-11T09:14:32Z",
  "sequenceNumber": 1, "id": "E_LITRB-1", "acceptanceId": 49242,
  "bidOfferPairId": 1, "cadlFlag": false, "soFlag": false,
  "storProviderFlag": false, "repricedIndicator": false,
  "reserveScarcityPrice": 0.0, "originalPrice": 90.25,
  "volume": -0.004166666666666667, "dmatAdjustedVolume": 0.0,
  "arbitrageAdjustedVolume": null, "nivAdjustedVolume": null,
  "parAdjustedVolume": null, "finalPrice": 90.25,
  "transmissionLossMultiplier": 0.977241,
  "tlmAdjustedVolume": null, "tlmAdjustedCost": null
}
```
- `id` is the **Elexon BMU id** (joins to `elexonBmUnit` in reference data). Bid volumes are negative (MWh); offer volumes positive. `cadlFlag` may be `null` on offers — treat `null` as `false`. Prices are £/MWh.
- This dataset is settlement-derived: acceptance supersession, deduplication, and volume integration are **already done by Elexon**. We do NOT reimplement them.

**`StackItem` pydantic model** (`extra="ignore"`): `settlementDate: date`, `settlementPeriod: int`, `startTime: datetime`, `sequenceNumber: int`, `id: str`, `acceptanceId: int`, `bidOfferPairId: int`, `cadlFlag: bool | None`, `soFlag: bool`, `originalPrice: float`, `finalPrice: float | None`, `volume: float`, `transmissionLossMultiplier: float | None`, `createdDateTime: datetime | None`, `storProviderFlag: bool | None`, `repricedIndicator: bool | None`, `reserveScarcityPrice: float | None`, `dmatAdjustedVolume: float | None`, `arbitrageAdjustedVolume: float | None`, `nivAdjustedVolume: float | None`, `parAdjustedVolume: float | None`, `tlmAdjustedVolume: float | None`, `tlmAdjustedCost: float | None`. (Fields after `transmissionLossMultiplier` are stored but unused in calculations.)

### 3.2 BMU reference data

```
GET /reference/bmunits/all
```
Returns a **bare JSON array** (no `data` wrapper). **`BmuRef` model** (`extra="ignore"`): `elexonBmUnit: str`, `nationalGridBmUnit: str | None`, `bmUnitName: str | None`, `leadPartyName: str | None`, `leadPartyId: str | None`, `fuelType: str | None` (observed values include `"WIND"`, `"CCGT"`, `"OCGT"`, `"PS"`, `"NPSHYD"`, `"BIOMASS"`, `"OTHER"`, `null`), `generationCapacity: str | None`, `bmUnitType: str | None`, `interconnectorId: str | None`, `gspGroupId: str | None`. Fetch once, cache to `raw/reference/bmunits.json`, refresh only on `--refresh-reference`.

### 3.3 Cross-check datasets (Milestone 6 only)

**BOAV** — `GET /balancing/settlement/acceptance/volumes/all/{bid|offer}/{date}/{period}` → `{"data": [...]}`, element:
```json
{"createdDateTime": "...", "settlementDate": "2026-07-10", "settlementPeriod": 20,
 "startTime": "...", "bmUnit": "2__ASTAT009", "bmUnitType": "S",
 "leadPartyName": "...", "nationalGridBmUnit": "AG-ASTK09", "acceptanceId": 11686,
 "acceptanceDuration": "L", "totalVolumeAccepted": 0.0,
 "pairVolumes": {"negative1": 0.0, "positive1": 0.0, "...": "negative1..negative6, positive1..positive6, later pairs may be null"}}
```

**EBOCF** — `GET /balancing/settlement/indicative/cashflows/all/{bid|offer}/{date}/{period}` → `{"data": [...]}`, element:
```json
{"settlementDate": "2026-07-10", "settlementPeriod": 20, "startTime": "...",
 "createdDateTime": "...", "bmUnit": "2__ASTAT009", "bmUnitType": "S",
 "leadPartyName": "...", "nationalGridBmUnit": "AG-ASTK09",
 "bidOfferPairCashflows": {"negative1": 0.0, "positive1": 0.0, "...": "negative1..6 / positive1..6, may be null"},
 "totalCashflow": 0.0}
```
Note: `bmUnit` here is the **Elexon** BMU id (joins `elexonBmUnit`).

**MID** — `GET /datasets/MID?from=YYYY-MM-DD&to=YYYY-MM-DD` (from/to inclusive; optional `settlementPeriodFrom/To`) → `{"data": [...]}`, element:
```json
{"dataset": "MID", "startTime": "2026-07-10T08:30:00Z", "dataProvider": "APXMIDP",
 "settlementDate": "2026-07-10", "settlementPeriod": 20, "price": 116.79, "volume": 2410.25}
```
Use only `dataProvider == "APXMIDP"` rows (N2EXMIDP rows are zero). Join to our data on `(settlementDate, settlementPeriod)`.

**BOALF** (acceptance metadata, not needed for any calculation) — `GET /balancing/acceptances/all?settlementDate=YYYY-MM-DD&settlementPeriod=N`. **BOD** (submitted ladders) — `GET /datasets/BOD?from=ISO&to=ISO&bmUnit=X` (from/to, NOT settlementDate — settlementDate 404s).

### 3.4 Validation source — wastedwind.energy summary API

```
GET https://wastedwind.energy/api/summary/{year}     e.g. /api/summary/2026
```
Verified response shape:
```json
{"total": {"bidCost": 169034194.69, "offerCost": 764032104.47, "totalCost": 933066299.16, "volume": 6143472.93},
 "data": [{"year": 2026, "month": 7, "bidVolumeMWh": 360996.50, "bidVolumeGWh": 360.99,
           "bidCost": 13746022.75, "bidCostM": 13.75, "turnUpVolume": 348067.73,
           "turnUpVolumeGWh": 348.07, "turnUpCost": 49897452.53, "turnUpCostM": 49.90}]}
```
One `data` element per month, **current month included and partial** (rolling). `bidCost` = curtailment £, `turnUpCost` = replacement £. Models (all `extra="ignore"`): `WastedWindTotal` (`bidCost: float, offerCost: float, totalCost: float, volume: float`), `WastedWindMonth` (`year: int, month: int, bidVolumeMWh: float, bidCost: float, turnUpVolume: float, turnUpCost: float`), `WastedWindSummary` (`total: WastedWindTotal, data: list[WastedWindMonth]`). **No HTML scraping anywhere** (the site is client-rendered; scraping was never viable).

Note: the summary reflects whatever data revisions existed when the site's cron computed it; small drift vs a fresh computation is expected and is why the tolerance is ±2%, not 0.

---

## 4. The replication algorithm (decompiled from wastedwind.energy's JS bundle, 2026-07-19)

This is the site's exact client-side computation, reverse-engineered from `https://wastedwind.energy/_next/static/chunks/2615710fa70e8583.js` (prettified). Implement it **verbatim** as pure functions in `wastedwind.py`. Any deviation must be a named, documented choice in `METHODOLOGY.md`.

For a settlement date `D`:

**Step 1 — fetch.** Get bid stack and offer stack for periods 1..50 (404 ⇒ empty list). Flatten each into one list for the day, **preserving (period, response-order)**.

**Step 2 — enrich.** For every stack item, look up `fuelType` by matching `item.id` to reference `elexonBmUnit`. Unknown id ⇒ `fuelType = None`. (The site uses a *bundled static* BMU list; we use live reference data — divergence risk is negligible but note it in METHODOLOGY.md.)

**Step 3 — curtailment (wind side).** Over the day's **bid** stack:
```
wind_bids              = [b for b in bids if b.fuelType == "WIND" and b.soFlag]
curtailment_volume_mwh = sum(b.volume for b in wind_bids)          # negative
curtailment_cost_gbp   = sum(b.originalPrice * b.volume for b in wind_bids)
                         # negative price × negative volume ⇒ positive £
```
Report volume as `abs(...)`. Uses `originalPrice` and `volume` — NOT finalPrice, NOT TLM-adjusted fields.

**Step 4 — turn-up (replacement side).** Per settlement period `p` where wind was curtailed (`period_curtailed[p] = sum of wind_bid volumes in p`, nonzero):
1. Candidate offers = all offer-stack items in `p` with `not cadlFlag` (treat `cadlFlag null/None` as False ⇒ candidate). **All fuel types, both SO and non-SO.**
2. Sort candidates: non-SO-flagged first, then by ascending `sequenceNumber`. The sort MUST be **stable**; items tying on `(soFlag, sequenceNumber)` retain their original flattened-response order. (Python's `sorted` with `key=lambda o: (o.soFlag, o.sequenceNumber)` satisfies this.)
3. Walk the sorted list, consuming `offer.volume` until cumulative volume ≥ `abs(period_curtailed[p])`. The final item is **pro-rated**: consume fraction `clamp((target − consumed_so_far) / item.volume, 0, 1)` of it. If candidates are exhausted before reaching the target (including the empty-stack case), turn-up covers only what was consumed — no error, no extrapolation.
4. `turnup_cost[p] = Σ originalPrice × consumed_volume`; `turnup_volume[p] = Σ consumed_volume`.

**Step 5 — daily totals.**
```
turnup_cost   = Σ_p turnup_cost[p]
turnup_volume = Σ_p turnup_volume[p]
total_cost    = curtailment_cost + turnup_cost
```

**Result contracts** (frozen dataclasses or pydantic models; all floats in £ / MWh):
- `CurtailmentResult`: `cost_gbp: float` (≥0 in practice, signed sum as computed), `volume_mwh: float` (**reported positive**, i.e. `abs`), `period_curtailed: dict[int, float]` (signed, negative, keyed by settlement period; zero-sum periods omitted).
- `TurnupResult`: `cost_gbp: float`, `volume_mwh: float` (positive), `per_period: dict[int, tuple[float, float]]` (cost, volume).
- `DayResult`: `date: date`, `curtailment: CurtailmentResult`, `turnup: TurnupResult`, `total_cost_gbp: float`.

Monthly aggregates = sum of daily values over the month. Mapping to summary API fields: `bidCost`↔`curtailment.cost_gbp`, `bidVolumeMWh`↔`curtailment.volume_mwh`, `turnUpCost`↔`turnup.cost_gbp`, `turnUpVolume`↔`turnup.volume_mwh`.

Semantics note for METHODOLOGY.md: this "turn-up cost" is *"what was actually paid, in offer-stack order, for the volume equal to the curtailed volume"* — a replacement-cost estimate, not the sum of SO-flagged offer cashflows. Phase B computes the SO-flagged-offer view separately (§5 M5); the two measures are named `replacement_cost` and `so_flagged_payments` respectively and must never be conflated (§8).

---

## 5. Milestones & tasks

Work strictly in order (M6 has an explicit skip policy). Per-task and per-milestone verification gates are defined in AGENTS.md. Commit per task with descriptive messages.

### Milestone 0 — Scaffold
- `uv init`, add deps (`httpx pydantic typer duckdb` + dev `pytest ruff mypy`), create package layout incl. `config.py` constants (§2), `.gitignore`, `METHODOLOGY.md` with a header + empty "Deviations" and "Validation results" sections, empty `validation/waivers.yml` (`waivers: []`).
- One smoke test so pytest collects ≥1 test: `tests/test_cli.py` invoking `tracker --help` via `typer.testing.CliRunner`, asserting exit 0.
- **Accept:** `uv run tracker --help` exits 0; `uv run pytest` exits 0; `uv run ruff check .` clean.

### Milestone 1 — API client + raw cache
- `api.py`: `ElexonClient` implementing §3.0 exactly (pacing incl. retries, retry policy incl. 429/Retry-After, atomic cache writes, canonical cache keys, stack-404-as-empty). Constructor takes `cache_dir: Path` and optional `transport` (for httpx MockTransport in tests).
- Methods: `bid_stack(date, period, refresh=False)`, `offer_stack(date, period, refresh=False)`, `bmunits(refresh=False)`, `wastedwind_summary(year)` — these return parsed pydantic models (`list[StackItem]`, `list[BmuRef]`, `WastedWindSummary`). Generic `get(path, params, refresh=False)` returns **decoded JSON** (`dict | list`) and is the raw layer the typed wrappers (and M6's EBOCF/MID/BOAV calls) sit on.
- `models.py`: `StackItem`, `BmuRef`, `WastedWindMonth`, `WastedWindSummary` per §3 with `model_config = ConfigDict(extra="ignore")`.
- CLI: `tracker fetch --date 2026-07-10` pulls both stacks for periods 1..50 into `raw/` (100 requests worst case).
- Tests (`test_api.py`, mock transport + `tmp_path` cache dir, no live calls): first pass over a mocked date makes exactly 100 requests; second pass with the same client+cache makes exactly 0 (count via the mock transport); 404 stack response cached as empty and parsed as `[]`; 429 with `Retry-After: 1` retried; ≥0.25 s spacing enforced between attempt timestamps (record attempt times in the mock; allow generous upper bounds so the test isn't flaky); cache filenames deterministic for permuted param order.
- **Accept:** `uv run pytest tests/test_api.py` passes; live smoke: `uv run tracker fetch --date 2026-07-10` exits 0 and populates `raw/`.

### Milestone 2 — Replication core (`wastedwind.py`)
- Pure functions: `daily_curtailment(bid_items, fuel_lookup) -> CurtailmentResult`, `daily_turnup(offer_items, period_curtailed) -> TurnupResult`, `compute_day(date, bid_items, offer_items, fuel_lookup) -> DayResult` implementing §4 exactly.
- Unit tests with hand-built fixtures, one named test per edge case: wind+soFlag filtering (non-wind and non-SO excluded); negative×negative ⇒ positive cost; turn-up sort order (non-SO before SO, then sequenceNumber); **stable tie order** (two offers with equal soFlag+sequenceNumber, different prices — assert original order consumed); pro-rating of final offer (exact-boundary and overshoot cases); **partial coverage** (nonempty offers summing to less than the curtailed target — turn-up equals what was consumable); zero-curtailment day ⇒ zero turn-up; `cadlFlag None` treated as False; curtailed period with empty offer stack.
- **Accept:** `uv run pytest tests/test_wastedwind.py` passes with every listed case present by name.

### Milestone 3 — Store + ingest + daily compute
- `store.py`: DuckDB tables:
  - `stack_items` (all §3.1 model fields + `flow` TEXT 'bid'|'offer'; PK `(settlementDate, settlementPeriod, flow, id, acceptanceId, bidOfferPairId, sequenceNumber)`),
  - `bmu_ref` (all §3.2 model fields, PK `elexonBmUnit`),
  - `daily_results` (`date` PK, `curtailment_cost, curtailment_volume, turnup_cost, turnup_volume, total_cost` DOUBLE, `computed_at` TIMESTAMP).
  - Per-date replace is transactional: `BEGIN; DELETE ... WHERE settlementDate = ?; INSERT ...; COMMIT;`.
- CLI date arguments: every ingest-family command takes **exactly one of** `--date D` **or** `--from A --to B` (both required together, inclusive range, `A ≤ B`); anything else is a usage error. Dates outside `[EARLIEST_DATE, today−1]` (Europe/London) → error before any HTTP. Exception: `tracker ingest --refresh-reference` with **no** date arguments is valid and refreshes only the BMU reference.
- `tracker ingest`: fetch (cache-aware) → upsert `stack_items` → compute §4 → upsert `daily_results`. Flags: `--refresh` (bypass+overwrite raw cache for the requested dates), `--refresh-reference` (refetch BMU reference).
- `tracker show --date D` prints the day's `daily_results` row.
- **Idempotency definition:** re-running `ingest` for a date without `--refresh` must reproduce byte-identical values for the five calculated columns and identical `stack_items` row counts; `computed_at` is excluded from the comparison.
- **Accept:** `uv run tracker ingest --date 2026-07-10 && uv run tracker show --date 2026-07-10` prints nonzero curtailment; running ingest twice and diffing the five values proves idempotency (make this a test using cached fixtures); `test_store.py` passes; a test proves pre-`EARLIEST_DATE` and future dates are rejected.

### Milestone 4 — Validation harness
- `tracker validate --year Y [--month M]`: considers only **complete months** entirely within `[EARLIEST_DATE, today−2]` (Europe/London). `--month` naming an incomplete/out-of-range month → error listing eligible months. For each eligible month: ingest all days (cache-aware), aggregate, fetch `/api/summary/{Y}`, compare all four metrics: `bidCost`, `bidVolumeMWh`, `turnUpCost`, `turnUpVolume`.
- **Deviation:** `Δ% = |ours − theirs| / |theirs| × 100`; if `theirs == 0`: `Δ% = 0` when `ours == 0`, else the metric fails outright.
- **Exit status:** exit 1 if any compared metric of any compared month exceeds **2%**, unless waived. A waiver is an entry in `validation/waivers.yml` (`{year, month, metric, observed_pct, reason}`), matched on **`(year, month, metric)` only**; `observed_pct` is documentary (the Δ% at waiver time — validate always prints the *current* Δ% alongside `WAIVED (reason)`). Waived metrics do not affect exit status. Waivers may only be added after the investigation procedure below, and each must be mirrored by a dated explanation in `METHODOLOGY.md` § Validation results.
- Investigation procedure for >2%: (1) re-fetch a sample day with `--refresh` and diff (data revisions); (2) compare fuel-type lookups for the BMUs involved (site's static list vs live reference); (3) re-read the implementation against §4 line by line. If still unexplained → STOP per AGENTS.md (write `BLOCKED.md`). Never proceed with an unexplained deviation.
- Request volume note: a 30-day month is ≤ 3,000 stack requests ≈ 13 min at 4 req/s — expected, fine, cached forever after.
- **Accept:** `uv run tracker validate --year 2026 --month 6` exits 0 AND `uv run tracker validate --year 2026 --month 5` exits 0 (waivers permitted per above); `METHODOLOGY.md` § Validation results records the actual observed Δ% table for both months.

### Milestone 5 — Phase B: follow the money
- `turnup.py` (pure) — both functions take `(items: list[StackItem], fuel_lookup: dict[str, str | None])` (same `fuel_lookup` contract as §4 Step 2; `StackItem` itself has no fuelType field): `so_offer_payments(offer_items, fuel_lookup)` selects `soFlag == True` items (constraint turn-ups; **no cadlFlag filter here** — document), groups by `id`: per-BMU `volume_mwh = Σ volume`, `cost_gbp = Σ originalPrice × volume`. `so_wind_curtailment(bid_items, fuel_lookup)` selects `fuel_lookup[id] == "WIND" and soFlag`, groups by `id`: `volume_mwh = abs(Σ volume)`, `cost_gbp = Σ originalPrice × volume`.
- `store.py` additions — tables `turnup_by_bmu` and `curtailment_by_bmu`, identical schema: `(date, bmu_id)` PK, `national_grid_bmu_id, station_name, lead_party_id, lead_party_name, fuel_type, volume_mwh DOUBLE, cost_gbp DOUBLE`. Reference fields resolved via `bmu_ref` at compute time; unknown BMU ⇒ name/party fields NULL, `fuel_type` NULL. Per-date transactional delete-and-replace, same as `stack_items`.
- `ingest` now also computes+upserts both attribution tables. `tracker recompute --from A --to B`: recompute `daily_results` + both attribution tables from `stack_items` already in DuckDB — **zero HTTP**. After implementing, run `recompute` over every date already ingested (backfill).
- `owners.py` + `data/owners.csv` (columns: `lead_party_id, lead_party_name, parent_company, notes`). Seed deterministically: query `turnup_by_bmu` over **2026-05-01..2026-06-30** (already ingested during M4 — zero new HTTP), rank lead parties by Σ cost_gbp, take top 30; assign `parent_company` from the §7.1 table where `lead_party_name` matches (case-insensitive substring); otherwise `parent_company = lead_party_name`, `notes = "unverified"`.
- `tracker leaderboard --from A --to B [--by station|company] [--side turnup|curtailment] [--json]`: aggregates the relevant table over the inclusive range, sorted by `cost_gbp` desc. `--by company` joins owners.csv on `lead_party_id` (fallback: `lead_party_name`, else `bmu_id`).
- **Accept (deterministic):** `uv run tracker leaderboard --from 2026-06-01 --to 2026-06-30 --side turnup --by company --json` exits 0, outputs ≥ 10 rows, rows sorted by `cost_gbp` descending, total Σ cost_gbp > 0; `test_turnup.py` passes (fixtures: SO filter, grouping, signed sums, owner join incl. missing-owner and missing-reference fallbacks).

### Milestone 6 — Cross-checks (optional; bounded — must not block M7)
- `tracker crosscheck --date D` prints three views:
  1. Our curtailment £ (from `daily_results`).
  2. EBOCF wind-side: Σ over bid-flow EBOCF rows where `bmUnit` maps to fuelType WIND of `Σ_k coalesce(bidOfferPairCashflows.negativeK, 0)` for k=1..6. Compare magnitudes: `Δ% = ||EBOCF_sum| − |ours|| / |ours| × 100`; flag `> 25%`. Zero cases: both zero ⇒ 0%; ours zero with EBOCF nonzero ⇒ flag. (Sign convention of EBOCF cashflows is not pre-verified — record the observed sign in METHODOLOGY.md on first run; only magnitudes are compared.)
  3. MID alternative estimate: `Σ_p abs(period_curtailed[p]) × price(APXMIDP, p)` using `MID?from=D&to=D`; periods missing an APXMIDP row are skipped and logged.
- **Skip policy:** if acceptance fails after 3 distinct fix attempts, append `M6 SKIPPED: <detailed reason>` to `PROGRESS.md` and proceed to M7. M6 can never appear in `BLOCKED.md`.
- **Accept:** `uv run tracker crosscheck --date 2026-07-10` exits 0 and prints all three views (or the skip entry exists).

### Milestone 7 — Export + automation
- `export.py`:
  - `tracker export --date D` (or `--from/--to`) → `out/daily/YYYY-MM-DD.json` per the frozen schema in §8. Top-lists: `top_bmus` = top 10 from `curtailment_by_bmu` by `cost_gbp` desc; `top_companies` = top 10 company aggregates from `turnup_by_bmu` (owner join as in leaderboard).
  - `tracker export-summary` → `out/summary.json` (§8): **current Europe/London calendar year**, one element per month from January through the current month (current month flagged `"partial": true`, computed over days ≤ today−2), plus year-to-date totals.
  - **Completeness guard:** by default `export-summary` exits 1 listing any date in `[max(EARLIEST_DATE, Jan 1), today−2]` missing from `daily_results` — an incomplete year must never be silently published. `--allow-missing` computes over available dates anyway, marks every month with missing days `"partial": true`, and prints a warning (used for local acceptance so M7 doesn't require a multi-hour full-year backfill; the workflow uses strict mode after its backfill step).
  - Both commands validate output with pydantic models before writing; tests round-trip the schemas.
- GitHub Actions `.github/workflows/daily.yml`, cron `30 6 * * *` (06:30 UTC):
  1. **Prepare:** `actions/checkout`, install uv (`astral-sh/setup-uv`), `uv sync`, install rclone (`curl https://rclone.org/install.sh | sudo bash` or apt).
  2. **Restore state (non-destructive):** `rclone copy r2:constraint-tracker/state/raw raw/` and `rclone copy r2:constraint-tracker/state/tracker.duckdb data/` (if remote exists). Never `sync` toward local — the local cache must not lose files.
  3. **Backfill:** ingest any dates in `[EARLIEST_DATE, today−2]` missing from `daily_results` (cache-aware — after restore this is normally nothing; the first-ever run does the full year here).
  4. **Refresh window:** one inclusive re-ingest `--refresh` of `[max(EARLIEST_DATE, today−8), today−2]` (data revises for ~7 days).
  5. **Export:** dailies for the refresh window **and every date the backfill ingested**, then `export-summary` (strict mode, once).
  6. **Persist state + publish (non-destructive):** `rclone copy` `raw/` and `data/tracker.duckdb` to `r2:constraint-tracker/state/`, and `rclone copy out/` to `r2:constraint-tracker/` (`daily/`, `summary.json`). Always `copy`, never `sync` — a fresh runner must not delete historical remote files.
  - Upload tool is **rclone** with S3-compatible env config from secrets `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` (endpoint `https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com`). A first step exports `has_r2=true/false` (secret presence check via env indirection); all rclone steps have `if: steps.check.outputs.has_r2 == 'true'`. **Missing secrets ⇒ rclone steps skipped, workflow still succeeds** (compute-only run) with a visible warning annotation. This milestone's acceptance is entirely local — credentials are NOT required to complete it.
- **Accept:** `uv run tracker export --date 2026-07-10` writes JSON matching §8 (pydantic-validated in tests, incl. list limits and ordering); `uv run tracker export-summary --allow-missing` writes valid `out/summary.json`; a test proves strict mode exits 1 on a gap; workflow YAML parses (`python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/daily.yml'))"`) and passes `actionlint` if installed (else skip); README documents the three secrets and the R2 layout.

---

## 6. Validation success criteria (summary)

| Check | Threshold | Blocking? |
|---|---|---|
| Monthly bidCost, bidVolumeMWh, turnUpCost, turnUpVolume vs `/api/summary` (complete months, May + June 2026 minimum) | ±2% each, waiver mechanism per M4 | Yes (M4) |
| Idempotent re-ingest (five calculated values, excl. `computed_at`) | exact | Yes (M3) |
| EBOCF wind-side magnitude sanity | ±25% | No (M6, skippable) |

---

## 7. Methodology decisions (pre-made — record in METHODOLOGY.md, don't reopen)

1. **Primary data = settlement stack.** Supersession/dedup/integration are Elexon's problem, not ours. Raw BOALF/BOD/PN are cross-check material only.
2. **Replication uses `originalPrice × volume`**, no TLM, no finalPrice — because the site does (§4). Preferred variants (finalPrice, TLM-adjusted) may be added later as clearly-labelled alternates; not now.
3. **Day = Elexon settlement date** (Europe/London calendar day). No timezone math on our side; periods 1..50 requested always.
4. **SO-flag only** as the constraint filter, both sides. Known to be conservative/noisy; documented, not "fixed".
5. **Our number is a floor:** bilateral/LCM constraint actions and embedded wind are invisible here. The fixed `limitations` string in every export (§8) carries this.
6. **Phase B headline = gross payment** (Σ originalPrice×volume on SO-flagged offers). The premium-above-market framing goes in METHODOLOGY.md as an alternate, for fairness.
7. **Data revisions:** trailing 7 days re-ingested with `--refresh` in the daily job; historical months treated as stable.
8. Negative-priced offers / positive-priced bids (batteries etc.) are **included as-is** in replication (the site doesn't filter them); Phase B tables may show them — that's a feature (batteries earning is part of the story).
9. **Two turn-up measures, never conflated:** `replacement_cost` (§4 walk — feeds `total_cost` and matches wastedwind) and `so_flagged_payments` (Phase B gross £ to SO-flagged offer BMUs — feeds league tables).

### 7.1 Owner seed table (case-insensitive substring match on lead_party_name; **table order = precedence, first match wins**; comma-separated substrings are alternatives for the same row)

| Match substring | parent_company |
|---|---|
| SSE | SSE |
| RWE | RWE |
| Uniper | Uniper |
| EDF | EDF |
| Drax | Drax Group |
| VPI | VPI (Vitol) |
| ScottishPower, Scottish Power, SP Gen | Iberdrola (ScottishPower) |
| Centrica | Centrica |
| InterGen, Coryton, Rocksavage, Spalding | InterGen |
| ESB | ESB |
| Statkraft | Statkraft |
| Orsted, Ørsted | Ørsted |
| Vattenfall | Vattenfall |
| Triton, Saltend | SSE Thermal / Equinor (Triton Power) |
| EP UK, EPUKI | EPH |
| Vitol | Vitol |
| Equinor | Equinor |
| Greencoat | Greencoat |
| Fred. Olsen, Fred Olsen | Fred. Olsen |
| Moray Offshore, Ocean Winds | Ocean Winds |
| Seagreen | SSE / TotalEnergies (Seagreen) |
| Beatrice | SSE / Red Rock / TRIG (Beatrice) |

Anything not matched: `parent_company = lead_party_name`, `notes = "unverified"`. Do not research further; refinement is a human job later.

---

## 8. Export contract (frozen — the future Cloudflare site's API)

All field names snake_case, money GBP floats, volumes MWh floats. `methodology_version: "1.0"`, bumped on any calc change. `limitations` is this exact string in every file: `"BM settlement data only. Excludes bilateral trades, the Local Constraint Market and embedded (non-BM) wind: true constraint costs are higher. SO-flag is an imperfect constraint indicator."`

`out/daily/2026-07-10.json`:
```json
{
  "date": "2026-07-10",
  "methodology_version": "1.0",
  "limitations": "…fixed string above…",
  "curtailment": {
    "cost_gbp": 0.0,
    "volume_mwh": 0.0,
    "top_bmus": [
      {"bmu_id": "T_XXXX-1", "station_name": "…", "lead_party_name": "…",
       "parent_company": "…", "cost_gbp": 0.0, "volume_mwh": 0.0}
    ]
  },
  "turnup": {
    "replacement_cost_gbp": 0.0,
    "replacement_volume_mwh": 0.0,
    "so_flagged_payments_gbp": 0.0,
    "so_flagged_volume_mwh": 0.0,
    "top_companies": [
      {"parent_company": "…", "cost_gbp": 0.0, "volume_mwh": 0.0, "fuel_types": ["CCGT"]}
    ]
  },
  "total_cost_gbp": 0.0
}
```
- `top_bmus`: top 10 by `cost_gbp` desc from `curtailment_by_bmu`. `top_companies`: top 10 company aggregates by `cost_gbp` desc from `turnup_by_bmu` (SO-flagged payments measure). Deterministic ordering: ties broken by `bmu_id` / `parent_company` ascending. No nulls in exports: NULL `station_name`/`lead_party_name` ⇒ substitute the `bmu_id`; NULL `parent_company` ⇒ substitute `lead_party_name` (or `bmu_id`); NULL `fuel_type` ⇒ `"UNKNOWN"`. `fuel_types` = sorted unique fuel types of the company's contributing BMUs. `total_cost_gbp = curtailment.cost_gbp + turnup.replacement_cost_gbp` (the wastedwind-comparable headline).

`out/summary.json` — current Europe/London calendar year:
```json
{
  "generated_at": "2026-07-19T06:35:00Z",
  "methodology_version": "1.0",
  "limitations": "…fixed string…",
  "year": 2026,
  "totals": {"curtailment_cost_gbp": 0.0, "curtailment_volume_mwh": 0.0,
             "replacement_cost_gbp": 0.0, "total_cost_gbp": 0.0,
             "so_flagged_payments_gbp": 0.0},
  "months": [
    {"month": 1, "partial": false, "curtailment_cost_gbp": 0.0,
     "curtailment_volume_mwh": 0.0, "replacement_cost_gbp": 0.0,
     "so_flagged_payments_gbp": 0.0, "total_cost_gbp": 0.0}
  ]
}
```
- `months` ordered January → current month; current month `"partial": true` (days ≤ today−2 only). Totals = Σ months.

R2 layout: `constraint-tracker/daily/YYYY-MM-DD.json`, `constraint-tracker/summary.json`, private state under `constraint-tracker/state/`.

---

## 9. Out of scope (do not build)

- The public website, any HTML/frontend.
- LCM / bilateral-trade data, embedded wind estimation.
- Scraping wastedwind HTML pages (client-rendered; the summary API replaces it).
- Auth of any kind; everything used is open data.
- Owner-mapping research beyond §7.1.

---

## 10. Amendment v1.3 — full history + live provisional today

This section supersedes any conflicting earlier text. Implement as milestone
**M8** (loop protocol unchanged: task-by-task, green gates, commit each task,
record in PROGRESS.md/METHODOLOGY.md). Motivation: the tracker now feeds a
public site that must (a) show GB constraint history as far back as the data
allows (wastedwind publishes yearly summaries from 2015) and (b) display a
live, provisional figure for today, like wastedwind does.

### 10.1 Two distinct date floors (critical)

- `EARLIEST_DATE` becomes `date(2015, 1, 1)` — the **manual-command accept
  floor** for `fetch`, `ingest`, `show`, `export`, `leaderboard`, `crosscheck`,
  `validate`. (Elexon serves settlement stacks back to at least 2015; earlier
  dates simply return sparse/empty stacks and are still accepted.)
- **The daily-automation floor is NOT `EARLIEST_DATE`.** Introduce a computed
  `current_year_start()` = `date(today_in_london().year, 1, 1)`. The `backfill`
  command and `export-summary`'s completeness guard operate over
  `[current_year_start(), …]`, never `[EARLIEST_DATE, …]`. The scheduled job
  must never attempt to ingest all of 2015–present on each run. **This is the
  single most important part of this amendment** — getting it wrong makes the
  daily workflow try to fetch a decade every night.
- `validate --year Y` accepts any `Y` with `2015 ≤ Y ≤ today.year`.

### 10.2 Live provisional today

- `fetch`/`ingest` accept `[EARLIEST_DATE, today]` (was `today−1`). Dates
  `≥ today−1` are **provisional**: always fetched with refresh semantics (cache
  overwritten, never served stale intraday), because settlement data for the
  current and prior day is incomplete and revises. Dates `≤ today−2` keep the
  permanent sacred cache.
- Future dates (`> today`, Europe/London) remain rejected **before any HTTP**;
  never requested, never cached (unchanged).
- Per-day export (§8) gains `"provisional": true` for dates `≥ today−1`, else
  `false`, so the site can badge live days.
- `export-summary`: the current month's `partial` figure is computed over days
  `≤ today` (was `today−2`); still `"partial": true`. `validate` is unchanged —
  it still restricts to complete months `≤ today−2` (wastedwind itself lags, so
  fresher comparison is meaningless).

### 10.3 Acceptance (M8)

- `uv run tracker ingest --date <today>` succeeds and re-fetches provisional
  data on a second run (prove refresh: the two provisional days bypass cache).
- `uv run tracker ingest --date 2015-06-15 && uv run tracker show --date 2015-06-15`
  runs without a date-floor error (value may be small/zero — that's fine).
- A test proves the `backfill` command's missing-date set is bounded by
  `current_year_start()`, not `EARLIEST_DATE` (e.g. with no data, it targets
  only the current year, not ~4000 days).
- A test proves dates `> today` are still rejected before any HTTP.
- Daily export for a provisional date carries `"provisional": true`; an old
  date carries `false`.
- All prior milestones' gates stay green; full `uv run pytest`, `ruff`, `mypy`
  clean.
