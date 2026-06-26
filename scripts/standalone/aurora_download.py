"""Baixa dados da EOS Scenario Explorer (Aurora) para CSV local.

Exemplos
--------
Listar cenários do Brasil (SE, central):
    python scripts/aurora_download.py --region bra_se --sensitivity central --list

Ver arquivos disponíveis no cenário mais recente:
    python scripts/aurora_download.py --region bra_se --files

Baixar o preço horário (system 1h) do cenário mais recente:
    python scripts/aurora_download.py --region bra_se --type system --granularity 1h \
        --out dados/aurora/bra_se_central_system_1h.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

from solar_bess_risk.aurora_api import AuroraAPIError, AuroraScenarioExplorer


def main() -> int:
    parser = argparse.ArgumentParser(description="Download de dados da Aurora EOS Scenario Explorer.")
    parser.add_argument("--region", default="bra_se", help="regionCode (ex.: bra_se, bra_ne, bra_no, bra_su)")
    parser.add_argument("--sensitivity", default="central", help="central | low | high")
    parser.add_argument("--type", dest="data_type", help="system | technology | technology-aggregated")
    parser.add_argument("--granularity", default="1y", help="1h | 1m | 1q | 1y")
    parser.add_argument("--currency", default=None, help="código de moeda (padrão: do cenário)")
    parser.add_argument("--out", type=Path, help="caminho do CSV de saída")
    parser.add_argument("--list", action="store_true", help="lista cenários e sai")
    parser.add_argument("--files", action="store_true", help="lista arquivos do cenário mais recente e sai")
    args = parser.parse_args()

    try:
        api = AuroraScenarioExplorer()

        if args.list:
            for sc in api.find_scenarios(region=args.region, sensitivity=args.sensitivity):
                print(sc.label)
            return 0

        scenario = api.latest_scenario(args.region, args.sensitivity)
        print(f"Cenário: {scenario.label}  [moeda padrão: {scenario.default_currency}]")

        if args.files or not args.data_type:
            print("Arquivos disponíveis (type / granularity / colunas):")
            for f in api.data_files(scenario):
                print(f"  {f.data_type:22} {f.granularity:3}  {list(f.columns)}")
            if not args.data_type:
                return 0
            return 0

        df = api.download(
            scenario,
            args.data_type,
            args.granularity,
            currency=args.currency,
        )
        print(f"Linhas: {len(df)}  Colunas: {list(df.columns)}")
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(args.out, index=False)
            print(f"Salvo em: {args.out}")
        else:
            print(df.head(10).to_string(index=False))
        return 0

    except AuroraAPIError as exc:
        print(f"ERRO: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
