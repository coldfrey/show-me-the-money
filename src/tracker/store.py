"""DuckDB persistence for raw-normalized and calculated tracker data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

import duckdb

from tracker.models import BmuRef, StackItem
from tracker.turnup import BmuAmount
from tracker.wastedwind import DayResult

Flow = Literal["bid", "offer"]
NULL_IDENTIFIER = -(2**63)
NULL_BMU_ID = "__NULL_BMU__"


@dataclass(frozen=True)
class DailyResultRecord:
    date: date
    curtailment_cost: float
    curtailment_volume: float
    turnup_cost: float
    turnup_volume: float
    total_cost: float
    computed_at: datetime

    @property
    def calculated_values(self) -> tuple[float, float, float, float, float]:
        return (
            self.curtailment_cost,
            self.curtailment_volume,
            self.turnup_cost,
            self.turnup_volume,
            self.total_cost,
        )


@dataclass(frozen=True)
class MonthlyAggregate:
    curtailment_cost: float
    curtailment_volume: float
    turnup_cost: float
    turnup_volume: float


@dataclass(frozen=True)
class AttributionRecord:
    date: date
    bmu_id: str
    national_grid_bmu_id: str | None
    station_name: str | None
    lead_party_id: str | None
    lead_party_name: str | None
    fuel_type: str | None
    volume_mwh: float
    cost_gbp: float


class TrackerStore:
    """Own the tracker's single DuckDB database."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = duckdb.connect(str(path))
        self._create_schema()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> TrackerStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _create_schema(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS stack_items (
                settlementDate DATE NOT NULL,
                settlementPeriod INTEGER NOT NULL,
                flow TEXT NOT NULL CHECK (flow IN ('bid', 'offer')),
                startTime TIMESTAMPTZ NOT NULL,
                createdDateTime TIMESTAMPTZ,
                sequenceNumber INTEGER NOT NULL,
                id TEXT NOT NULL,
                acceptanceId BIGINT NOT NULL,
                bidOfferPairId BIGINT NOT NULL,
                cadlFlag BOOLEAN,
                soFlag BOOLEAN NOT NULL,
                storProviderFlag BOOLEAN,
                repricedIndicator BOOLEAN,
                reserveScarcityPrice DOUBLE,
                originalPrice DOUBLE NOT NULL,
                finalPrice DOUBLE,
                volume DOUBLE NOT NULL,
                transmissionLossMultiplier DOUBLE,
                dmatAdjustedVolume DOUBLE,
                arbitrageAdjustedVolume DOUBLE,
                nivAdjustedVolume DOUBLE,
                parAdjustedVolume DOUBLE,
                tlmAdjustedVolume DOUBLE,
                tlmAdjustedCost DOUBLE,
                PRIMARY KEY (
                    settlementDate, settlementPeriod, flow, id,
                    acceptanceId, bidOfferPairId, sequenceNumber
                )
            )
            """
        )
        for table in ("turnup_by_bmu", "curtailment_by_bmu"):
            self.connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    date DATE NOT NULL,
                    bmu_id TEXT NOT NULL,
                    national_grid_bmu_id TEXT,
                    station_name TEXT,
                    lead_party_id TEXT,
                    lead_party_name TEXT,
                    fuel_type TEXT,
                    volume_mwh DOUBLE NOT NULL,
                    cost_gbp DOUBLE NOT NULL,
                    PRIMARY KEY (date, bmu_id)
                )
                """
            )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS bmu_ref (
                elexonBmUnit TEXT PRIMARY KEY,
                nationalGridBmUnit TEXT,
                bmUnitName TEXT,
                leadPartyName TEXT,
                leadPartyId TEXT,
                fuelType TEXT,
                generationCapacity TEXT,
                bmUnitType TEXT,
                interconnectorId TEXT,
                gspGroupId TEXT
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_results (
                date DATE PRIMARY KEY,
                curtailment_cost DOUBLE NOT NULL,
                curtailment_volume DOUBLE NOT NULL,
                turnup_cost DOUBLE NOT NULL,
                turnup_volume DOUBLE NOT NULL,
                total_cost DOUBLE NOT NULL,
                computed_at TIMESTAMP NOT NULL
            )
            """
        )

    def replace_stack_items(
        self,
        settlement_date: date,
        bid_items: list[StackItem],
        offer_items: list[StackItem],
    ) -> None:
        rows = [self._stack_row(item, "bid") for item in bid_items]
        rows.extend(self._stack_row(item, "offer") for item in offer_items)
        self.connection.execute("BEGIN")
        try:
            self.connection.execute(
                "DELETE FROM stack_items WHERE settlementDate = ?", [settlement_date]
            )
            if rows:
                self.connection.executemany(
                    """
                    INSERT INTO stack_items VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?
                    )
                    """,
                    rows,
                )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    @staticmethod
    def _stack_row(item: StackItem, flow: Flow) -> tuple[Any, ...]:
        return (
            item.settlementDate,
            item.settlementPeriod,
            flow,
            item.startTime,
            item.createdDateTime,
            item.sequenceNumber,
            item.id if item.id is not None else NULL_BMU_ID,
            item.acceptanceId if item.acceptanceId is not None else NULL_IDENTIFIER,
            item.bidOfferPairId if item.bidOfferPairId is not None else NULL_IDENTIFIER,
            item.cadlFlag,
            item.soFlag,
            item.storProviderFlag,
            item.repricedIndicator,
            item.reserveScarcityPrice,
            item.originalPrice,
            item.finalPrice,
            item.volume,
            item.transmissionLossMultiplier,
            item.dmatAdjustedVolume,
            item.arbitrageAdjustedVolume,
            item.nivAdjustedVolume,
            item.parAdjustedVolume,
            item.tlmAdjustedVolume,
            item.tlmAdjustedCost,
        )

    def replace_bmu_ref(self, items: list[BmuRef]) -> None:
        rows = [
            (
                item.elexonBmUnit,
                item.nationalGridBmUnit,
                item.bmUnitName,
                item.leadPartyName,
                item.leadPartyId,
                item.fuelType,
                item.generationCapacity,
                item.bmUnitType,
                item.interconnectorId,
                item.gspGroupId,
            )
            for item in items
        ]
        self.connection.execute("BEGIN")
        try:
            self.connection.execute("DELETE FROM bmu_ref")
            if rows:
                self.connection.executemany(
                    "INSERT INTO bmu_ref VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
                )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def fuel_lookup(self) -> dict[str, str | None]:
        return dict(
            self.connection.execute(
                "SELECT elexonBmUnit, fuelType FROM bmu_ref"
            ).fetchall()
        )

    def bmu_references(self) -> list[BmuRef]:
        rows = self.connection.execute(
            """
            SELECT elexonBmUnit, nationalGridBmUnit, bmUnitName, leadPartyName,
                   leadPartyId, fuelType, generationCapacity, bmUnitType,
                   interconnectorId, gspGroupId
            FROM bmu_ref ORDER BY elexonBmUnit
            """
        ).fetchall()
        return [
            BmuRef.model_validate(dict(zip(BmuRef.model_fields, row))) for row in rows
        ]

    def replace_daily_result(self, result: DayResult) -> None:
        computed_at = datetime.now(UTC).replace(tzinfo=None)
        self.connection.execute("BEGIN")
        try:
            self.connection.execute(
                "DELETE FROM daily_results WHERE date = ?", [result.date]
            )
            self.connection.execute(
                "INSERT INTO daily_results VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    result.date,
                    result.curtailment.cost_gbp,
                    result.curtailment.volume_mwh,
                    result.turnup.cost_gbp,
                    result.turnup.volume_mwh,
                    result.total_cost_gbp,
                    computed_at,
                ],
            )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def daily_result(self, settlement_date: date) -> DailyResultRecord | None:
        row = self.connection.execute(
            """
            SELECT date, curtailment_cost, curtailment_volume, turnup_cost,
                   turnup_volume, total_cost, computed_at
            FROM daily_results WHERE date = ?
            """,
            [settlement_date],
        ).fetchone()
        return DailyResultRecord(*row) if row is not None else None

    def stack_item_count(self, settlement_date: date) -> int:
        row = self.connection.execute(
            "SELECT count(*) FROM stack_items WHERE settlementDate = ?",
            [settlement_date],
        ).fetchone()
        assert row is not None
        return int(row[0])

    def stack_items(self, settlement_date: date, flow: Flow) -> list[StackItem]:
        fields = list(StackItem.model_fields)
        rows = self.connection.execute(
            """
            SELECT settlementDate, settlementPeriod, startTime, sequenceNumber,
                   id, acceptanceId, bidOfferPairId, cadlFlag, soFlag,
                   originalPrice, finalPrice, volume, transmissionLossMultiplier,
                   createdDateTime, storProviderFlag, repricedIndicator,
                   reserveScarcityPrice, dmatAdjustedVolume,
                   arbitrageAdjustedVolume, nivAdjustedVolume, parAdjustedVolume,
                   tlmAdjustedVolume, tlmAdjustedCost
            FROM stack_items
            WHERE settlementDate = ? AND flow = ?
            ORDER BY settlementPeriod, rowid
            """,
            [settlement_date, flow],
        ).fetchall()
        items: list[StackItem] = []
        for row in rows:
            values = list(row)
            if values[4] == NULL_BMU_ID:
                values[4] = None
            if values[5] == NULL_IDENTIFIER:
                values[5] = None
            if values[6] == NULL_IDENTIFIER:
                values[6] = None
            items.append(StackItem.model_validate(dict(zip(fields, values))))
        return items

    def stored_dates(self, start: date, end: date) -> list[date]:
        return [
            row[0]
            for row in self.connection.execute(
                """
                SELECT DISTINCT settlementDate FROM stack_items
                WHERE settlementDate BETWEEN ? AND ? ORDER BY settlementDate
                """,
                [start, end],
            ).fetchall()
        ]

    def replace_attributions(
        self,
        settlement_date: date,
        turnup: dict[str | None, BmuAmount],
        curtailment: dict[str | None, BmuAmount],
        references: dict[str, BmuRef],
    ) -> None:
        self.connection.execute("BEGIN")
        try:
            for table, amounts in (
                ("turnup_by_bmu", turnup),
                ("curtailment_by_bmu", curtailment),
            ):
                self.connection.execute(
                    f"DELETE FROM {table} WHERE date = ?", [settlement_date]
                )
                rows = [
                    self._attribution_row(settlement_date, bmu_id, amount, references)
                    for bmu_id, amount in amounts.items()
                ]
                if rows:
                    self.connection.executemany(
                        f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        rows,
                    )
            self.connection.execute("COMMIT")
        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    @staticmethod
    def _attribution_row(
        settlement_date: date,
        bmu_id: str | None,
        amount: BmuAmount,
        references: dict[str, BmuRef],
    ) -> tuple[Any, ...]:
        stored_bmu_id = bmu_id if bmu_id is not None else NULL_BMU_ID
        reference = references.get(stored_bmu_id)
        return (
            settlement_date,
            stored_bmu_id,
            reference.nationalGridBmUnit if reference else None,
            reference.bmUnitName if reference else None,
            reference.leadPartyId if reference else None,
            reference.leadPartyName if reference else None,
            reference.fuelType if reference else None,
            amount.volume_mwh,
            amount.cost_gbp,
        )

    def attribution_rows(
        self, start: date, end: date, side: Literal["turnup", "curtailment"]
    ) -> list[AttributionRecord]:
        table = "turnup_by_bmu" if side == "turnup" else "curtailment_by_bmu"
        rows = self.connection.execute(
            f"""
            SELECT date, bmu_id, national_grid_bmu_id, station_name,
                   lead_party_id, lead_party_name, fuel_type, volume_mwh, cost_gbp
            FROM {table} WHERE date BETWEEN ? AND ?
            ORDER BY date, bmu_id
            """,
            [start, end],
        ).fetchall()
        return [AttributionRecord(*row) for row in rows]

    def lead_party_totals(
        self, start: date, end: date, limit: int
    ) -> list[tuple[str, str, float]]:
        return [
            (str(row[0]), str(row[1]), float(row[2]))
            for row in self.connection.execute(
                """
                SELECT lead_party_id, lead_party_name, sum(cost_gbp) AS cost
                FROM turnup_by_bmu
                WHERE date BETWEEN ? AND ?
                  AND lead_party_id IS NOT NULL AND lead_party_name IS NOT NULL
                GROUP BY lead_party_id, lead_party_name
                ORDER BY cost DESC, lead_party_id, lead_party_name
                LIMIT ?
                """,
                [start, end, limit],
            ).fetchall()
        ]

    def monthly_aggregate(self, year: int, month: int) -> MonthlyAggregate:
        row = self.connection.execute(
            """
            SELECT coalesce(sum(curtailment_cost), 0),
                   coalesce(sum(curtailment_volume), 0),
                   coalesce(sum(turnup_cost), 0),
                   coalesce(sum(turnup_volume), 0)
            FROM daily_results
            WHERE year(date) = ? AND month(date) = ?
            """,
            [year, month],
        ).fetchone()
        assert row is not None
        return MonthlyAggregate(*(float(value) for value in row))
