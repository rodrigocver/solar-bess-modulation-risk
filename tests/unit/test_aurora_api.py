"""Testes unitários do cliente Aurora EOS Scenario Explorer (sem rede)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from solar_bess_risk.aurora_api import (
    AuroraAPIError,
    AuroraScenarioExplorer,
    Scenario,
    load_token,
)
from solar_bess_risk.config import HOURS_PER_YEAR
from solar_bess_risk.data_sources import DataSourceError, load_price_aurora_api

SCENARIOS_JSON = {
    "currencies": [{"currencyCode": "brl2025", "name": "BRL 2025 real"}],
    "regions": [{"regionCode": "bra_se", "regionFullName": "Brazil SE"}],
    "scenarios": [
        {
            "regionCode": "bra_se",
            "sensitivity": "central",
            "name": "Brazil Q1 26 (Central)",
            "hash": "old-hash",
            "publicationDate": "2026-01-10T12:00:00.000Z",
            "defaultCurrency": "brl2025",
            "products": ["bra_power_and_res"],
            "metaUrl": "v1/scenarios/pmf/old-hash/bra_se/central/meta.json",
            "dataUrlBase": "v1/scenarios/pmf/old-hash/bra_se/central/",
        },
        {
            "regionCode": "bra_se",
            "sensitivity": "central",
            "name": "Brazil Q2 26 (Central)",
            "hash": "new-hash",
            "publicationDate": "2026-04-23T13:36:08.000Z",
            "defaultCurrency": "brl2025",
            "products": ["bra_power_and_res"],
            "metaUrl": "v1/scenarios/pmf/new-hash/bra_se/central/meta.json",
            "dataUrlBase": "v1/scenarios/pmf/new-hash/bra_se/central/",
        },
        {
            "regionCode": "bra_ne",
            "sensitivity": "low",
            "name": "Brazil Q2 26 (Low)",
            "hash": "ne-hash",
            "publicationDate": "2026-04-23T13:36:08.000Z",
            "defaultCurrency": "brl2025",
            "products": ["bra_power_and_res"],
            "metaUrl": "v1/scenarios/pmf/ne-hash/bra_ne/low/meta.json",
            "dataUrlBase": "v1/scenarios/pmf/ne-hash/bra_ne/low/",
        },
    ],
}

META_JSON = {
    "years": [2026, 2027],
    "dataDefinitions": [
        {
            "type": "system",
            "granularity": "1h",
            "filename": "{currency}-system-1h.csv",
            "structure": [
                {"name": "Time (UTC)", "unit": "UTC"},
                {"name": "Time (Local)", "unit": "UTC-03:00"},
                {"name": "Wholesale market price", "unit": "{currency}/MWh"},
            ],
        }
    ],
}

SYSTEM_1H_CSV = (
    "Time (UTC),Time (Local),Wholesale market price\n"
    "UTC,UTC-03:00,BRL/MWh\n"
    "2026-10-01 03:00:00,2026-10-01 00:00:00,252.9\n"
    "2026-10-01 04:00:00,2026-10-01 01:00:00,251.4\n"
)


class _FakeResponse:
    def __init__(self, status_code: int, *, text: str = "", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self):
        return self._payload


class _FakeHeaders(dict):
    def update(self, other):  # noqa: D401 - mimic requests headers
        super().update(other)


class FakeSession:
    """Roteia GETs por sufixo de URL, sem rede."""

    def __init__(self, *, fail_status: int | None = None):
        self.headers = _FakeHeaders()
        self.fail_status = fail_status
        self.requested: list[str] = []

    def get(self, url: str, timeout: float = 0):  # noqa: ARG002
        self.requested.append(url)
        if self.fail_status is not None:
            return _FakeResponse(self.fail_status, text="boom")
        if url.endswith("/v1/scenarios"):
            return _FakeResponse(200, text=json.dumps(SCENARIOS_JSON), payload=SCENARIOS_JSON)
        if url.endswith("meta.json"):
            return _FakeResponse(200, text=json.dumps(META_JSON), payload=META_JSON)
        if url.endswith("brl2025-system-1h.csv"):
            return _FakeResponse(200, text=SYSTEM_1H_CSV)
        return _FakeResponse(404, text="not found")


@pytest.fixture
def api():
    return AuroraScenarioExplorer(token="t0ken", cache_dir=None, session=FakeSession())


def test_load_token_from_keys_env(tmp_path, monkeypatch):
    for var in ("AURORA_KEY", "aurora_key"):
        monkeypatch.delenv(var, raising=False)
    keys = tmp_path / "keys.env"
    keys.write_text("﻿aurora_key=abc123\r\n", encoding="utf-8")
    assert load_token(keys_path=keys) == "abc123"


def test_load_token_env_takes_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("AURORA_KEY", "from-env")
    keys = tmp_path / "keys.env"
    keys.write_text("aurora_key=from-file", encoding="utf-8")
    assert load_token(keys_path=keys) == "from-env"


def test_load_token_missing_raises(tmp_path, monkeypatch):
    for var in ("AURORA_KEY", "aurora_key"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(AuroraAPIError):
        load_token(keys_path=tmp_path / "absent.env")


def test_token_set_as_header():
    session = FakeSession()
    AuroraScenarioExplorer(token="secret", cache_dir=None, session=session)
    assert session.headers["Private-Token"] == "secret"


def test_scenarios_parsed(api):
    scenarios = api.scenarios()
    assert len(scenarios) == 3
    assert all(isinstance(s, Scenario) for s in scenarios)


def test_find_scenarios_filters_and_sorts(api):
    se = api.find_scenarios(region="bra_se", sensitivity="central")
    assert [s.name for s in se] == ["Brazil Q2 26 (Central)", "Brazil Q1 26 (Central)"]


def test_latest_scenario_picks_most_recent(api):
    sc = api.latest_scenario("bra_se", "central")
    assert sc.hash == "new-hash"


def test_latest_scenario_unknown_raises(api):
    with pytest.raises(AuroraAPIError):
        api.latest_scenario("bra_xx", "central")


def test_data_files_lists_columns_and_units(api):
    sc = api.latest_scenario("bra_se", "central")
    files = api.data_files(sc)
    assert files[0].key == ("system", "1h")
    assert "Wholesale market price" in files[0].columns
    assert files[0].units["Time (UTC)"] == "UTC"


def test_download_drops_units_row_and_parses(api):
    sc = api.latest_scenario("bra_se", "central")
    df = api.download(sc, "system", "1h")
    assert list(df.columns) == ["Time (UTC)", "Time (Local)", "Wholesale market price"]
    assert len(df) == 2  # linha de unidades descartada
    assert df["Wholesale market price"].iloc[0] == pytest.approx(252.9)
    assert df.attrs["currency"] == "brl2025"


def test_download_unknown_file_raises(api):
    sc = api.latest_scenario("bra_se", "central")
    with pytest.raises(AuroraAPIError):
        api.download(sc, "system", "9z")


def test_http_error_maps_to_aurora_error():
    api = AuroraScenarioExplorer(
        token="x", cache_dir=None, session=FakeSession(fail_status=401)
    )
    with pytest.raises(AuroraAPIError, match="401"):
        api.scenarios()


# --------------------------------------------------------------------- adapter
def _make_1h_df(year: int) -> pd.DataFrame:
    """CSV system-1h sintético (já parseado) cobrindo o ano inteiro em horário local."""
    idx = pd.date_range(f"{year}-01-01 00:00:00", f"{year}-12-31 23:00:00", freq="h")
    return pd.DataFrame(
        {
            "Time (UTC)": (idx + pd.Timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"),
            "Time (Local)": idx.strftime("%Y-%m-%d %H:%M:%S"),
            "Wholesale market price": np.linspace(100.0, 300.0, len(idx)),
        }
    )


class FakeClient:
    """Cliente Aurora falso para o adapter de preço (sem rede)."""

    def __init__(self, df: pd.DataFrame, *, default_currency: str = "brl2025"):
        self._df = df
        self.default_currency = default_currency

    def latest_scenario(self, region: str, sensitivity: str = "central") -> Scenario:
        return Scenario(
            region_code=region,
            sensitivity=sensitivity,
            name="Brazil Q2 26 (Central)",
            hash="abcd1234efgh",
            publication_date="2026-04-23T13:36:08.000Z",
            default_currency=self.default_currency,
            products=("bra_power_and_res",),
            data_url_base="x/",
            meta_url="x/meta.json",
        )

    def find_scenarios(self, *, region, sensitivity=None, name_contains=None):
        return [self.latest_scenario(region, sensitivity or "central")]

    def download(self, scenario, data_type, granularity, *, currency=None):
        assert (data_type, granularity) == ("system", "1h")
        return self._df.copy()


def test_adapter_returns_8760_price_profile():
    client = FakeClient(_make_1h_df(2027))
    profile = load_price_aurora_api(2027, "SE", client=client)
    assert profile.prices_brl_per_mwh.shape == (HOURS_PER_YEAR,)
    assert profile.bq_submarket == "SE"
    assert profile.bq_year == 2027
    assert profile.source.startswith("aurora_api_bra_se_central_abcd1234")
    assert (profile.prices_brl_per_mwh >= 0).all()


def test_adapter_leap_year_drops_feb29():
    client = FakeClient(_make_1h_df(2028))  # bissexto: 8784 horas
    profile = load_price_aurora_api(2028, "S", client=client)
    assert profile.prices_brl_per_mwh.shape == (HOURS_PER_YEAR,)


@pytest.mark.parametrize(
    "submarket,region",
    [("SE", "bra_se"), ("S", "bra_su"), ("NE", "bra_ne"), ("N", "bra_no")],
)
def test_adapter_maps_each_submarket(submarket, region):
    client = FakeClient(_make_1h_df(2027))
    profile = load_price_aurora_api(2027, submarket, client=client)
    assert f"aurora_api_{region}_" in profile.source


def test_adapter_partial_year_raises():
    partial = _make_1h_df(2026)
    partial = partial[pd.to_datetime(partial["Time (Local)"]).dt.month >= 10]
    client = FakeClient(partial)
    with pytest.raises(DataSourceError, match="parcial"):
        load_price_aurora_api(2026, "SE", client=client)


def test_adapter_missing_year_raises():
    client = FakeClient(_make_1h_df(2027))
    with pytest.raises(DataSourceError, match="ausente"):
        load_price_aurora_api(2030, "SE", client=client)


def test_adapter_bad_submarket_raises():
    client = FakeClient(_make_1h_df(2027))
    with pytest.raises(DataSourceError, match="inválido"):
        load_price_aurora_api(2027, "XX", client=client)
