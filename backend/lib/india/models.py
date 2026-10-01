"""India-specific product models: macro strip and dashboard schemas.

These are contracts only — no live scraping. The macro strip carries fixture
data in this phase, clearly labeled; the India Adapter phase will populate it
from RBI / official macro sources.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from lib.core.entity_types import EntityType


# ── India macro strip ─────────────────────────────────────────────────────

@dataclass
class IndiaMacroStrip:
    """India macro context for dashboards.

    A live strip is built from official sources and carries ``is_fixture``
    false. When no source could be verified the strip is *unavailable* — an
    empty item list with a reason — never a placeholder number, because a
    plausible-looking yield that is not RBI's would be read as fact.
    """

    items: list[dict[str, Any]] = field(default_factory=list)
    attribution: str = ""
    is_fixture: bool = False
    unavailable_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "available": bool(self.items),
            "is_fixture": self.is_fixture,
            "strip": list(self.items),
            "attribution": self.attribution,
        }
        if not self.items:
            payload["reason"] = self.unavailable_reason or (
                "No official macro source available at the time of this run"
            )
        return payload


def unavailable_macro_strip(reason: str) -> IndiaMacroStrip:
    """A macro strip that states plainly that nothing was verified.

    Macro must never block company research, so an absent source degrades to
    this rather than raising or, worse, substituting an invented value.
    """
    return IndiaMacroStrip(
        items=[],
        attribution="",
        is_fixture=False,
        unavailable_reason=reason,
    )


def fixture_macro_strip() -> IndiaMacroStrip:
    """Development fixture macro values — explicitly labeled fixture."""
    return IndiaMacroStrip(
        is_fixture=True,
        attribution="Fixture data — not live RBI or exchange data",
        items=[
            {"label": "RBI Policy Repo Rate", "value": "6.50%",
             "series_id": "FIXTURE_RBI_REPO", "date": "2026-09-01", "status": "FIXTURE"},
            {"label": "India 10Y G-Sec Yield", "value": "6.92%",
             "series_id": "FIXTURE_IN10Y", "date": "2026-09-01", "status": "FIXTURE"},
            {"label": "India CPI Inflation", "value": "4.1%",
             "series_id": "FIXTURE_INCPI", "date": "2026-08-01", "status": "FIXTURE"},
            {"label": "USD/INR", "value": "₹83.9",
             "series_id": "FIXTURE_USDINR", "date": "2026-09-01", "status": "FIXTURE"},
        ],
    )


# Dashboard tabs per entity type (spec §39)
INDIA_DASHBOARD_TABS: dict[str, list[str]] = {
    EntityType.CORPORATE.value: [
        "OVERVIEW", "FINANCIALS", "GROWTH", "PROFITABILITY", "LIQUIDITY",
        "LEVERAGE", "EFFICIENCY", "CAPITAL ALLOCATION", "OWNERSHIP",
        "FORENSICS", "VALUATION", "SOURCES",
    ],
    EntityType.BANK.value: [
        "OVERVIEW", "FINANCIALS", "GROWTH", "PROFITABILITY", "ASSET QUALITY",
        "FUNDING", "CAPITAL", "OWNERSHIP", "FORENSICS", "VALUATION", "SOURCES",
    ],
    EntityType.NBFC.value: [
        "OVERVIEW", "FINANCIALS", "GROWTH", "PROFITABILITY", "ASSET QUALITY",
        "LEVERAGE", "FUNDING", "OWNERSHIP", "FORENSICS", "VALUATION", "SOURCES",
    ],
}


# ── India dashboard schemas ───────────────────────────────────────────────

@dataclass
class IndiaDashboardSchema:
    """Schema describing one India dashboard's structure.

    Drives the dashboard builder, the completeness engine and the frontend
    renderer. Metric ids reference the central registry.
    """

    entity_type: EntityType
    tabs: list[str]
    overview_metrics: list[str]
    # category → ordered metric ids rendered in that tab
    tab_metrics: dict[str, list[str]] = field(default_factory=dict)
    # statement line items (ordered) for the Financials tab
    statements: dict[str, list[str]] = field(default_factory=dict)

    def expected_metric_ids(self) -> list[str]:
        """All metrics expected for completeness (overview + tabs)."""
        seen: dict[str, None] = {}
        for mid in self.overview_metrics + [m for ids in self.tab_metrics.values() for m in ids]:
            seen[mid] = None
        return list(seen)


def _schema(entity: EntityType, tabs: list[str], overview: list[str],
            tab_metrics: dict[str, list[str]],
            statements: dict[str, list[str]]) -> IndiaDashboardSchema:
    return IndiaDashboardSchema(
        entity_type=entity, tabs=tabs, overview_metrics=overview,
        tab_metrics=tab_metrics, statements=statements,
    )


INDIA_CORPORATE_SCHEMA: IndiaDashboardSchema = _schema(
    EntityType.CORPORATE,
    INDIA_DASHBOARD_TABS[EntityType.CORPORATE.value],
    overview=[
        "revenue", "ebitda", "ebit", "net_profit", "eps_diluted", "free_cash_flow",
    ],
    tab_metrics={
        "GROWTH": [
            "revenue_growth", "ebitda_growth", "ebit_growth", "pat_growth",
            "eps_growth", "ocf_growth", "fcf_growth",
            "revenue_cagr_3y", "revenue_cagr_5y", "pat_cagr_3y", "pat_cagr_5y",
            "eps_cagr_3y", "eps_cagr_5y", "ebitda_cagr_3y",
        ],
        "PROFITABILITY": [
            "gross_margin", "ebitda_margin", "operating_margin", "pbt_margin",
            "pat_margin", "ocf_margin", "fcf_margin",
            "roa", "roe", "roce", "roic",
        ],
        "LIQUIDITY": [
            "current_ratio", "quick_ratio", "cash_ratio",
            "net_working_capital", "nwc_to_revenue",
        ],
        "LEVERAGE": [
            "debt_to_equity", "debt_to_assets", "debt_to_capital", "net_debt",
            "debt_to_ebitda", "net_debt_to_ebitda", "cash_flow_to_debt",
            "interest_coverage",
        ],
        "EFFICIENCY": [
            "asset_turnover", "receivables_turnover", "inventory_turnover",
            "payables_turnover", "dso", "dio", "dpo", "cash_conversion_cycle",
        ],
        "CAPITAL ALLOCATION": [
            "capex", "capex_to_revenue", "ocf_to_pat", "fcf_to_pat",
            "dividend_payout", "dividend_yield", "share_buybacks",
            "debt_raised", "debt_repaid", "net_debt_change",
        ],
        "OWNERSHIP": [
            "promoter_holding", "promoter_pledge", "fii_holding", "dii_holding",
            "mutual_fund_holding", "public_holding", "institutional_holding",
        ],
        "VALUATION": [
            "share_price", "market_cap", "enterprise_value", "pe_ratio", "ps_ratio",
            "pb_ratio", "earnings_yield", "fcf_yield", "ev_revenue", "ev_ebitda",
            "ev_ebit", "ev_fcf", "net_debt_to_ev", "dividend_yield",
        ],
    },
    statements={
        "income_statement": [
            "revenue", "other_income", "total_income",
            "cost_of_materials", "purchases_stock_in_trade", "changes_in_inventories",
            "employee_benefits", "finance_costs", "depreciation_amortisation",
            "other_expenses", "total_expenses",
            "ebitda", "ebit",
            "pbt", "exceptional_items", "current_tax", "deferred_tax", "total_tax",
            "net_profit", "oci", "comprehensive_income",
            "eps_basic", "eps_diluted",
        ],
        "balance_sheet": [
            "cash", "bank_balances", "current_investments", "non_current_investments",
            "trade_receivables", "inventory", "other_current_assets",
            "total_current_assets",
            "ppe", "cwip", "intangibles", "goodwill", "other_non_current_assets",
            "total_non_current_assets", "total_assets",
            "trade_payables", "short_term_borrowings", "current_debt",
            "other_current_liabilities", "total_current_liabilities",
            "long_term_borrowings", "other_non_current_liabilities",
            "total_non_current_liabilities", "total_debt", "total_liabilities",
            "share_capital", "reserves_surplus", "minority_interest", "total_equity",
        ],
        "cash_flow": [
            "operating_cash_flow", "capex", "free_cash_flow",
            "investing_cash_flow", "financing_cash_flow",
            "dividends_paid", "interest_paid", "debt_raised", "debt_repaid",
            "share_buybacks", "net_change_in_cash",
        ],
    },
)


INDIA_BANK_SCHEMA: IndiaDashboardSchema = _schema(
    EntityType.BANK,
    INDIA_DASHBOARD_TABS[EntityType.BANK.value],
    overview=[
        "nii", "bank_operating_profit", "bank_pat", "eps_diluted",
        "advances", "deposits",
    ],
    tab_metrics={
        "GROWTH": [
            "advances_growth", "deposit_growth", "nii_growth", "pat_growth",
            "eps_growth",
        ],
        "PROFITABILITY": [
            "nim", "cost_to_income", "bank_roa", "bank_roe",
        ],
        "ASSET QUALITY": [
            "gnpa", "gnpa_pct", "nnpa", "nnpa_pct",
            "provision_coverage_ratio", "credit_cost",
        ],
        "FUNDING": [
            "deposits", "casa_deposits", "casa_ratio", "bank_borrowings",
            "credit_to_deposit",
        ],
        "CAPITAL": [
            "capital_adequacy_ratio", "cet1_ratio", "tier1_ratio",
        ],
        "OWNERSHIP": [
            "promoter_holding", "promoter_pledge", "fii_holding", "dii_holding",
            "mutual_fund_holding", "public_holding", "institutional_holding",
        ],
        "VALUATION": [
            "share_price", "market_cap", "pe_ratio", "pb_ratio",
            "book_value_per_share", "dividend_yield",
        ],
    },
    statements={
        "income_statement": [
            "interest_earned", "interest_expended", "nii",
            "bank_other_income", "operating_expenses", "bank_operating_profit",
            "provisions", "bank_pbt", "bank_tax", "bank_pat",
            "eps_basic", "eps_diluted",
        ],
        "balance_sheet": [
            "bank_cash", "balances_with_rbi", "balances_with_banks",
            "bank_investments", "advances", "total_assets",
            "deposits", "bank_borrowings", "other_liabilities_bank",
            "share_capital", "bank_reserves", "bank_total_equity",
        ],
    },
)


INDIA_NBFC_SCHEMA: IndiaDashboardSchema = _schema(
    EntityType.NBFC,
    INDIA_DASHBOARD_TABS[EntityType.NBFC.value],
    overview=[
        "total_income_nbfc", "nbfc_nii", "nbfc_pat", "eps_diluted",
        "aum", "nbfc_net_worth",
    ],
    tab_metrics={
        "GROWTH": [
            "aum_growth", "loan_book_growth", "nbfc_income_growth",
            "nbfc_nii_growth", "nbfc_pat_growth", "nbfc_eps_growth",
        ],
        "PROFITABILITY": [
            "nbfc_nim", "nbfc_roa", "nbfc_roe", "nbfc_cost_to_income",
        ],
        "ASSET QUALITY": [
            "stage3_gross", "stage3_gross_pct", "stage3_net", "stage3_net_pct",
            "nbfc_credit_cost", "nbfc_provision_coverage",
        ],
        "LEVERAGE": [
            "nbfc_debt_to_equity", "nbfc_leverage_ratio", "nbfc_capital_adequacy",
            "nbfc_interest_coverage",
        ],
        "FUNDING": [
            "bank_borrowings_nbfc", "debt_securities", "commercial_paper",
            "securitisation", "nbfc_borrowings",
        ],
        "OWNERSHIP": [
            "promoter_holding", "promoter_pledge", "fii_holding", "dii_holding",
            "mutual_fund_holding", "public_holding", "institutional_holding",
        ],
        "VALUATION": [
            "share_price", "market_cap", "pe_ratio", "pb_ratio",
            "book_value_per_share", "dividend_yield",
        ],
    },
    statements={
        "income_statement": [
            "nbfc_interest_income", "nbfc_interest_expense", "nbfc_nii",
            "fee_income", "nbfc_operating_expenses", "nbfc_ppop",
            "nbfc_provisions", "nbfc_pbt", "nbfc_tax", "nbfc_pat",
            "eps_basic", "eps_diluted",
        ],
        "balance_sheet": [
            "loan_book", "nbfc_investments", "nbfc_cash", "nbfc_total_assets",
            "bank_borrowings_nbfc", "debt_securities", "commercial_paper",
            "subordinated_debt", "nbfc_borrowings", "other_liabilities_nbfc",
            "share_capital", "bank_reserves", "nbfc_net_worth",
        ],
    },
)


def schema_for(entity_type: EntityType) -> IndiaDashboardSchema:
    """Return the dashboard schema for an entity type."""
    schemas = {
        EntityType.CORPORATE: INDIA_CORPORATE_SCHEMA,
        EntityType.BANK: INDIA_BANK_SCHEMA,
        EntityType.NBFC: INDIA_NBFC_SCHEMA,
    }
    schema = schemas.get(entity_type)
    if schema is None:
        raise ValueError(f"No India dashboard schema for {entity_type.value} (future phase)")
    return schema
