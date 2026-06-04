"""Unit tests for report chart contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from solar_bess_risk.must_optimizer import MustEvaluationPoint, MustOptimizationResult
from solar_bess_risk.report_charts import build_payback_curve, must_sensitivity_chart


def test_must_sensitivity_chart_limits_x_axis_and_explains_metrics():
    sweep = [
        MustEvaluationPoint(
            reduction_pct=pct,
            must_mw=100.0 * (1.0 - pct),
            delta_must_mw=100.0 * pct,
            tust_savings_brl_per_yr=1_000_000.0 * pct,
            net_balance_com_brl=-2_000_000.0 * pct,
            net_balance_delta_vs_baseline_brl=-2_000_000.0 * pct,
            net_benefit_brl_per_yr=-1_000_000.0 * pct,
            curtailment_lost_mwh=0.0,
        )
        for pct in (0.0, 0.05, 0.10, 0.15, 0.20)
    ]
    result = MustOptimizationResult(
        scenario_label="B",
        duration_h=4,
        mwac=100.0,
        tust_brl_per_kw_month=7.23,
        tust_is_default=True,
        optimal_reduction_pct=0.05,
        optimal_must_mw=95.0,
        optimal_net_benefit_brl_per_yr=-50_000.0,
        sweep=sweep,
    )

    fig = must_sensitivity_chart(result)

    assert fig.layout.xaxis.range == pytest.approx((0, 15))
    assert fig.layout.yaxis.range == pytest.approx((-10_000_000, 10_000_000))
    assert "Benefício líquido = economia de TUST + Δ saldo líquido" in fig.layout.title.text
    assert "saldo base sem redução" in fig.layout.title.text
    assert fig.data[0].name == "Benefício líquido (TUST + Δ saldo)"
    assert fig.data[2].name == "Δ saldo líquido (vs. 0%)"


def test_payback_curve_uses_simple_nominal_cashflow():
    result = SimpleNamespace(
        scenario=SimpleNamespace(label="B"),
        annual_savings_brl=90.0,
        annual_gross_savings_brl=100.0,
        annual_o_and_m_brl=10.0,
        capex_brl=180.0,
    )

    fig = build_payback_curve([result], useful_life_years=3)

    assert list(fig.data[0].y) == pytest.approx([90.0, 180.0, 270.0])
    assert "Payback Simples" in fig.layout.title.text
