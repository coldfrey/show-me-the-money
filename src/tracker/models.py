"""Validated models for the external data sources."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class StackItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    settlementDate: date
    settlementPeriod: int
    startTime: datetime
    sequenceNumber: int
    id: str
    acceptanceId: int | None
    bidOfferPairId: int | None
    cadlFlag: bool | None
    soFlag: bool
    originalPrice: float
    finalPrice: float | None
    volume: float
    transmissionLossMultiplier: float | None
    createdDateTime: datetime | None
    storProviderFlag: bool | None
    repricedIndicator: bool | None
    reserveScarcityPrice: float | None
    dmatAdjustedVolume: float | None
    arbitrageAdjustedVolume: float | None
    nivAdjustedVolume: float | None
    parAdjustedVolume: float | None
    tlmAdjustedVolume: float | None
    tlmAdjustedCost: float | None


class BmuRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    elexonBmUnit: str
    nationalGridBmUnit: str | None
    bmUnitName: str | None
    leadPartyName: str | None
    leadPartyId: str | None
    fuelType: str | None
    generationCapacity: str | None
    bmUnitType: str | None
    interconnectorId: str | None
    gspGroupId: str | None


class WastedWindTotal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    bidCost: float
    offerCost: float
    totalCost: float
    volume: float


class WastedWindMonth(BaseModel):
    model_config = ConfigDict(extra="ignore")

    year: int
    month: int
    bidVolumeMWh: float
    bidCost: float
    turnUpVolume: float
    turnUpCost: float


class WastedWindSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total: WastedWindTotal
    data: list[WastedWindMonth]
