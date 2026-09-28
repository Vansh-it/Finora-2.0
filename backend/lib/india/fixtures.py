"""Fixture / development datasets for India dashboards.

All fixture data is FICTIONAL and clearly labeled. The fixture companies are:
  - Finora Industries Ltd  (corporate, NSE: FININD)
  - Finora Bank Ltd        (bank, NSE: FINBANK)
  - Finora Finance Ltd     (NBFC, NSE: FINFIN)

Fixtures exercise: positive numbers, negative numbers, missing values (null +
reason), N/A metrics, consolidated/standalone scopes, five-year histories and
red-flag scenarios. Fixture sources carry is_fixture=True and every market
data snapshot carries data_status="FIXTURE". These are NEVER presented as
live research for real companies.

KNOWN DEFECT — the corporate balance sheet does not reconcile
-----------------------------------------------------------
``Finora Industries Ltd`` FY2026 balance sheet is internally inconsistent:

  * ``total_current_assets``     is reported as 255.8B but its six component
    lines sum to 256.1B  (delta -0.3B)
  * ``total_non_current_assets`` is reported as 283.8B but its six component
    lines sum to 284.6B  (delta -0.8B)
  * ``total_assets`` 539.6B exceeds liabilities + equity 517.4B by 22.2B

This is left in place deliberately: rebalancing would move every India demo
KPI that depends on the balance sheet (ROE, book value per share, leverage,
ROA, debt ratios), and the demo numbers are currently treated as the
published baseline. ``TestFixtureIntegrity`` in ``tests/test_india_metrics.py``
pins the exact discrepancy so that any future change to it is deliberate
rather than accidental. Reported subtotals remain authoritative over derived
ones in ``MetricEngine.resolve_input``, so these gaps do not silently corrupt
downstream ratios -- they are visible as the difference between a reported
subtotal and the sum of its components.
"""

from __future__ import annotations

from typing import Optional

from lib.core.canonical_models import (
    AuditStatus,
    CanonicalCompanyData,
    CanonicalCompanyIdentity,
    CanonicalMarketData,
    CanonicalMetric,
    CanonicalOwnership,
    CanonicalPeriod,
    CanonicalSource,
    CanonicalStatement,
    MetricStatus,
    Scope,
)
from lib.core.entity_types import EntityType

FIXTURE_FLAG = "FIXTURE"

_YEARS = ["FY2022", "FY2023", "FY2024", "FY2025", "FY2026"]


def _src(sid: str, name: str, doc: str, used_for: str) -> CanonicalSource:
    return CanonicalSource(
        source_id=sid,
        source_name=name,
        source_type=FIXTURE_FLAG,
        trust_tier="PRIMARY",
        document_type=FIXTURE_FLAG,
        document_title=f"[DEV FIXTURE] {doc}",
        period="FY2022–FY2026",
        published_date="2026-06-30",
        url="",
        retrieved_at="2026-09-01",
        used_for=used_for,
        status="FIXTURE",
        is_fixture=True,
    )


def _m(metric_id: str, period: str, value: Optional[float], *,
       scope: str = Scope.CONSOLIDATED.value,
       status: str = MetricStatus.REPORTED.value,
       source: str = "src_fixture_ar",
       unit: str = "MONEY",
       reason: str = "",
       formula: str = "") -> CanonicalMetric:
    return CanonicalMetric(
        metric_id=metric_id, period=period, value=value, currency="INR",
        period_type="FY", statement_scope=scope, status=status,
        source_ids=[source] if value is not None else [],
        reason=reason, unit_type=unit, formula=formula,
        audit_status=AuditStatus.AUDITED.value,
    )


def _periods() -> list[CanonicalPeriod]:
    return [
        CanonicalPeriod(label=y, kind="FY", fiscal_year=int(y[2:]),
                        audit_status=AuditStatus.AUDITED.value)
        for y in _YEARS
    ]


def _market(price: float, change: float, mcap: float) -> CanonicalMarketData:
    return CanonicalMarketData(
        price=price, previous_close=round(price / (1 + change / 100), 2),
        price_date="2026-09-25", percent_change=change,
        market_cap=mcap, shares_outstanding=None, currency="INR",
        exchange="NSE", source_id="src_fixture_market",
        source_name="Finora Dev Fixture Market Data",
        data_status=FIXTURE_FLAG, is_fixture=True,
    )


def _identity(name: str, entity: EntityType, nse: str, sector: str,
              industry: str, desc: str) -> CanonicalCompanyIdentity:
    return CanonicalCompanyIdentity(
        name=name, country="IN", legal_name=name,
        nse_symbol=nse, bse_code="5XXXXX", isin="INE999X00010",
        cin="U99999MH2010PLC000000", primary_exchange="NSE",
        sector=sector, industry=industry, currency="INR",
        entity_type=entity.value, description=desc,
        reporting_standard="Ind AS",
    )


# ══════════════════════════════════════════════════════════════════════════
# CORPORATE FIXTURE — Finora Industries Ltd
# Scenario: decent business with a worsening receivables/FCF story to
# exercise red flags; FY2026 standalone exists for scope switching.
# ══════════════════════════════════════════════════════════════════════════

def _corp_income(data: CanonicalCompanyData) -> None:
    stmt = CanonicalStatement(statement_type="income_statement")
    series = {
        "revenue": [612_000_000_000, 682_000_000_000, 748_000_000_000,
                     815_000_000_000, 878_000_000_000],
        "other_income": [9_800_000_000, 11_200_000_000, 10_900_000_000,
                          12_600_000_000, 14_100_000_000],
        "cost_of_materials": [391_000_000_000, 443_000_000_000, 486_000_000_000,
                               538_000_000_000, 586_000_000_000],
        "purchases_stock_in_trade": [8_200_000_000, 9_100_000_000, 9_800_000_000,
                                      10_400_000_000, 11_000_000_000],
        "changes_in_inventories": [-1_100_000_000, 1_400_000_000, -900_000_000,
                                    1_800_000_000, 2_200_000_000],
        "employee_benefits": [64_000_000_000, 70_500_000_000, 77_800_000_000,
                               84_900_000_000, 92_300_000_000],
        "finance_costs": [18_500_000_000, 19_800_000_000, 21_600_000_000,
                           24_900_000_000, 28_700_000_000],
        "depreciation_amortisation": [28_400_000_000, 31_200_000_000, 34_100_000_000,
                                       37_800_000_000, 41_200_000_000],
        "other_expenses": [58_900_000_000, 63_400_000_000, 68_900_000_000,
                            74_200_000_000, 80_100_000_000],
        "exceptional_items": [None, None, None, None, 4_800_000_000],
        "pbt": [50_000_000_000, 55_800_000_000, 57_800_000_000,
                 56_600_000_000, 42_800_000_000],
        "current_tax": [12_800_000_000, 14_300_000_000, 14_800_000_000,
                         14_500_000_000, 11_000_000_000],
        "deferred_tax": [1_100_000_000, 900_000_000, 1_200_000_000,
                          1_500_000_000, 2_100_000_000],
        "net_profit": [36_100_000_000, 40_600_000_000, 41_800_000_000,
                        40_600_000_000, 29_700_000_000],
        "oci": [-1_400_000_000, 900_000_000, -600_000_000, 1_200_000_000, -800_000_000],
        # EPS ties to PAT / shares outstanding exactly (as real filings do):
        # shares = share_capital / FV 10 → 1.3050bn, 1.3240bn, 1.3290bn …
        "eps_basic": [27.66, 30.66, 31.45, 30.55, 22.35],
        "eps_diluted": [27.36, 30.40, 31.18, 30.32, 22.10],
    }
    for mid, values in series.items():
        for y, v in zip(_YEARS, values):
            unit = "PER_SHARE" if mid.startswith("eps_") else "MONEY"
            stmt.add(_m(mid, y, v, unit=unit))
    data.statements["income_statement"] = stmt


def _corp_balance(data: CanonicalCompanyData) -> None:
    stmt = CanonicalStatement(statement_type="balance_sheet")
    series = {
        "cash": [21_000_000_000, 18_500_000_000, 16_200_000_000,
                  12_800_000_000, 9_400_000_000],
        "bank_balances": [8_500_000_000, 7_200_000_000, 6_100_000_000,
                           5_200_000_000, 4_100_000_000],
        "current_investments": [12_300_000_000, 11_800_000_000, 10_400_000_000,
                                 9_100_000_000, 8_300_000_000],
        "non_current_investments": [18_000_000_000, 19_500_000_000, 21_000_000_000,
                                     22_400_000_000, 23_800_000_000],
        "trade_receivables": [58_400_000_000, 68_900_000_000, 82_600_000_000,
                               101_200_000_000, 132_400_000_000],
        "inventory": [61_200_000_000, 67_800_000_000, 71_500_000_000,
                       76_900_000_000, 88_400_000_000],
        "other_current_assets": [9_800_000_000, 10_900_000_000, 11_800_000_000,
                                  12_600_000_000, 13_500_000_000],
        "total_current_assets": [171_200_000_000, 184_600_000_000, 198_600_000_000,
                                  217_800_000_000, 255_800_000_000],
        "ppe": [148_000_000_000, 162_000_000_000, 178_000_000_000,
                 191_000_000_000, 205_000_000_000],
        "cwip": [12_400_000_000, 15_100_000_000, 18_900_000_000,
                  22_300_000_000, 26_800_000_000],
        "intangibles": [6_800_000_000, 7_400_000_000, 8_100_000_000,
                         8_600_000_000, 9_200_000_000],
        "goodwill": [4_200_000_000, 4_200_000_000, 4_200_000_000,
                      4_200_000_000, 4_200_000_000],
        "other_non_current_assets": [11_000_000_000, 12_100_000_000, 13_300_000_000,
                                      14_400_000_000, 15_600_000_000],
        "total_non_current_assets": [200_400_000_000, 220_300_000_000, 242_600_000_000,
                                      260_500_000_000, 283_800_000_000],
        "total_assets": [371_600_000_000, 404_900_000_000, 441_200_000_000,
                          478_300_000_000, 539_600_000_000],
        "trade_payables": [44_800_000_000, 49_100_000_000, 53_400_000_000,
                            58_900_000_000, 66_200_000_000],
        "short_term_borrowings": [12_400_000_000, 14_800_000_000, 18_900_000_000,
                                   26_800_000_000, 38_400_000_000],
        "current_debt": [6_800_000_000, 7_600_000_000, 8_900_000_000,
                          10_400_000_000, 12_100_000_000],
        "other_current_liabilities": [38_600_000_000, 42_100_000_000, 45_800_000_000,
                                       49_600_000_000, 54_800_000_000],
        "total_current_liabilities": [102_600_000_000, 113_600_000_000, 127_000_000_000,
                                       145_700_000_000, 171_500_000_000],
        "long_term_borrowings": [42_000_000_000, 46_800_000_000, 54_600_000_000,
                                  63_200_000_000, 74_900_000_000],
        "other_non_current_liabilities": [18_400_000_000, 19_600_000_000, 20_800_000_000,
                                           21_900_000_000, 23_400_000_000],
        "total_non_current_liabilities": [60_400_000_000, 66_400_000_000, 75_400_000_000,
                                           85_100_000_000, 98_300_000_000],
        "share_capital": [13_050_000_000, 13_240_000_000, 13_290_000_000,
                           13_290_000_000, 13_290_000_000],
        "reserves_surplus": [195_550_000_000, 211_660_000_000, 222_510_000_000,
                              226_600_000_000, 234_310_000_000],
        "minority_interest": [0.0, 0.0, 0.0, 0.0, 0.0],
        "total_equity": [208_600_000_000, 224_900_000_000, 235_800_000_000,
                          239_890_000_000, 247_600_000_000],
    }
    for mid, values in series.items():
        for y, v in zip(_YEARS, values):
            stmt.add(_m(mid, y, v))
    data.statements["balance_sheet"] = stmt


def _corp_cashflow(data: CanonicalCompanyData) -> None:
    stmt = CanonicalStatement(statement_type="cash_flow")
    series = {
        "operating_cash_flow": [54_200_000_000, 58_900_000_000, 61_400_000_000,
                                 52_800_000_000, 31_600_000_000],
        "capex": [31_000_000_000, 34_500_000_000, 38_200_000_000,
                   42_100_000_000, 47_800_000_000],
        "investing_cash_flow": [-29_800_000_000, -33_100_000_000, -36_400_000_000,
                                 -40_600_000_000, -45_900_000_000],
        "financing_cash_flow": [-18_900_000_000, -21_400_000_000, -19_800_000_000,
                                 -9_200_000_000, 12_400_000_000],
        "dividends_paid": [9_800_000_000, 11_200_000_000, 12_100_000_000,
                            12_600_000_000, 10_400_000_000],
        "interest_paid": [17_200_000_000, 18_900_000_000, 20_800_000_000,
                           23_900_000_000, 27_800_000_000],
        "debt_raised": [11_400_000_000, 15_800_000_000, 21_900_000_000,
                         30_200_000_000, 41_600_000_000],
        "debt_repaid": [8_900_000_000, 10_400_000_000, 11_600_000_000,
                         12_800_000_000, 14_900_000_000],
        "share_buybacks": [None, None, None, None, None],
        "net_change_in_cash": [5_500_000_000, 4_400_000_000, 5_200_000_000,
                                3_000_000_000, -1_900_000_000],
    }
    for mid, values in series.items():
        for y, v in zip(_YEARS, values):
            reason = "No buyback programme disclosed" if mid == "share_buybacks" and v is None else ""
            stmt.add(_m(mid, y, v, reason=reason))
    data.statements["cash_flow"] = stmt


def _merge_scope(
    data: CanonicalCompanyData,
    statement_type: str,
    extra: CanonicalStatement,
) -> None:
    """Merge another scope's metrics into the company's existing statement.

    Safe because the canonical store is scope-keyed: adding STANDALONE
    ``revenue|FY2026`` alongside CONSOLIDATED ``revenue|FY2026`` stores two
    distinct facts rather than one overwriting the other.
    """
    target = data.statements[statement_type]
    for metric in extra.metrics.values():
        target.add(metric)
    for line in extra.line_items:
        if line not in target.line_items:
            target.line_items.append(line)
    for period in extra.periods:
        if period not in target.periods:
            target.periods.append(period)


def _corp_standalone(data: CanonicalCompanyData) -> None:
    """FY2026 standalone (parent-only) statements, for scope switching.

    Indian filings publish both bases. The parent is materially smaller than
    the group, and — the point of the fixture — the parent's cash generation is
    healthy while the group's is not: consolidated FY2026 FCF is -16.2B while
    standalone FCF is +26.2B. A user who switches scope should be able to see
    that the FCF red flag belongs to the group, not the parent.

    Unlike the consolidated statements, these balance exactly. The consolidated
    balance sheet carries a known, documented 22.2B imbalance (see
    ``TestFixtureIntegrity``); repeating that defect here would make it
    impossible to tell an engine bug from a fixture bug.
    """
    S = Scope.STANDALONE.value
    P = "FY2026"

    income = CanonicalStatement(statement_type="income_statement")
    income_series = {
        "revenue": 596_000_000_000,
        "other_income": 9_800_000_000,
        "cost_of_materials": 401_000_000_000,
        "purchases_stock_in_trade": 0.0,
        "changes_in_inventories": 1_400_000_000,
        "employee_benefits": 58_700_000_000,
        "finance_costs": 9_800_000_000,
        "depreciation_amortisation": 17_900_000_000,
        "other_expenses": 46_300_000_000,
        # PBT ties to the engine's own EBITDA less finance costs:
        #   EBITDA = 596.0 - (58.7 + 46.3 + 401.0 + 0.0 + 1.4) = 88.6B
        #   EBIT   = 88.6 - 17.9 = 70.7B ; PBT = 70.7 - 9.8 = 60.9B
        "pbt": 60_900_000_000,
        "current_tax": 15_100_000_000,
        "deferred_tax": 600_000_000,
        # PAT = 60.9 - 15.1 - 0.6 = 45.2B
        "net_profit": 45_200_000_000,
        "oci": -400_000_000,
        # EPS = 45.2B / 1.329bn shares (13.29B capital at FV 10)
        "eps_basic": 34.01,
        "eps_diluted": 33.70,
    }
    for mid, v in income_series.items():
        income.add(_m(mid, P, v, scope=S,
                      unit="PER_SHARE" if mid.startswith("eps_") else "MONEY"))
    income.add(_m("exceptional_items", P, None, scope=S,
                  reason="No exceptional items disclosed in standalone accounts"))
    _merge_scope(data, "income_statement", income)

    balance = CanonicalStatement(statement_type="balance_sheet")
    balance_series = {
        "cash": 6_200_000_000,
        "bank_balances": 2_900_000_000,
        "current_investments": 3_400_000_000,
        "trade_receivables": 48_600_000_000,
        "inventory": 31_200_000_000,
        "other_current_assets": 5_700_000_000,
        # TCA = 98.0B
        "total_current_assets": 98_000_000_000,
        "ppe": 84_300_000_000,
        "cwip": 9_100_000_000,
        "intangibles": 1_800_000_000,
        # Goodwill arises only on consolidation; the parent carries none.
        "goodwill": 0.0,
        "other_non_current_assets": 4_200_000_000,
        # TNCA = 99.4B
        "total_non_current_assets": 99_400_000_000,
        "total_assets": 197_400_000_000,
        "trade_payables": 24_800_000_000,
        "short_term_borrowings": 11_200_000_000,
        "current_debt": 4_600_000_000,
        "other_current_liabilities": 18_900_000_000,
        # TCL = 59.5B
        "total_current_liabilities": 59_500_000_000,
        "long_term_borrowings": 22_400_000_000,
        "other_non_current_liabilities": 7_300_000_000,
        # TNCL = 29.7B
        "total_non_current_liabilities": 29_700_000_000,
        "share_capital": 13_290_000_000,
        # Equity is the plug: 197.4 - 59.5 - 29.7 = 108.2B
        "reserves_surplus": 94_910_000_000,
        "minority_interest": 0.0,
        "total_equity": 108_200_000_000,
    }
    for mid, v in balance_series.items():
        balance.add(_m(mid, P, v, scope=S))
    _merge_scope(data, "balance_sheet", balance)

    cash = CanonicalStatement(statement_type="cash_flow")
    cash_series = {
        "operating_cash_flow": 44_800_000_000,
        "capex": 18_600_000_000,
        "investing_cash_flow": -16_900_000_000,
        "financing_cash_flow": -30_300_000_000,
        "dividends_paid": 8_900_000_000,
        "interest_paid": 9_600_000_000,
        "debt_raised": 6_200_000_000,
        "debt_repaid": 22_900_000_000,
        "share_buybacks": None,
        # 44.8 - 16.9 - 30.3 = -2.4B
        "net_change_in_cash": -2_400_000_000,
    }
    for mid, v in cash_series.items():
        reason = "No buyback programme disclosed" if mid == "share_buybacks" else ""
        cash.add(_m(mid, P, v, scope=S, reason=reason))
    _merge_scope(data, "cash_flow", cash)


def _corp_ownership() -> list[CanonicalOwnership]:
    """FY2026 pledge spike (2% → 15%) exercises the pledge detector."""
    rows = [
        # period, promoter, pledge, fii, dii, mf, public
        ("FY2022", 52.4, 0.0, 22.1, 14.8, 8.9, 7.3),
        ("FY2023", 52.4, 0.8, 23.6, 15.2, 9.6, 6.4),
        ("FY2024", 51.9, 2.1, 24.8, 15.9, 10.2, 5.6),
        ("FY2025", 51.9, 2.0, 25.1, 16.4, 10.8, 4.9),
        ("FY2026", 50.1, 15.2, 25.9, 16.8, 11.4, 4.2),
    ]
    out = []
    for period, prom, pled, fii, dii, mf, pub in rows:
        out.append(CanonicalOwnership(
            period=period, promoter_pct=prom, promoter_pledge_pct=pled,
            fii_pct=fii, dii_pct=dii, mutual_fund_pct=mf, public_pct=pub,
            institutional_pct=round(fii + dii, 1),
            source_ids=["src_fixture_ownership"],
        ))
    return out


def build_corporate_fixture() -> CanonicalCompanyData:
    data = CanonicalCompanyData(
        identity=_identity(
            "Finora Industries Ltd", EntityType.CORPORATE, "FININD",
            "Manufacturing", "Diversified Industrials",
            "Development fixture entity representing a diversified Indian "
            "manufacturing corporate. All data is fictional."),
        periods=_periods(),
        market_data=_market(1_412.50, -1.2, 1_877_700_000_000),
        ownership=_corp_ownership(),
    )
    _corp_income(data)
    _corp_balance(data)
    _corp_cashflow(data)
    _corp_standalone(data)

    data.add_source(_src("src_fixture_ar", "Finora Dev Fixture Annual Report",
                         "Annual Report FY2022–FY2026",
                         "All financial statements and reported metrics"))
    data.add_source(_src("src_fixture_ownership", "Finora Dev Fixture Shareholding Data",
                         "Shareholding Pattern Filings",
                         "Promoter, FII/DII, MF and public holdings"))
    data.add_source(_src("src_fixture_market", "Finora Dev Fixture Market Data",
                         "Market Snapshot",
                         "Share price, market cap and valuation"))
    return data


# ══════════════════════════════════════════════════════════════════════════
# BANK FIXTURE — Finora Bank Ltd
# Scenario: clean-ish bank with mild asset-quality deterioration so bank
# detectors can fire without overwhelming the dashboard.
# ══════════════════════════════════════════════════════════════════════════

def _bank_income(data: CanonicalCompanyData) -> None:
    stmt = CanonicalStatement(statement_type="income_statement")
    series = {
        "interest_earned": [182_400_000_000, 205_800_000_000, 231_600_000_000,
                             259_900_000_000, 291_400_000_000],
        "interest_expended": [108_900_000_000, 124_600_000_000, 142_800_000_000,
                               162_400_000_000, 185_100_000_000],
        "bank_other_income": [28_400_000_000, 32_600_000_000, 36_800_000_000,
                               41_200_000_000, 46_900_000_000],
        "operating_expenses": [44_800_000_000, 49_900_000_000, 55_600_000_000,
                                61_400_000_000, 67_900_000_000],
        "provisions": [9_800_000_000, 10_900_000_000, 11_800_000_000,
                        13_900_000_000, 16_400_000_000],
        "bank_tax": [10_900_000_000, 12_400_000_000, 13_700_000_000,
                      14_200_000_000, 15_400_000_000],
        "eps_basic": [42.6, 48.9, 55.8, 60.2, 65.4],
        "eps_diluted": [42.1, 48.3, 55.1, 59.5, 64.6],
    }
    for mid, values in series.items():
        for y, v in zip(_YEARS, values):
            unit = "PER_SHARE" if mid.startswith("eps_") else "MONEY"
            stmt.add(_m(mid, y, v, unit=unit))
    data.statements["income_statement"] = stmt


def _bank_balance(data: CanonicalCompanyData) -> None:
    stmt = CanonicalStatement(statement_type="balance_sheet")
    series = {
        "bank_cash": [18_400_000_000, 20_100_000_000, 22_600_000_000,
                       24_900_000_000, 27_800_000_000],
        "balances_with_rbi": [64_800_000_000, 71_200_000_000, 78_400_000_000,
                               86_900_000_000, 94_100_000_000],
        "balances_with_banks": [21_600_000_000, 23_800_000_000, 25_400_000_000,
                                 27_800_000_000, 29_600_000_000],
        "bank_investments": [198_400_000_000, 218_900_000_000, 241_600_000_000,
                              268_400_000_000, 296_800_000_000],
        "advances": [412_800_000_000, 459_600_000_000, 514_800_000_000,
                      571_200_000_000, 638_400_000_000],
        "total_assets": [742_600_000_000, 824_900_000_000, 918_400_000_000,
                          1_018_600_000_000, 1_132_400_000_000],
        "deposits": [589_400_000_000, 648_900_000_000, 721_600_000_000,
                      798_400_000_000, 881_900_000_000],
        "casa_deposits": [218_100_000_000, 243_600_000_000, 274_200_000_000,
                           305_400_000_000, 338_900_000_000],
        "bank_borrowings": [48_900_000_000, 54_600_000_000, 59_800_000_000,
                             64_100_000_000, 70_400_000_000],
        "other_liabilities_bank": [38_400_000_000, 42_800_000_000, 47_600_000_000,
                                    52_900_000_000, 58_600_000_000],
        "share_capital": [10_200_000_000, 10_200_000_000, 10_200_000_000,
                           10_200_000_000, 10_200_000_000],
        "bank_reserves": [55_900_000_000, 68_400_000_000, 79_200_000_000,
                           92_800_000_000, 111_300_000_000],
        "shares_outstanding": [1_020_000_000, 1_020_000_000, 1_020_000_000,
                                1_020_000_000, 1_020_000_000],
        # asset quality (bank disclosures)
        "gnpa": [21_800_000_000, 20_100_000_000, 18_400_000_000,
                  19_900_000_000, 24_600_000_000],
        "nnpa": [6_400_000_000, 5_800_000_000, 5_100_000_000,
                  5_900_000_000, 7_800_000_000],
        "capital_adequacy_ratio": [15.8, 16.2, 16.4, 15.9, 15.1],
        "cet1_ratio": [11.2, 11.6, 11.9, 11.4, 10.8],
        "tier1_ratio": [13.1, 13.5, 13.8, 13.2, 12.5],
    }
    for mid, values in series.items():
        for y, v in zip(_YEARS, values):
            unit = "PERCENT" if mid in ("capital_adequacy_ratio", "cet1_ratio",
                                         "tier1_ratio") else "MONEY"
            stmt.add(_m(mid, y, v, unit=unit))
    data.statements["balance_sheet"] = stmt


def build_bank_fixture() -> CanonicalCompanyData:
    data = CanonicalCompanyData(
        identity=_identity(
            "Finora Bank Ltd", EntityType.BANK, "FINBANK",
            "Financial Services", "Private Sector Bank",
            "Development fixture entity representing a private-sector Indian "
            "bank. All data is fictional."),
        periods=_periods(),
        market_data=_market(318.40, 0.8, 648_700_000_000),
        ownership=[
            CanonicalOwnership(period=y, promoter_pct=26.4 if y < "FY2025" else 26.4,
                               promoter_pledge_pct=0.0,
                               fii_pct=34.2, dii_pct=22.8, mutual_fund_pct=12.6,
                               public_pct=9.4, institutional_pct=57.0,
                               source_ids=["src_fixture_ownership"])
            for y in _YEARS
        ],
    )
    _bank_income(data)
    _bank_balance(data)

    data.add_source(_src("src_fixture_ar", "Finora Dev Fixture Annual Report",
                         "Annual Report FY2022–FY2026",
                         "Bank financial statements and reported metrics"))
    data.add_source(_src("src_fixture_ownership", "Finora Dev Fixture Shareholding Data",
                         "Shareholding Pattern Filings",
                         "Ownership structure"))
    data.add_source(_src("src_fixture_market", "Finora Dev Fixture Market Data",
                         "Market Snapshot",
                         "Share price, market cap and valuation"))
    return data


# ══════════════════════════════════════════════════════════════════════════
# NBFC FIXTURE — Finora Finance Ltd
# Scenario: fast-growing NBFC with mild asset-quality pressure — exercises
# AUM, stage-3, leverage and funding metrics.
# ══════════════════════════════════════════════════════════════════════════

def _nbfc_income(data: CanonicalCompanyData) -> None:
    stmt = CanonicalStatement(statement_type="income_statement")
    series = {
        "total_income_nbfc": [84_600_000_000, 101_200_000_000, 121_800_000_000,
                               146_400_000_000, 176_900_000_000],
        "nbfc_interest_income": [71_800_000_000, 86_400_000_000, 104_600_000_000,
                                  126_800_000_000, 153_400_000_000],
        "nbfc_interest_expense": [32_400_000_000, 40_100_000_000, 49_600_000_000,
                                   61_200_000_000, 75_800_000_000],
        "fee_income": [8_900_000_000, 10_800_000_000, 12_400_000_000,
                        14_100_000_000, 16_800_000_000],
        "nbfc_operating_expenses": [18_400_000_000, 22_100_000_000, 26_800_000_000,
                                     32_400_000_000, 39_600_000_000],
        "nbfc_provisions": [4_800_000_000, 5_600_000_000, 6_400_000_000,
                             8_100_000_000, 10_900_000_000],
        "nbfc_tax": [4_900_000_000, 5_900_000_000, 7_100_000_000,
                      8_600_000_000, 10_400_000_000],
        "eps_basic": [24.8, 29.6, 35.4, 42.1, 49.8],
        "eps_diluted": [24.5, 29.2, 34.9, 41.5, 49.1],
    }
    for mid, values in series.items():
        for y, v in zip(_YEARS, values):
            unit = "PER_SHARE" if mid.startswith("eps_") else "MONEY"
            stmt.add(_m(mid, y, v, unit=unit))
    data.statements["income_statement"] = stmt


def _nbfc_balance(data: CanonicalCompanyData) -> None:
    stmt = CanonicalStatement(statement_type="balance_sheet")
    series = {
        "loan_book": [342_800_000_000, 421_600_000_000, 514_900_000_000,
                       628_400_000_000, 761_800_000_000],
        "nbfc_investments": [28_400_000_000, 31_200_000_000, 34_800_000_000,
                              38_900_000_000, 42_600_000_000],
        "nbfc_cash": [12_600_000_000, 14_100_000_000, 15_800_000_000,
                       17_200_000_000, 19_400_000_000],
        "aum": [358_400_000_000, 441_800_000_000, 539_600_000_000,
                 658_900_000_000, 798_400_000_000],
        "nbfc_total_assets": [398_600_000_000, 484_900_000_000, 586_400_000_000,
                               712_800_000_000, 861_200_000_000],
        "bank_borrowings_nbfc": [118_400_000_000, 141_600_000_000, 168_900_000_000,
                                  198_400_000_000, 231_600_000_000],
        "debt_securities": [96_800_000_000, 121_400_000_000, 148_600_000_000,
                             178_900_000_000, 214_800_000_000],
        "commercial_paper": [18_400_000_000, 21_600_000_000, 24_800_000_000,
                              28_900_000_000, 31_400_000_000],
        "subordinated_debt": [12_600_000_000, 12_900_000_000, 13_400_000_000,
                               13_800_000_000, 14_200_000_000],
        "other_liabilities_nbfc": [28_900_000_000, 33_400_000_000, 38_600_000_000,
                                    44_800_000_000, 52_100_000_000],
        "share_capital": [9_600_000_000, 9_600_000_000, 9_600_000_000,
                           9_600_000_000, 9_600_000_000],
        "bank_reserves": [94_300_000_000, 113_900_000_000, 137_700_000_000,
                           168_000_000_000, 205_700_000_000],
        "shares_outstanding": [960_000_000, 960_000_000, 960_000_000,
                                960_000_000, 960_000_000],
        # asset quality (stage 3)
        "stage3_gross": [9_800_000_000, 11_400_000_000, 13_100_000_000,
                          15_900_000_000, 21_400_000_000],
        "stage3_net": [2_900_000_000, 3_400_000_000, 3_900_000_000,
                        4_900_000_000, 7_100_000_000],
        "nbfc_capital_adequacy": [21.4, 20.8, 20.1, 19.2, 18.1],
    }
    for mid, values in series.items():
        for y, v in zip(_YEARS, values):
            unit = "PERCENT" if mid == "nbfc_capital_adequacy" else "MONEY"
            stmt.add(_m(mid, y, v, unit=unit))
    data.statements["balance_sheet"] = stmt


def build_nbfc_fixture() -> CanonicalCompanyData:
    data = CanonicalCompanyData(
        identity=_identity(
            "Finora Finance Ltd", EntityType.NBFC, "FINFIN",
            "Financial Services", "NBFC — Retail Lending",
            "Development fixture entity representing a retail-lending Indian "
            "NBFC. All data is fictional."),
        periods=_periods(),
        market_data=_market(842.10, 1.6, 495_200_000_000),
        ownership=[
            CanonicalOwnership(period=y, promoter_pct=48.9, promoter_pledge_pct=1.2,
                               fii_pct=28.4, dii_pct=12.6, mutual_fund_pct=8.9,
                               public_pct=7.4, institutional_pct=41.0,
                               source_ids=["src_fixture_ownership"])
            for y in _YEARS
        ],
    )
    _nbfc_income(data)
    _nbfc_balance(data)

    data.add_source(_src("src_fixture_ar", "Finora Dev Fixture Annual Report",
                         "Annual Report FY2022–FY2026",
                         "NBFC financial statements and reported metrics"))
    data.add_source(_src("src_fixture_ownership", "Finora Dev Fixture Shareholding Data",
                         "Shareholding Pattern Filings",
                         "Ownership structure"))
    data.add_source(_src("src_fixture_market", "Finora Dev Fixture Market Data",
                         "Market Snapshot",
                         "Share price, market cap and valuation"))
    return data


# ══════════════════════════════════════════════════════════════════════════
# FIXTURE REGISTRY
# ══════════════════════════════════════════════════════════════════════════

FIXTURE_COMPANIES: dict[str, dict[str, object]] = {
    "corporate": {
        "slug": "corporate",
        "ticker": "FININD",
        "name": "Finora Industries Ltd",
        "entity_type": EntityType.CORPORATE.value,
        "builder": build_corporate_fixture,
    },
    "bank": {
        "slug": "bank",
        "ticker": "FINBANK",
        "name": "Finora Bank Ltd",
        "entity_type": EntityType.BANK.value,
        "builder": build_bank_fixture,
    },
    "nbfc": {
        "slug": "nbfc",
        "ticker": "FINFIN",
        "name": "Finora Finance Ltd",
        "entity_type": EntityType.NBFC.value,
        "builder": build_nbfc_fixture,
    },
}


def get_fixture(slug: str) -> CanonicalCompanyData:
    """Build a fixture dataset by slug (corporate | bank | nbfc)."""
    entry = FIXTURE_COMPANIES.get(slug)
    if entry is None:
        raise ValueError(f"Unknown India fixture: {slug}")
    return entry["builder"]()  # type: ignore[operator]
