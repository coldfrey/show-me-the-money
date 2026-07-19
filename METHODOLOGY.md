# Methodology

This document records calculation choices, deviations from `SPEC.md`, and
validation evidence for the constraint-cost tracker.

## Deviations

- **2026-07-19 — nullable settlement-stack identifiers:** live Elexon
  settlement-stack responses contain synthetic SO-flagged offers (observed with
  `id = "1"`) whose `acceptanceId` and `bidOfferPairId` are null. `StackItem`
  therefore accepts null for those two fields, although SPEC §3.1 types them as
  integers. The records and their calculation fields are retained unchanged.

## Validation results

None yet.
