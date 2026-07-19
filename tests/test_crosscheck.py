from tracker.crosscheck import (
    ebocf_wind_cashflow,
    magnitude_deviation_pct,
    mid_alternative_estimate,
)


def test_ebocf_uses_negative_pairs_for_wind_only() -> None:
    rows = [
        {
            "bmUnit": "W",
            "bidOfferPairCashflows": {
                "negative1": -100,
                "negative2": None,
                "positive1": 999,
            },
        },
        {"bmUnit": "G", "bidOfferPairCashflows": {"negative1": -500}},
    ]

    assert ebocf_wind_cashflow(rows, {"W": "WIND", "G": "CCGT"}) == -100


def test_magnitude_deviation_handles_sign_and_zero_cases() -> None:
    assert magnitude_deviation_pct(100, -90) == 10
    assert magnitude_deviation_pct(0, 0) == 0
    assert magnitude_deviation_pct(0, 1) == float("inf")


def test_mid_estimate_skips_and_reports_missing_periods() -> None:
    curtailed = {1: -2, 2: -3}
    rows = [
        {"dataProvider": "APXMIDP", "settlementPeriod": 1, "price": 50},
        {"dataProvider": "N2EXMIDP", "settlementPeriod": 2, "price": 999},
    ]

    estimate, missing = mid_alternative_estimate(curtailed, rows)

    assert estimate == 100
    assert missing == [2]
