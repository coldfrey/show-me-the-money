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

## Validation results

None yet.
