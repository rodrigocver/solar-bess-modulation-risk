"""Cliente da EOS Scenario Explorer API (Aurora Energy Research).

Base URL
--------
``https://api.auroraer.com/scenarioExplr``

Autenticação
------------
Header ``Private-Token: <token>``. O token é lido de ``dados/keys.env``
(variável ``aurora_key``) ou da variável de ambiente ``AURORA_KEY`` /
``aurora_key``. Crie um token em https://eos.auroraer.com/dragonfly/settings.

Fluxo de uso
------------
>>> api = AuroraScenarioExplorer()
>>> sc = api.latest_scenario("bra_se", "central")      # cenário mais recente
>>> files = api.data_files(sc)                          # arquivos disponíveis
>>> df = api.download(sc, "system", "1h")               # preço horário (BRL/MWh)

Formato dos CSV
---------------
A linha 1 é o cabeçalho e a linha 2 traz as unidades (``BRL/MWh``, ``UTC`` …).
A linha de unidades é descartada na leitura; as unidades ficam acessíveis via
:meth:`AuroraScenarioExplorer.data_files` (campo ``units``) e em ``df.attrs``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

AURORA_BASE_URL = "https://api.auroraer.com/scenarioExplr"
DEFAULT_KEYS_PATHS = (Path("dados/.env"), Path("dados/keys.env"))
DEFAULT_CACHE_DIR = Path("dados/aurora_cache")
TOKEN_ENV_VARS = ("AURORA_KEY", "aurora_key")
TOKEN_KEYS_NAME = "aurora_key"


class AuroraAPIError(Exception):
    """Falha de autenticação, rede, permissão ou recurso ausente na API Aurora."""


@dataclass(frozen=True)
class Scenario:
    """Um cenário publicado (região + sensibilidade + data de publicação)."""

    region_code: str
    sensitivity: str
    name: str
    hash: str
    publication_date: str
    default_currency: str
    products: tuple[str, ...]
    data_url_base: str
    meta_url: str
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def label(self) -> str:
        return f"{self.region_code}/{self.sensitivity} — {self.name} ({self.publication_date[:10]})"


@dataclass(frozen=True)
class DataFile:
    """Um arquivo de dados disponível para um cenário (vindo do meta.json)."""

    data_type: str
    granularity: str
    filename: str
    columns: tuple[str, ...]
    units: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str]:
        return (self.data_type, self.granularity)


def load_token(
    *,
    keys_path: str | Path | None = None,
    env_vars: tuple[str, ...] = TOKEN_ENV_VARS,
) -> str:
    """Retorna o token Aurora a partir do ambiente ou de um arquivo ``.env``.

    A variável de ambiente tem precedência. Se ``keys_path`` for ``None``,
    procura nos caminhos padrão (``dados/.env`` e ``dados/keys.env``). Lança
    :class:`AuroraAPIError` se nenhum token for encontrado.
    """
    for var in env_vars:
        value = os.environ.get(var)
        if value and value.strip():
            return value.strip()

    candidates = [Path(keys_path)] if keys_path is not None else list(DEFAULT_KEYS_PATHS)
    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8-sig").replace("\r", "")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key.strip() == TOKEN_KEYS_NAME:
                token = val.strip().strip('"').strip("'")
                if token:
                    return token

    searched = ", ".join(str(p) for p in candidates)
    raise AuroraAPIError(
        f"Token Aurora não encontrado. Defina a env var {env_vars[0]} ou "
        f"adicione 'aurora_key=<token>' em um destes arquivos: {searched}."
    )


class AuroraScenarioExplorer:
    """Cliente fino para a EOS Scenario Explorer API."""

    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str = AURORA_BASE_URL,
        cache_dir: str | Path | None = DEFAULT_CACHE_DIR,
        session: requests.Session | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._token = token or load_token()
        self._session = session or requests.Session()
        self._session.headers.update({"Private-Token": self._token})
        self._metadata: dict | None = None
        self._meta_cache: dict[str, dict] = {}

    # ------------------------------------------------------------------ HTTP
    def _get(self, path: str) -> requests.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            resp = self._session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise AuroraAPIError(f"Erro de rede ao acessar {url}: {exc}") from exc

        if resp.status_code == 200:
            return resp
        messages = {
            401: "Não autorizado — verifique o Private-Token (aurora_key).",
            403: "Sem permissão para acessar este recurso.",
            404: "Recurso não encontrado — verifique região/sensibilidade/arquivo.",
        }
        detail = messages.get(resp.status_code, resp.text[:200])
        raise AuroraAPIError(f"HTTP {resp.status_code} em {url}: {detail}")

    # -------------------------------------------------------------- metadata
    def metadata(self, *, refresh: bool = False) -> dict:
        """Resposta crua de ``GET /v1/scenarios`` (com cache em instância)."""
        if self._metadata is None or refresh:
            self._metadata = self._get("v1/scenarios").json()
        return self._metadata

    def scenarios(self, *, refresh: bool = False) -> list[Scenario]:
        raw_scenarios = self.metadata(refresh=refresh).get("scenarios", [])
        return [_to_scenario(s) for s in raw_scenarios]

    def regions(self) -> list[dict]:
        return self.metadata().get("regions", [])

    def currencies(self) -> list[dict]:
        return self.metadata().get("currencies", [])

    def find_scenarios(
        self,
        *,
        region: str | None = None,
        sensitivity: str | None = None,
        name_contains: str | None = None,
    ) -> list[Scenario]:
        """Filtra cenários por região/sensibilidade/nome, mais recentes primeiro."""
        result = self.scenarios()
        if region is not None:
            result = [s for s in result if s.region_code == region]
        if sensitivity is not None:
            result = [s for s in result if s.sensitivity == sensitivity]
        if name_contains is not None:
            needle = name_contains.lower()
            result = [s for s in result if needle in s.name.lower()]
        return sorted(result, key=lambda s: s.publication_date, reverse=True)

    def latest_scenario(self, region: str, sensitivity: str = "central") -> Scenario:
        """Cenário publicado mais recentemente para ``region``/``sensitivity``."""
        matches = self.find_scenarios(region=region, sensitivity=sensitivity)
        if not matches:
            raise AuroraAPIError(
                f"Nenhum cenário para região={region!r}, sensibilidade={sensitivity!r}. "
                f"Use .find_scenarios() para ver o que está disponível."
            )
        return matches[0]

    # ------------------------------------------------------------------ meta
    def _meta(self, scenario: Scenario) -> dict:
        if scenario.meta_url not in self._meta_cache:
            self._meta_cache[scenario.meta_url] = self._get(scenario.meta_url).json()
        return self._meta_cache[scenario.meta_url]

    def years(self, scenario: Scenario) -> list[int]:
        return self._meta(scenario).get("years", [])

    def data_files(self, scenario: Scenario) -> list[DataFile]:
        """Lista os arquivos de dados disponíveis para ``scenario``."""
        files: list[DataFile] = []
        for d in self._meta(scenario).get("dataDefinitions", []):
            structure = d.get("structure", [])
            columns = tuple(c.get("name") for c in structure)
            units = {
                c.get("name"): c.get("unit")
                for c in structure
                if c.get("unit")
            }
            files.append(
                DataFile(
                    data_type=d.get("type"),
                    granularity=d.get("granularity"),
                    filename=d.get("filename"),
                    columns=columns,
                    units=units,
                )
            )
        return files

    def _find_data_file(
        self, scenario: Scenario, data_type: str, granularity: str
    ) -> DataFile:
        for f in self.data_files(scenario):
            if f.data_type == data_type and f.granularity == granularity:
                return f
        available = sorted((f.data_type, f.granularity) for f in self.data_files(scenario))
        raise AuroraAPIError(
            f"Arquivo type={data_type!r} granularity={granularity!r} indisponível "
            f"para {scenario.label}. Disponíveis: {available}"
        )

    # -------------------------------------------------------------- download
    def download(
        self,
        scenario: Scenario,
        data_type: str,
        granularity: str,
        *,
        currency: str | None = None,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """Baixa um arquivo de dados como :class:`pandas.DataFrame`.

        Parameters
        ----------
        scenario : Scenario
            Cenário obtido via :meth:`latest_scenario` ou :meth:`find_scenarios`.
        data_type : str
            ``system``, ``technology`` ou ``technology-aggregated``.
        granularity : str
            ``1h``, ``1m``, ``1q`` ou ``1y`` (varia por ``data_type``).
        currency : str, optional
            Código de moeda. Padrão: ``scenario.default_currency``.
        use_cache : bool
            Se ``True`` e ``cache_dir`` definido, lê/grava o CSV em disco.
        """
        data_file = self._find_data_file(scenario, data_type, granularity)
        cur = currency or scenario.default_currency
        filename = data_file.filename.replace("{currency}", cur)

        text = self._read_csv_text(scenario, filename, use_cache=use_cache)
        df = _parse_eos_csv(text)
        df.attrs["units"] = {
            col: unit.replace("{currency}", cur)
            for col, unit in data_file.units.items()
        }
        df.attrs["scenario"] = scenario.label
        df.attrs["data_type"] = data_type
        df.attrs["granularity"] = granularity
        df.attrs["currency"] = cur
        return df

    def _read_csv_text(
        self, scenario: Scenario, filename: str, *, use_cache: bool
    ) -> str:
        cache_path: Path | None = None
        if use_cache and self.cache_dir is not None:
            cache_path = (
                self.cache_dir
                / scenario.hash
                / scenario.region_code
                / scenario.sensitivity
                / filename
            )
            if cache_path.exists():
                return cache_path.read_text(encoding="utf-8")

        resp = self._get(f"{scenario.data_url_base}{filename}")
        text = resp.text
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(text, encoding="utf-8")
        return text


# --------------------------------------------------------------------- helpers
def _to_scenario(s: dict) -> Scenario:
    return Scenario(
        region_code=s.get("regionCode", ""),
        sensitivity=s.get("sensitivity", ""),
        name=s.get("name", ""),
        hash=s.get("hash", ""),
        publication_date=s.get("publicationDate", ""),
        default_currency=s.get("defaultCurrency", ""),
        products=tuple(s.get("products", []) or ()),
        data_url_base=s.get("dataUrlBase", ""),
        meta_url=s.get("metaUrl", ""),
        raw=s,
    )


def _parse_eos_csv(text: str) -> pd.DataFrame:
    """Lê um CSV EOS, descartando a linha de unidades (2ª linha física)."""
    # header na linha 0, unidades na linha 1, dados a partir da linha 2.
    return pd.read_csv(StringIO(text), skiprows=[1])
