"""Rate-limited, cached client for Elexon's public BMRS API."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import threading
import time
from typing import Any
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

import httpx

from tracker.config import (
    BASE_URL,
    MAX_RETRIES,
    MIN_ATTEMPT_INTERVAL_S,
    WASTEDWIND_BASE,
)
from tracker.models import BmuRef, StackItem, WastedWindSummary

JsonValue = dict[str, Any] | list[Any]


class ElexonClient:
    """Fetch Elexon data while preserving a reproducible local raw cache."""

    _pacing_lock = threading.Lock()
    _last_attempt_start: float | None = None

    def __init__(
        self, cache_dir: Path, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.cache_dir = cache_dir
        self._client = httpx.Client(transport=transport, timeout=30.0)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ElexonClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get(
        self,
        path: str,
        params: dict[str, str | int] | None = None,
        refresh: bool = False,
    ) -> JsonValue:
        """Return decoded Elexon JSON for a relative API path."""
        url = f"{BASE_URL.rstrip('/')}/{path.lstrip('/')}"
        cache_path = self._canonical_cache_path(url, params)
        return self._cached_request(url, params, cache_path, refresh)

    def bid_stack(
        self, settlement_date: date, period: int, refresh: bool = False
    ) -> list[StackItem]:
        return self._stack("bid", settlement_date, period, refresh)

    def offer_stack(
        self, settlement_date: date, period: int, refresh: bool = False
    ) -> list[StackItem]:
        return self._stack("offer", settlement_date, period, refresh)

    def _stack(
        self, flow: str, settlement_date: date, period: int, refresh: bool
    ) -> list[StackItem]:
        data = self.get(
            f"/balancing/settlement/stack/all/{flow}/{settlement_date.isoformat()}/{period}",
            refresh=refresh,
        )
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise ValueError("Settlement stack response lacks a data list")
        return [StackItem.model_validate(item) for item in data["data"]]

    def bmunits(self, refresh: bool = False) -> list[BmuRef]:
        cache_path = self.cache_dir / "reference" / "bmunits.json"
        data = self._cached_request(
            f"{BASE_URL}/reference/bmunits/all", None, cache_path, refresh
        )
        if not isinstance(data, list):
            raise ValueError("BMU reference response must be an array")
        return [BmuRef.model_validate(item) for item in data]

    def wastedwind_summary(self, year: int) -> WastedWindSummary:
        fetch_date = time_in_london().isoformat()
        cache_path = self.cache_dir / "wastedwind" / f"summary-{year}-{fetch_date}.json"
        data = self._cached_request(
            f"{WASTEDWIND_BASE}/api/summary/{year}", None, cache_path, False
        )
        return WastedWindSummary.model_validate(data)

    def _cached_request(
        self,
        url: str,
        params: dict[str, str | int] | None,
        cache_path: Path,
        refresh: bool,
    ) -> JsonValue:
        if cache_path.exists() and not refresh:
            return self._read_cache(cache_path)

        response = self._request_with_retries(url, params)
        if response.status_code == 404 and "/balancing/settlement/stack/all/" in url:
            data: JsonValue = {"data": []}
        else:
            response.raise_for_status()
            decoded = response.json()
            if not isinstance(decoded, (dict, list)):
                raise ValueError(f"Expected JSON object or array from {url}")
            data = decoded
        self._write_cache(cache_path, data)
        return data

    def _request_with_retries(
        self, url: str, params: dict[str, str | int] | None
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                self._pace_attempts()
                response = self._client.get(url, params=params)
                if response.status_code != 429 and response.status_code < 500:
                    return response
                last_error = httpx.HTTPStatusError(
                    f"Retryable response {response.status_code}",
                    request=response.request,
                    response=response,
                )
                retry_after = response.headers.get("Retry-After")
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                retry_after = None

            if attempt == MAX_RETRIES:
                assert last_error is not None
                raise last_error
            backoff = float(2**attempt)
            if retry_after is not None:
                try:
                    backoff = max(backoff, float(retry_after))
                except ValueError:
                    pass
            time.sleep(backoff)
        raise AssertionError("unreachable")

    @classmethod
    def _pace_attempts(cls) -> None:
        with cls._pacing_lock:
            now = time.monotonic()
            if cls._last_attempt_start is not None:
                wait = MIN_ATTEMPT_INTERVAL_S - (now - cls._last_attempt_start)
                if wait > 0:
                    time.sleep(wait)
            cls._last_attempt_start = time.monotonic()

    def _canonical_cache_path(
        self, url: str, params: dict[str, str | int] | None
    ) -> Path:
        parsed = urlsplit(url)
        query = urlencode(sorted((params or {}).items()), doseq=True)
        canonical_key = f"{parsed.netloc}{parsed.path}?{query}"
        filename = parsed.path.lstrip("/").replace("/", "__")
        if query:
            filename = f"{filename}?{query.replace('/', '%2F').replace(':', '%3A')}"
        filename = f"{filename}.json"
        if len(filename) > 180:
            filename = f"{sha256(canonical_key.encode()).hexdigest()}.json"
        return self.cache_dir / parsed.netloc / filename

    @staticmethod
    def _read_cache(cache_path: Path) -> JsonValue:
        data = json.loads(cache_path.read_text())
        if not isinstance(data, (dict, list)):
            raise ValueError(f"Invalid cache JSON in {cache_path}")
        return data

    @staticmethod
    def _write_cache(cache_path: Path, data: JsonValue) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
        temp_path.write_text(json.dumps(data, separators=(",", ":")))
        temp_path.replace(cache_path)


def time_in_london() -> date:
    """Return today's calendar date in the tracker timezone."""
    from datetime import datetime

    return datetime.now(ZoneInfo("Europe/London")).date()
