"""Deterministic parent-company mapping and leaderboard aggregation."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from tracker.store import AttributionRecord, TrackerStore

OWNER_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("SSE",), "SSE"),
    (("RWE",), "RWE"),
    (("Uniper",), "Uniper"),
    (("EDF",), "EDF"),
    (("Drax",), "Drax Group"),
    (("VPI",), "VPI (Vitol)"),
    (("ScottishPower", "Scottish Power", "SP Gen"), "Iberdrola (ScottishPower)"),
    (("Centrica",), "Centrica"),
    (("InterGen", "Coryton", "Rocksavage", "Spalding"), "InterGen"),
    (("ESB",), "ESB"),
    (("Statkraft",), "Statkraft"),
    (("Orsted", "Ørsted"), "Ørsted"),
    (("Vattenfall",), "Vattenfall"),
    (("Triton", "Saltend"), "SSE Thermal / Equinor (Triton Power)"),
    (("EP UK", "EPUKI"), "EPH"),
    (("Vitol",), "Vitol"),
    (("Equinor",), "Equinor"),
    (("Greencoat",), "Greencoat"),
    (("Fred. Olsen", "Fred Olsen"), "Fred. Olsen"),
    (("Moray Offshore", "Ocean Winds"), "Ocean Winds"),
    (("Seagreen",), "SSE / TotalEnergies (Seagreen)"),
    (("Beatrice",), "SSE / Red Rock / TRIG (Beatrice)"),
)


@dataclass(frozen=True)
class Owner:
    lead_party_id: str
    lead_party_name: str
    parent_company: str
    notes: str


def map_parent_company(lead_party_name: str) -> tuple[str, str]:
    folded = lead_party_name.casefold()
    for alternatives, parent in OWNER_RULES:
        if any(value.casefold() in folded for value in alternatives):
            return parent, ""
    return lead_party_name, "unverified"


def seed_owners(
    store: TrackerStore,
    path: Path,
    start: date = date(2026, 5, 1),
    end: date = date(2026, 6, 30),
) -> list[Owner]:
    owners = []
    for lead_party_id, lead_party_name, _cost in store.lead_party_totals(
        start, end, 30
    ):
        parent, notes = map_parent_company(lead_party_name)
        owners.append(Owner(lead_party_id, lead_party_name, parent, notes))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(Owner.__dataclass_fields__))
        writer.writeheader()
        for owner in owners:
            writer.writerow(owner.__dict__)
    return owners


def load_owners(path: Path) -> dict[str, Owner]:
    if not path.exists():
        return {}
    with path.open(newline="") as source:
        return {row["lead_party_id"]: Owner(**row) for row in csv.DictReader(source)}


def aggregate_leaderboard(
    rows: list[AttributionRecord],
    by: Literal["station", "company"],
    owners: dict[str, Owner],
) -> list[dict[str, Any]]:
    if by == "station":
        return _station_leaderboard(rows)
    return _company_leaderboard(rows, owners)


def _station_leaderboard(rows: list[AttributionRecord]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        result = grouped.setdefault(
            row.bmu_id,
            {
                "bmu_id": row.bmu_id,
                "station_name": row.station_name or row.bmu_id,
                "lead_party_name": row.lead_party_name or row.bmu_id,
                "fuel_type": row.fuel_type or "UNKNOWN",
                "volume_mwh": 0.0,
                "cost_gbp": 0.0,
            },
        )
        result["volume_mwh"] += row.volume_mwh
        result["cost_gbp"] += row.cost_gbp
    return sorted(
        grouped.values(), key=lambda item: (-item["cost_gbp"], item["bmu_id"])
    )


def _company_leaderboard(
    rows: list[AttributionRecord], owners: dict[str, Owner]
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        owner = owners.get(row.lead_party_id or "")
        company = (
            owner.parent_company
            if owner is not None
            else (row.lead_party_name or row.bmu_id)
        )
        result = grouped.setdefault(
            company,
            {
                "parent_company": company,
                "volume_mwh": 0.0,
                "cost_gbp": 0.0,
                "fuel_types": set(),
            },
        )
        result["volume_mwh"] += row.volume_mwh
        result["cost_gbp"] += row.cost_gbp
        result["fuel_types"].add(row.fuel_type or "UNKNOWN")
    output = []
    for result in grouped.values():
        result["fuel_types"] = sorted(result["fuel_types"])
        output.append(result)
    return sorted(
        output,
        key=lambda item: (-item["cost_gbp"], item["parent_company"]),
    )
