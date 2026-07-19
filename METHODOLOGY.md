# Methodology

This document records calculation choices, deviations from `SPEC.md`, and
validation evidence for the constraint-cost tracker.

## Calculation choices

- Settlement-stack data is primary; Elexon owns acceptance supersession,
  deduplication, and volume integration.
- Replication uses `originalPrice * volume` without final-price or TLM
  adjustment, matching wastedwind.energy.
- A day is the Europe/London Elexon settlement date, with periods 1 through 50
  always requested.
- SO flag is the constraint filter. Negative-priced offers and positive-priced
  bids remain included as supplied.
- The reported figures are a floor because BM settlement data excludes
  bilateral trades, the Local Constraint Market, and embedded wind.
- Replacement cost is the stable offer-stack walk for curtailed volume. It is
  distinct from Phase B's gross SO-flagged offer payments and the measures are
  never combined.
- Phase B reports gross payment. Premium above market is a possible future
  alternate, not the headline measure.
- The scheduled process refreshes the trailing seven days; older months are
  treated as stable.
- Fuel types are enriched from Elexon's live BMU reference list. The reference
  site uses a bundled static list, so recently changed BMUs could differ.
- Phase B gross SO-flagged offer payments intentionally do not apply a CADL
  filter. This is distinct from replacement cost, whose stack walk excludes
  CADL-flagged offers to match wastedwind.energy.

## Deviations

- **2026-07-19 — nullable settlement-stack identifiers:** live Elexon
  settlement-stack responses contain synthetic SO-flagged offers (observed with
  `id = "1"`) whose `acceptanceId` and `bidOfferPairId` are null. `StackItem`
  therefore accepts null for those two fields, although SPEC §3.1 types them as
  integers. The records and their calculation fields are retained unchanged.
  DuckDB primary-key columns cannot be null, so persistence maps those two null
  identifiers to the reserved sentinel `-9223372036854775808`; no calculation
  uses either identifier.
- **2026-07-19 — BMU reference rows without an Elexon ID:** the live
  `/reference/bmunits/all` response contains 89 rows with null
  `elexonBmUnit`. They remain in the raw cache but are excluded from the typed
  reference list because they cannot participate in the specified BMU join or
  satisfy the `bmu_ref` primary key.
- **2026-07-19 — duplicate BMU reference:** the live reference response
  includes `T_WLNYO-4` twice. The rows are identical across all fields in SPEC
  §3.2 and differ only in the ignored `eic` field. The raw cache retains both;
  typed reference data deterministically retains the first row so
  `elexonBmUnit` remains a valid primary key.
- **2026-07-19 — null settlement-stack BMU IDs:** live stack data includes
  occasional rows with null `id` (first observed on 2026-06-01 period 40).
  They remain in calculation input with unknown fuel; this excludes them from
  wind curtailment while retaining them in the all-fuel offer walk. Persistence
  maps null to the reserved primary-key value `__NULL_BMU__`.

## Validation results

### 2026-07-19 — wastedwind.energy monthly replication

No waivers were needed. Values below are fresh Elexon settlement-stack
aggregates compared with the same-day wastedwind.energy summary API.

| Month | Metric | Ours | Theirs | Absolute delta |
|---|---|---:|---:|---:|
| 2026-05 | bidCost | 10,250,812.402910 | 10,239,915.901660 | 0.106412% |
| 2026-05 | bidVolumeMWh | 577,414.328564 | 576,680.536897 | 0.127244% |
| 2026-05 | turnUpCost | 82,411,399.349244 | 82,312,435.899796 | 0.120229% |
| 2026-05 | turnUpVolume | 570,779.876404 | 570,046.084738 | 0.128725% |
| 2026-06 | bidCost | 20,443,572.767158 | 20,443,572.767158 | 0.000000% |
| 2026-06 | bidVolumeMWh | 605,943.025167 | 605,943.025167 | 0.000000% |
| 2026-06 | turnUpCost | 89,558,881.516572 | 89,576,953.407854 | 0.020175% |
| 2026-06 | turnUpVolume | 600,075.795330 | 600,075.795330 | 0.000000% |
