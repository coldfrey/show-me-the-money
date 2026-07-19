"""DuckDB persistence for raw-normalized and calculated tracker data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

import duckdb

from tracker.models import BmuRef, StackItem
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
