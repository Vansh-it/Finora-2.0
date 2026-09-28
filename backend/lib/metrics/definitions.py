"""Metric definitions for all entity types.

One definition per metric. Bank and NBFC metrics use distinct metric_ids from
corporate ids where the underlying economics differ (e.g. bank ROA is computed
from interest-earned statements, corporate ROA from EBIT-style statements).

Definitions carry methodology text surfaced in evidence drawers and the
/methodology page.
"""

from __future__ import annotations

from lib.core.entity_types import EntityType
from lib.metrics.registry import (
    MetricDefinition,
    MetricRegistry,
    Requirement,
    SourceType,
    UnitType,
)

_ALL = frozenset(EntityType)
_CORP = frozenset({EntityType.CORPORATE})
_BANK = frozenset({EntityType.BANK})
_NBFC = frozenset({EntityType.NBFC})
_BANK_NBFC = frozenset({EntityType.BANK, EntityType.NBFC})


# Which source types a metric trusts, most-authoritative first. Derived from the
# metric's category so every registered metric declares an order rather than
# leaving ``source_priority`` empty and unranked.
#
# Rationale: machine-readable XBRL beats a human-filed PDF, a filing beats an
# investor-relations summary, and for anything market-derived the price feed is
# the only authority. FIXTURE ranks last everywhere so development data can
# never outrank a real filing if both are ever present.
_FILING_SOURCES = (
    SourceType.NSE_XBRL.value,
    SourceType.BSE_XBRL.value,
    SourceType.ANNUAL_REPORT.value,
    SourceType.NSE_FILING.value,
    SourceType.BSE_FILING.value,
    SourceType.COMPANY_IR.value,
    SourceType.FIXTURE.value,
)
_MARKET_SOURCES = (
    SourceType.MARKET_DATA.value,
    SourceType.NSE_XBRL.value,
    SourceType.BSE_XBRL.value,
    SourceType.ANNUAL_REPORT.value,
    SourceType.COMPANY_IR.value,
    SourceType.FIXTURE.value,
)
_MACRO_SOURCES = (
    SourceType.MACRO_DATA.value,
    SourceType.NSE_XBRL.value,
    SourceType.ANNUAL_REPORT.value,
    SourceType.FIXTURE.value,
)

_CATEGORY_SOURCES: dict[str, tuple[str, ...]] = {
    "valuation": _MARKET_SOURCES,
    "ownership": _FILING_SOURCES,
}


def _sources_for(category: str) -> tuple[str, ...]:
    return _CATEGORY_SOURCES.get(category, _FILING_SOURCES)


def _d(
    metric_id: str,
    display_name: str,
    category: str,
    entities: frozenset,
    *,
    unit: str = UnitType.MONEY.value,
    requirement: str = Requirement.REQUIRED.value,
    method: str = "REPORTED",
    inputs: tuple[str, ...] = (),
    opt_inputs: tuple[str, ...] = (),
    formula: str = "",
    methodology: str = "",
    higher_is_better: bool | None = None,
    formatting: str = "inr",
    conditional_when: str = "",
    sources: tuple[str, ...] = (),
) -> MetricDefinition:
    return MetricDefinition(
        metric_id=metric_id,
        display_name=display_name,
        category=category,
        entity_types=entities,
        unit_type=unit,
        requirement=requirement,
        calculation_method=method,
        required_inputs=inputs,
        optional_inputs=opt_inputs,
        formula=formula or (f"{display_name} = {' / '.join(inputs)}" if inputs and method == "FORMULA" else ""),
        methodology=methodology
        or (
            f"Computed as {display_name} = {' / '.join(inputs)}."
            if inputs and method == "FORMULA"
            else "Reported directly in company filings."
        ),
        higher_is_better=higher_is_better,
        source_priority=sources or _sources_for(category),
        formatting=formatting,
        conditional_when=conditional_when,
    )


def populate_registry(registry: MetricRegistry) -> None:
    """Register every Finora metric definition."""

    def reg(d: MetricDefinition) -> None:
        registry.register(d)

    # ══════════════════════════════════════════════════════════════════
    # SHARED — money & per-share basics
    # ══════════════════════════════════════════════════════════════════
    reg(_d("revenue", "Revenue from Operations", "income_statement", _ALL,
           methodology="Reported 'Revenue from operations' per Ind AS 115."))
    reg(_d("other_income", "Other Income", "income_statement", _ALL))
    reg(_d("total_income", "Total Income", "income_statement", _ALL,
           method="FORMULA", inputs=("revenue", "other_income"),
           formula="Total Income = Revenue from Operations + Other Income",
           methodology="Sum of operating revenue and other income."))
    reg(_d("net_profit", "Profit After Tax", "income_statement", _ALL,
           methodology="Profit attributable after all expenses and tax."))
    reg(_d("eps_basic", "Basic EPS", "income_statement", _ALL, unit=UnitType.PER_SHARE.value,
           formatting="eps"))
    reg(_d("eps_diluted", "Diluted EPS", "income_statement", _ALL, unit=UnitType.PER_SHARE.value,
           formatting="eps"))
    reg(_d("total_assets", "Total Assets", "balance_sheet", _ALL))
    reg(_d("share_capital", "Share Capital", "balance_sheet", _ALL))
    reg(_d("equity", "Shareholders' Equity", "balance_sheet", _ALL,
           methodology="Share capital plus reserves & surplus and other equity."))
    reg(_d("dividend_per_share", "Dividend per Share", "capital_allocation", _ALL,
           unit=UnitType.PER_SHARE.value, formatting="eps", requirement=Requirement.OPTIONAL.value))

    # ══════════════════════════════════════════════════════════════════
    # CORPORATE — income statement (Ind AS Schedule III line items)
    # ══════════════════════════════════════════════════════════════════
    reg(_d("cost_of_materials", "Cost of Materials Consumed", "income_statement", _CORP,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("purchases_stock_in_trade", "Purchases of Stock-in-Trade", "income_statement", _CORP,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("changes_in_inventories", "Changes in Inventories", "income_statement", _CORP,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("employee_benefits", "Employee Benefits Expense", "income_statement", _CORP,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("finance_costs", "Finance Costs", "income_statement", _CORP,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("depreciation_amortisation", "Depreciation & Amortisation", "income_statement", _CORP,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("other_expenses", "Other Expenses", "income_statement", _CORP,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("total_expenses", "Total Expenses", "income_statement", _CORP,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("ebitda", "EBITDA", "income_statement", _CORP,
           method="FORMULA",
           inputs=("revenue", "employee_benefits", "other_expenses", "cost_of_materials",
                    "purchases_stock_in_trade", "changes_in_inventories"),
           formula="EBITDA = Revenue − Operating Expenses (materials, purchases, inventory change, employees, other) — excludes other income, finance costs and D&A",
           methodology="Operating earnings before interest, tax, depreciation and amortisation. "
                       "Finora computes EBITDA from operating line items only; other income is excluded "
                       "so EBITDA reflects core operations."))
    reg(_d("ebit", "Operating Profit (EBIT)", "income_statement", _CORP,
           method="FORMULA", inputs=("ebitda", "depreciation_amortisation"),
           formula="EBIT = EBITDA − Depreciation & Amortisation"))
    reg(_d("pbt", "Profit Before Tax", "income_statement", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("exceptional_items", "Exceptional Items", "income_statement", _CORP,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("current_tax", "Current Tax", "income_statement", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("deferred_tax", "Deferred Tax", "income_statement", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("total_tax", "Total Tax Expense", "income_statement", _CORP,
           method="FORMULA", inputs=("current_tax", "deferred_tax"),
           formula="Total Tax = Current Tax + Deferred Tax",
           requirement=Requirement.OPTIONAL.value))
    reg(_d("oci", "Other Comprehensive Income", "income_statement", _CORP,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("comprehensive_income", "Total Comprehensive Income", "income_statement", _CORP,
           method="FORMULA", inputs=("net_profit", "oci"),
           formula="Total Comprehensive Income = PAT + Other Comprehensive Income",
           requirement=Requirement.OPTIONAL.value))

    # ══════════════════════════════════════════════════════════════════
    # CORPORATE — balance sheet
    # ══════════════════════════════════════════════════════════════════
    reg(_d("cash", "Cash & Cash Equivalents", "balance_sheet", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("bank_balances", "Bank Balances", "balance_sheet", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("current_investments", "Current Investments", "balance_sheet", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("non_current_investments", "Non-current Investments", "balance_sheet", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("trade_receivables", "Trade Receivables", "balance_sheet", _CORP))
    reg(_d("inventory", "Inventories", "balance_sheet", _CORP))
    reg(_d("other_current_assets", "Other Current Assets", "balance_sheet", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("total_current_assets", "Total Current Assets", "balance_sheet", _CORP,
           method="FORMULA",
           inputs=("cash", "bank_balances", "current_investments", "trade_receivables", "inventory", "other_current_assets"),
           formula="Total Current Assets = Cash + Bank Balances + Current Investments + Trade Receivables + Inventories + Other Current Assets"))
    reg(_d("ppe", "Property, Plant & Equipment", "balance_sheet", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("cwip", "Capital Work in Progress", "balance_sheet", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("intangibles", "Intangible Assets", "balance_sheet", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("goodwill", "Goodwill", "balance_sheet", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("other_non_current_assets", "Other Non-current Assets", "balance_sheet", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("total_non_current_assets", "Total Non-current Assets", "balance_sheet", _CORP,
           method="FORMULA",
           inputs=("ppe", "cwip", "intangibles", "goodwill", "non_current_investments", "other_non_current_assets"),
           formula="Total Non-current Assets = PPE + CWIP + Intangibles + Goodwill + Non-current Investments + Other",
           requirement=Requirement.OPTIONAL.value))
    reg(_d("trade_payables", "Trade Payables", "balance_sheet", _CORP))
    reg(_d("short_term_borrowings", "Short-term Borrowings", "balance_sheet", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("current_debt", "Current Portion of Long-term Debt", "balance_sheet", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("other_current_liabilities", "Other Current Liabilities", "balance_sheet", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("total_current_liabilities", "Total Current Liabilities", "balance_sheet", _CORP,
           method="FORMULA",
           inputs=("trade_payables", "short_term_borrowings", "current_debt", "other_current_liabilities"),
           formula="Total Current Liabilities = Trade Payables + Short-term Borrowings + Current Debt + Other",
           requirement=Requirement.OPTIONAL.value))
    reg(_d("long_term_borrowings", "Long-term Borrowings", "balance_sheet", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("other_non_current_liabilities", "Other Non-current Liabilities", "balance_sheet", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("total_non_current_liabilities", "Total Non-current Liabilities", "balance_sheet", _CORP,
           method="FORMULA",
           inputs=("long_term_borrowings", "other_non_current_liabilities"),
           formula="Total Non-current Liabilities = Long-term Borrowings + Other",
           requirement=Requirement.OPTIONAL.value))
    reg(_d("total_debt", "Total Debt", "balance_sheet", _CORP,
           method="FORMULA", inputs=("short_term_borrowings", "current_debt", "long_term_borrowings"),
           formula="Total Debt = Short-term + Current portion of long-term + Long-term Borrowings",
           methodology="Interest-bearing borrowings only; trade payables and other operating liabilities excluded."))
    reg(_d("total_liabilities", "Total Liabilities", "balance_sheet", _CORP,
           method="FORMULA", inputs=("total_current_liabilities", "total_non_current_liabilities"),
           formula="Total Liabilities = Current + Non-current Liabilities",
           requirement=Requirement.OPTIONAL.value))
    reg(_d("reserves_surplus", "Reserves & Surplus", "balance_sheet", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("minority_interest", "Non-controlling Interests", "balance_sheet", _CORP,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("total_equity", "Total Equity", "balance_sheet", _CORP,
           method="FORMULA", inputs=("share_capital", "reserves_surplus", "minority_interest"),
           formula="Total Equity = Share Capital + Reserves & Surplus + Non-controlling Interests"))

    # ══════════════════════════════════════════════════════════════════
    # CORPORATE — cash flow
    # ══════════════════════════════════════════════════════════════════
    reg(_d("operating_cash_flow", "Cash Flow from Operations", "cash_flow", _CORP))
    reg(_d("capex", "Capital Expenditure", "cash_flow", _CORP,
           methodology="Purchases of PPE and intangibles, expressed positive."))
    reg(_d("free_cash_flow", "Free Cash Flow", "cash_flow", _CORP,
           method="FORMULA", inputs=("operating_cash_flow", "capex"),
           formula="FCF = Operating Cash Flow − CapEx",
           methodology="Finora defines FCF as OCF minus purchases of PPE and intangibles."))
    reg(_d("investing_cash_flow", "Cash Flow from Investing", "cash_flow", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("financing_cash_flow", "Cash Flow from Financing", "cash_flow", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("dividends_paid", "Dividends Paid", "cash_flow", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("interest_paid", "Interest Paid", "cash_flow", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("debt_raised", "Debt Raised", "cash_flow", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("debt_repaid", "Debt Repaid", "cash_flow", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("share_buybacks", "Share Buybacks", "cash_flow", _CORP, requirement=Requirement.OPTIONAL.value))
    reg(_d("net_change_in_cash", "Net Change in Cash", "cash_flow", _CORP, requirement=Requirement.OPTIONAL.value))

    # ══════════════════════════════════════════════════════════════════
    # CORPORATE — growth
    # ══════════════════════════════════════════════════════════════════
    for mid, name, base in (
        ("revenue_growth", "Revenue Growth", "revenue"),
        ("ebitda_growth", "EBITDA Growth", "ebitda"),
        ("ebit_growth", "EBIT Growth", "ebit"),
        ("pat_growth", "PAT Growth", "net_profit"),
        ("eps_growth", "EPS Growth", "eps_diluted"),
        ("ocf_growth", "OCF Growth", "operating_cash_flow"),
        ("fcf_growth", "FCF Growth", "free_cash_flow"),
    ):
        reg(_d(mid, name, "growth", _CORP, unit=UnitType.PERCENT.value, formatting="percent",
               method="DERIVED", inputs=(base,),
               formula=f"{name} = (Current − Previous) / |Previous| × 100",
               higher_is_better=True))
    for mid, name, base, years in (
        ("revenue_cagr_3y", "Revenue CAGR 3Y", "revenue", 3),
        ("revenue_cagr_5y", "Revenue CAGR 5Y", "revenue", 5),
        ("pat_cagr_3y", "PAT CAGR 3Y", "net_profit", 3),
        ("pat_cagr_5y", "PAT CAGR 5Y", "net_profit", 5),
        ("eps_cagr_3y", "EPS CAGR 3Y", "eps_diluted", 3),
        ("eps_cagr_5y", "EPS CAGR 5Y", "eps_diluted", 5),
        ("ebitda_cagr_3y", "EBITDA CAGR 3Y", "ebitda", 3),
    ):
        reg(_d(mid, name, "growth", _CORP, unit=UnitType.PERCENT.value, formatting="percent",
               method="DERIVED", inputs=(base,),
               formula=f"{name} = (End/Start)^(1/{years}) − 1",
               methodology=f"Compound annual growth over {years} fiscal years. Requires positive start and end values; "
                           "computed only when an exact FY span exists.",
               higher_is_better=True, requirement=Requirement.CONDITIONAL.value,
               conditional_when=f"Requires {years} years of history"))

    # ══════════════════════════════════════════════════════════════════
    # CORPORATE — profitability
    # ══════════════════════════════════════════════════════════════════
    reg(_d("gross_profit", "Gross Profit", "profitability", _CORP,
           method="FORMULA", inputs=("revenue", "cost_of_materials"),
           formula="Gross Profit = Revenue − Cost of Materials Consumed − Changes in Inventories − Purchases of Stock-in-Trade",
           requirement=Requirement.CONDITIONAL.value,
           conditional_when="Only when cost-of-sales inputs exist and gross profit is economically meaningful"))
    reg(_d("gross_margin", "Gross Margin", "profitability", _CORP,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("gross_profit", "revenue"),
           formula="Gross Margin = Gross Profit / Revenue × 100",
           requirement=Requirement.CONDITIONAL.value,
           conditional_when="Only when gross profit is computable from disclosed cost lines",
           higher_is_better=True))
    reg(_d("ebitda_margin", "EBITDA Margin", "profitability", _CORP,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("ebitda", "revenue"), formula="EBITDA Margin = EBITDA / Revenue × 100",
           higher_is_better=True))
    reg(_d("operating_margin", "Operating Margin", "profitability", _CORP,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("ebit", "revenue"), formula="Operating Margin = EBIT / Revenue × 100",
           higher_is_better=True))
    reg(_d("pbt_margin", "PBT Margin", "profitability", _CORP,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("pbt", "revenue"), formula="PBT Margin = PBT / Revenue × 100",
           requirement=Requirement.OPTIONAL.value, higher_is_better=True))
    reg(_d("pat_margin", "PAT Margin", "profitability", _CORP,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("net_profit", "revenue"), formula="PAT Margin = PAT / Revenue × 100",
           higher_is_better=True))
    reg(_d("ocf_margin", "OCF Margin", "profitability", _CORP,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("operating_cash_flow", "revenue"), formula="OCF Margin = OCF / Revenue × 100",
           higher_is_better=True))
    reg(_d("fcf_margin", "FCF Margin", "profitability", _CORP,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("free_cash_flow", "revenue"), formula="FCF Margin = FCF / Revenue × 100",
           higher_is_better=True))
    reg(_d("roa", "Return on Assets", "profitability", _CORP,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("ebit", "total_assets"),
           formula="ROA = EBIT / Total Assets × 100",
           methodology="Finora computes corporate ROA from EBIT (pre-interest operating earnings) over average total assets where history exists, else closing assets.",
           higher_is_better=True))
    reg(_d("roe", "Return on Equity", "profitability", _CORP,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("net_profit", "total_equity"),
           formula="ROE = PAT / Total Equity × 100",
           higher_is_better=True))
    reg(_d("roce", "Return on Capital Employed", "profitability", _CORP,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("ebit", "total_equity", "total_debt"),
           formula="ROCE = EBIT / (Equity + Debt) × 100",
           methodology="Capital Employed is defined by Finora as Total Equity plus Total Debt "
                       "(interest-bearing), measured at period end when history is unavailable.",
           higher_is_better=True))
    reg(_d("roic", "Return on Invested Capital", "profitability", _CORP,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("ebit", "total_equity", "total_debt", "cash", "current_investments", "bank_balances"),
           formula="ROIC = EBIT × (1 − Tax Rate) / (Debt + Equity − Cash & Investments)",
           methodology="Invested capital = debt + equity − non-operating liquid assets (cash, bank balances, current investments). "
                       "Tax rate = total tax / PBT when both are disclosed.",
           higher_is_better=True))

    # ══════════════════════════════════════════════════════════════════
    # CORPORATE — liquidity
    # ══════════════════════════════════════════════════════════════════
    reg(_d("current_ratio", "Current Ratio", "liquidity", _CORP,
           unit=UnitType.RATIO.value, formatting="ratio", method="FORMULA",
           inputs=("total_current_assets", "total_current_liabilities"),
           formula="Current Ratio = Current Assets / Current Liabilities", higher_is_better=True))
    reg(_d("quick_ratio", "Quick Ratio", "liquidity", _CORP,
           unit=UnitType.RATIO.value, formatting="ratio", method="FORMULA",
           inputs=("total_current_assets", "inventory", "total_current_liabilities"),
           formula="Quick Ratio = (Current Assets − Inventories) / Current Liabilities",
           higher_is_better=True))
    reg(_d("cash_ratio", "Cash Ratio", "liquidity", _CORP,
           unit=UnitType.RATIO.value, formatting="ratio", method="FORMULA",
           inputs=("cash", "total_current_liabilities"),
           formula="Cash Ratio = Cash & Equivalents / Current Liabilities",
           requirement=Requirement.OPTIONAL.value, higher_is_better=True))
    reg(_d("net_working_capital", "Net Working Capital", "liquidity", _CORP,
           method="FORMULA", inputs=("total_current_assets", "total_current_liabilities"),
           formula="NWC = Current Assets − Current Liabilities", requirement=Requirement.OPTIONAL.value))
    reg(_d("nwc_to_revenue", "NWC / Revenue", "liquidity", _CORP,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("net_working_capital", "revenue"),
           formula="NWC / Revenue = Net Working Capital / Revenue × 100",
           requirement=Requirement.OPTIONAL.value))

    # ══════════════════════════════════════════════════════════════════
    # CORPORATE — leverage
    # ══════════════════════════════════════════════════════════════════
    reg(_d("debt_to_equity", "Debt / Equity", "leverage", _CORP,
           unit=UnitType.RATIO.value, formatting="ratio", method="FORMULA",
           inputs=("total_debt", "total_equity"),
           formula="Debt / Equity = Total Debt / Total Equity",
           higher_is_better=False))
    reg(_d("debt_to_assets", "Debt / Assets", "leverage", _CORP,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("total_debt", "total_assets"),
           formula="Debt / Assets = Total Debt / Total Assets × 100", higher_is_better=False))
    reg(_d("debt_to_capital", "Debt / Capital", "leverage", _CORP,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("total_debt", "total_equity"),
           formula="Debt / Capital = Debt / (Debt + Equity) × 100", higher_is_better=False))
    reg(_d("net_debt", "Net Debt", "leverage", _CORP,
           method="FORMULA", inputs=("total_debt", "cash", "current_investments"),
           formula="Net Debt = Total Debt − Cash − Current Investments",
           methodology="Cash and current investments are subtracted as liquid resources; bank balances included when disclosed.",
           requirement=Requirement.OPTIONAL.value))
    reg(_d("debt_to_ebitda", "Debt / EBITDA", "leverage", _CORP,
           unit=UnitType.TIMES.value, formatting="ratio", method="FORMULA",
           inputs=("total_debt", "ebitda"),
           formula="Debt / EBITDA = Total Debt / EBITDA", higher_is_better=False))
    reg(_d("net_debt_to_ebitda", "Net Debt / EBITDA", "leverage", _CORP,
           unit=UnitType.TIMES.value, formatting="ratio", method="FORMULA",
           inputs=("net_debt", "ebitda"),
           formula="Net Debt / EBITDA = Net Debt / EBITDA", higher_is_better=False))
    reg(_d("cash_flow_to_debt", "Cash Flow / Debt", "leverage", _CORP,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("operating_cash_flow", "total_debt"),
           formula="Cash Flow / Debt = OCF / Total Debt × 100", higher_is_better=True))
    reg(_d("interest_coverage", "Interest Coverage", "leverage", _CORP,
           unit=UnitType.TIMES.value, formatting="ratio", method="FORMULA",
           inputs=("ebit", "finance_costs"),
           formula="Interest Coverage = EBIT / Finance Costs", higher_is_better=True))

    # ══════════════════════════════════════════════════════════════════
    # CORPORATE — efficiency (never applicable to BANK/NBFC)
    # ═════════════════════════════════════════════════════════core
    # ══════════════════════════════════════════════════════════════════
    reg(_d("asset_turnover", "Asset Turnover", "efficiency", _CORP,
           unit=UnitType.TIMES.value, formatting="ratio", method="FORMULA",
           inputs=("revenue", "total_assets"),
           formula="Asset Turnover = Revenue / Total Assets", higher_is_better=True))
    reg(_d("receivables_turnover", "Receivables Turnover", "efficiency", _CORP,
           unit=UnitType.TIMES.value, formatting="ratio", method="FORMULA",
           inputs=("revenue", "trade_receivables"),
           formula="Receivables Turnover = Revenue / Trade Receivables", higher_is_better=True))
    reg(_d("inventory_turnover", "Inventory Turnover", "efficiency", _CORP,
           unit=UnitType.TIMES.value, formatting="ratio", method="FORMULA",
           inputs=("cost_of_materials", "inventory"),
           formula="Inventory Turnover = Cost of Materials / Inventories", higher_is_better=True))
    reg(_d("payables_turnover", "Payables Turnover", "efficiency", _CORP,
           unit=UnitType.TIMES.value, formatting="ratio", method="FORMULA",
           inputs=("cost_of_materials", "trade_payables"),
           formula="Payables Turnover = Cost of Materials / Trade Payables", higher_is_better=True))
    reg(_d("dso", "Days Sales Outstanding", "efficiency", _CORP,
           unit=UnitType.DAYS.value, formatting="days", method="FORMULA",
           inputs=("trade_receivables", "revenue"),
           formula="DSO = Trade Receivables / Revenue × 365", higher_is_better=False))
    reg(_d("dio", "Days Inventory Outstanding", "efficiency", _CORP,
           unit=UnitType.DAYS.value, formatting="days", method="FORMULA",
           inputs=("inventory", "cost_of_materials"),
           formula="DIO = Inventories / Cost of Materials × 365", higher_is_better=False))
    reg(_d("dpo", "Days Payables Outstanding", "efficiency", _CORP,
           unit=UnitType.DAYS.value, formatting="days", method="FORMULA",
           inputs=("trade_payables", "cost_of_materials"),
           formula="DPO = Trade Payables / Cost of Materials × 365", higher_is_better=True))
    reg(_d("cash_conversion_cycle", "Cash Conversion Cycle", "efficiency", _CORP,
           unit=UnitType.DAYS.value, formatting="days", method="FORMULA",
           inputs=("dso", "dio", "dpo"),
           formula="CCC = DSO + DIO − DPO", higher_is_better=False))

    # ══════════════════════════════════════════════════════════════════
    # CORPORATE — capital allocation
    # ══════════════════════════════════════════════════════════════════
    reg(_d("capex_to_revenue", "CapEx / Revenue", "capital_allocation", _CORP,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("capex", "revenue"), formula="CapEx / Revenue = CapEx / Revenue × 100"))
    reg(_d("ocf_to_pat", "OCF / PAT", "capital_allocation", _CORP,
           unit=UnitType.TIMES.value, formatting="ratio", method="FORMULA",
           inputs=("operating_cash_flow", "net_profit"),
           formula="OCF / PAT = Operating Cash Flow / Profit After Tax",
           methodology="Earnings-to-cash conversion. Sustained ratios below 1.0x signal accrual-heavy earnings.",
           higher_is_better=True))
    reg(_d("fcf_to_pat", "FCF / PAT", "capital_allocation", _CORP,
           unit=UnitType.TIMES.value, formatting="ratio", method="FORMULA",
           inputs=("free_cash_flow", "net_profit"),
           formula="FCF / PAT = Free Cash Flow / Profit After Tax", higher_is_better=True))
    reg(_d("dividend_payout", "Dividend Payout", "capital_allocation", _CORP,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("dividends_paid", "net_profit"),
           formula="Dividend Payout = Dividends Paid / PAT × 100",
           requirement=Requirement.CONDITIONAL.value,
           conditional_when="Requires disclosed dividends and positive PAT"))
    reg(_d("dividend_yield", "Dividend Yield", "valuation", _ALL,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("dividend_per_share", "share_price"),
           formula="Dividend Yield = DPS / Share Price × 100",
           requirement=Requirement.CONDITIONAL.value,
           conditional_when="Requires market data"))
    reg(_d("net_debt_change", "Net Debt Change", "capital_allocation", _CORP,
           method="DERIVED", inputs=("net_debt",),
           formula="Net Debt Change = Net Debt (current) − Net Debt (previous)",
           requirement=Requirement.OPTIONAL.value))

    # ══════════════════════════════════════════════════════════════════
    # CORPORATE — ownership (India-specific, listed corporates)
    # ══════════════════════════════════════════════════════════════════
    for mid, name in (
        ("promoter_holding", "Promoter Holding %"),
        ("promoter_pledge", "Promoter Pledge %"),
        ("fii_holding", "FII/FPI Holding %"),
        ("dii_holding", "DII Holding %"),
        ("mutual_fund_holding", "Mutual Fund Holding %"),
        ("public_holding", "Public Holding %"),
        ("institutional_holding", "Institutional Holding %"),
    ):
        is_conditional = mid in ("promoter_holding", "promoter_pledge")
        reg(_d(mid, name, "ownership", _ALL,
               unit=UnitType.PERCENT.value, formatting="percent",
               requirement=Requirement.CONDITIONAL.value if is_conditional else Requirement.OPTIONAL.value,
               method="REPORTED" if mid not in ("institutional_holding",) else "DERIVED",
               inputs=("fii_holding", "dii_holding") if mid == "institutional_holding" else (),
               formula="Institutional Holding = FII/FPI + DII" if mid == "institutional_holding" else "",
               conditional_when="Requires listed-entity shareholding disclosures"
               if is_conditional else ""))

    # ══════════════════════════════════════════════════════════════════
    # CORPORATE — valuation
    # ══════════════════════════════════════════════════════════════════
    reg(_d("share_price", "Share Price", "valuation", _ALL,
           unit=UnitType.PER_SHARE.value, formatting="inr"))
    reg(_d("market_cap", "Market Cap", "valuation", _ALL,
           method="DERIVED", inputs=("share_price", "shares_outstanding"),
           formula="Market Cap = Share Price × Shares Outstanding"))
    reg(_d("shares_outstanding", "Shares Outstanding", "balance_sheet", _ALL, unit=UnitType.COUNT.value,
           formatting="count"))
    reg(_d("enterprise_value", "Enterprise Value", "valuation", _CORP,
           method="DERIVED", inputs=("market_cap", "net_debt"),
           formula="EV = Market Cap + Net Debt",
           methodology="Finora defines EV as market cap plus net debt (debt minus cash & current investments)."))
    reg(_d("pe_ratio", "P/E", "valuation", _ALL,
           unit=UnitType.TIMES.value, formatting="ratio", method="DERIVED",
           inputs=("market_cap", "net_profit"),
           formula="P/E = Market Cap / Profit After Tax", higher_is_better=None))
    reg(_d("ps_ratio", "P/S", "valuation", _ALL,
           unit=UnitType.TIMES.value, formatting="ratio", method="DERIVED",
           inputs=("market_cap", "revenue"), formula="P/S = Market Cap / Revenue"))
    reg(_d("pb_ratio", "P/B", "valuation", _ALL,
           unit=UnitType.TIMES.value, formatting="ratio", method="DERIVED",
           inputs=("market_cap", "total_equity"),
           formula="P/B = Market Cap / Book Value (Total Equity)"))
    reg(_d("earnings_yield", "Earnings Yield", "valuation", _ALL,
           unit=UnitType.PERCENT.value, formatting="percent", method="DERIVED",
           inputs=("net_profit", "market_cap"),
           formula="Earnings Yield = PAT / Market Cap × 100", higher_is_better=True))
    reg(_d("fcf_yield", "FCF Yield", "valuation", _CORP,
           unit=UnitType.PERCENT.value, formatting="percent", method="DERIVED",
           inputs=("free_cash_flow", "market_cap"),
           formula="FCF Yield = FCF / Market Cap × 100",
           requirement=Requirement.CONDITIONAL.value, conditional_when="Requires FCF (corporate) and market data",
           higher_is_better=True))
    reg(_d("ev_revenue", "EV / Revenue", "valuation", _CORP,
           unit=UnitType.TIMES.value, formatting="ratio", method="DERIVED",
           inputs=("enterprise_value", "revenue"), formula="EV / Revenue"))
    reg(_d("ev_ebitda", "EV / EBITDA", "valuation", _CORP,
           unit=UnitType.TIMES.value, formatting="ratio", method="DERIVED",
           inputs=("enterprise_value", "ebitda"), formula="EV / EBITDA"))
    reg(_d("ev_ebit", "EV / EBIT", "valuation", _CORP,
           unit=UnitType.TIMES.value, formatting="ratio", method="DERIVED",
           inputs=("enterprise_value", "ebit"), formula="EV / EBIT"))
    reg(_d("ev_fcf", "EV / FCF", "valuation", _CORP,
           unit=UnitType.TIMES.value, formatting="ratio", method="DERIVED",
           inputs=("enterprise_value", "free_cash_flow"), formula="EV / FCF"))
    reg(_d("net_debt_to_ev", "Net Debt / EV", "valuation", _CORP,
           unit=UnitType.PERCENT.value, formatting="percent", method="DERIVED",
           inputs=("net_debt", "enterprise_value"),
           formula="Net Debt / EV = Net Debt / Enterprise Value × 100", higher_is_better=False))

    # ══════════════════════════════════════════════════════════════════
    # BANK — income statement & balance sheet
    # ══════════════════════════════════════════════════════════════════
    reg(_d("interest_earned", "Interest Earned", "income_statement", _BANK))
    reg(_d("interest_expended", "Interest Expended", "income_statement", _BANK))
    reg(_d("nii", "Net Interest Income", "income_statement", _BANK,
           method="FORMULA", inputs=("interest_earned", "interest_expended"),
           formula="NII = Interest Earned − Interest Expended",
           methodology="Core lending spread before provisions and operating costs."))
    reg(_d("bank_other_income", "Other Income (Bank)", "income_statement", _BANK,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("operating_expenses", "Operating Expenses", "income_statement", _BANK,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("bank_operating_profit", "Operating Profit (Bank)", "income_statement", _BANK,
           method="FORMULA", inputs=("nii", "bank_other_income", "operating_expenses"),
           formula="Operating Profit = NII + Other Income − Operating Expenses"))
    reg(_d("provisions", "Provisions & Contingencies", "income_statement", _BANK,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("bank_pbt", "Profit Before Tax (Bank)", "income_statement", _BANK,
           method="FORMULA", inputs=("bank_operating_profit", "provisions"),
           formula="PBT = Operating Profit − Provisions", requirement=Requirement.OPTIONAL.value))
    reg(_d("bank_tax", "Tax (Bank)", "income_statement", _BANK, requirement=Requirement.OPTIONAL.value))
    reg(_d("bank_pat", "Profit After Tax (Bank)", "income_statement", _BANK,
           method="FORMULA", inputs=("bank_pbt", "bank_tax"),
           formula="PAT = PBT − Tax", requirement=Requirement.OPTIONAL.value))
    reg(_d("advances", "Advances", "balance_sheet", _BANK,
           methodology="Customer loans and advances — the bank's core earning asset."))
    reg(_d("deposits", "Deposits", "balance_sheet", _BANK,
           methodology="Customer deposits — the bank's core funding."))
    reg(_d("casa_deposits", "CASA Deposits", "balance_sheet", _BANK,
           requirement=Requirement.OPTIONAL.value,
           methodology="Current + savings accounts: low-cost deposit funding."))
    reg(_d("casa_ratio", "CASA Ratio", "funding", _BANK,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("casa_deposits", "deposits"),
           formula="CASA Ratio = CASA Deposits / Total Deposits × 100",
           requirement=Requirement.OPTIONAL.value, higher_is_better=True))
    reg(_d("bank_cash", "Cash", "balance_sheet", _BANK, requirement=Requirement.OPTIONAL.value))
    reg(_d("balances_with_rbi", "Balances with RBI", "balance_sheet", _BANK, requirement=Requirement.OPTIONAL.value))
    reg(_d("balances_with_banks", "Balances with Banks", "balance_sheet", _BANK, requirement=Requirement.OPTIONAL.value))
    reg(_d("bank_investments", "Investments", "balance_sheet", _BANK,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("bank_borrowings", "Borrowings", "balance_sheet", _BANK, requirement=Requirement.OPTIONAL.value))
    reg(_d("other_liabilities_bank", "Other Liabilities", "balance_sheet", _BANK,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("bank_reserves", "Reserves & Surplus (Bank)", "balance_sheet", _BANK,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("bank_total_equity", "Total Equity (Bank)", "balance_sheet", _BANK,
           method="FORMULA", inputs=("share_capital", "bank_reserves"),
           formula="Total Equity = Share Capital + Reserves & Surplus"))

    # ══════════════════════════════════════════════════════════════════
    # BANK — performance
    # ══════════════════════════════════════════════════════════════════
    reg(_d("nim", "Net Interest Margin", "profitability", _BANK,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("nii", "interest_earned"),
           formula="NIM = NII / Average Interest-Earning Assets × 100",
           methodology="Finora uses interest-earned-based earning assets as the denominator proxy when "
                       "average earning assets are not separately disclosed: NII / Interest Earned × 100.",
           higher_is_better=True))
    reg(_d("cost_to_income", "Cost / Income", "profitability", _BANK,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("operating_expenses", "nii", "bank_other_income"),
           formula="Cost / Income = Operating Expenses / (NII + Other Income) × 100",
           higher_is_better=False))
    reg(_d("bank_roa", "ROA (Bank)", "profitability", _BANK,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("bank_pat", "total_assets"),
           formula="ROA = PAT / Total Assets × 100", higher_is_better=True))
    reg(_d("bank_roe", "ROE (Bank)", "profitability", _BANK,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("bank_pat", "bank_total_equity"),
           formula="ROE = PAT / Total Equity × 100", higher_is_better=True))

    # ══════════════════════════════════════════════════════════════════
    # BANK — asset quality
    # ══════════════════════════════════════════════════════════════════
    reg(_d("gnpa", "Gross NPA", "asset_quality", _BANK,
           requirement=Requirement.OPTIONAL.value,
           methodology="Gross non-performing assets per RBI classification."))
    reg(_d("gnpa_pct", "GNPA %", "asset_quality", _BANK,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("gnpa", "advances"), formula="GNPA % = Gross NPA / Gross Advances × 100",
           higher_is_better=False))
    reg(_d("nnpa", "Net NPA", "asset_quality", _BANK, requirement=Requirement.OPTIONAL.value))
    reg(_d("nnpa_pct", "NNPA %", "asset_quality", _BANK,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("nnpa", "advances"), formula="NNPA % = Net NPA / Net Advances × 100",
           higher_is_better=False))
    reg(_d("provision_coverage_ratio", "Provision Coverage Ratio", "asset_quality", _BANK,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("gnpa", "nnpa"),
           formula="PCR = (GNPA − NNPA) / GNPA × 100",
           methodology="Provisions held against gross NPAs: (GNPA − NNPA) / GNPA.",
           higher_is_better=True))
    reg(_d("credit_cost", "Credit Cost", "asset_quality", _BANK,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("provisions", "advances"),
           formula="Credit Cost = Provisions / Advances × 100",
           higher_is_better=False))

    # ══════════════════════════════════════════════════════════════════
    # BANK — funding & capital
    # ══════════════════════════════════════════════════════════════════
    reg(_d("credit_to_deposit", "Credit / Deposit Ratio", "funding", _BANK,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("advances", "deposits"),
           formula="Credit / Deposit = Advances / Deposits × 100"))
    reg(_d("deposit_growth", "Deposit Growth", "growth", _BANK,
           unit=UnitType.PERCENT.value, formatting="percent", method="DERIVED",
           inputs=("deposits",), formula="Deposit Growth = YoY change in Deposits",
           higher_is_better=True))
    reg(_d("advances_growth", "Advances Growth", "growth", _BANK,
           unit=UnitType.PERCENT.value, formatting="percent", method="DERIVED",
           inputs=("advances",), formula="Advances Growth = YoY change in Advances",
           higher_is_better=True))
    reg(_d("nii_growth", "NII Growth", "growth", _BANK,
           unit=UnitType.PERCENT.value, formatting="percent", method="DERIVED",
           inputs=("nii",), formula="NII Growth = YoY change in NII", higher_is_better=True))
    reg(_d("capital_adequacy_ratio", "Capital Adequacy Ratio", "capital", _BANK,
           unit=UnitType.PERCENT.value, formatting="percent", method="REPORTED",
           requirement=Requirement.OPTIONAL.value,
           methodology="Total capital (Tier 1 + Tier 2) to risk-weighted assets, per Basel III / RBI norms.",
           higher_is_better=True))
    reg(_d("cet1_ratio", "CET1 Ratio", "capital", _BANK,
           unit=UnitType.PERCENT.value, formatting="percent", method="REPORTED",
           requirement=Requirement.OPTIONAL.value, higher_is_better=True))
    reg(_d("tier1_ratio", "Tier 1 Capital Ratio", "capital", _BANK,
           unit=UnitType.PERCENT.value, formatting="percent", method="REPORTED",
           requirement=Requirement.OPTIONAL.value, higher_is_better=True))

    # ══════════════════════════════════════════════════════════════════
    # NBFC — statements
    # ══════════════════════════════════════════════════════════════════
    reg(_d("total_income_nbfc", "Total Income (NBFC)", "income_statement", _NBFC))
    reg(_d("nbfc_interest_income", "Interest Income", "income_statement", _NBFC,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("nbfc_interest_expense", "Interest Expense", "income_statement", _NBFC,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("nbfc_nii", "Net Interest Income (NBFC)", "income_statement", _NBFC,
           method="FORMULA", inputs=("nbfc_interest_income", "nbfc_interest_expense"),
           formula="NII = Interest Income − Interest Expense",
           requirement=Requirement.CONDITIONAL.value,
           conditional_when="When interest income and expense are separately disclosed"))
    reg(_d("fee_income", "Fee / Other Income", "income_statement", _NBFC,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("nbfc_operating_expenses", "Operating Expenses", "income_statement", _NBFC,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("nbfc_ppop", "Pre-Provision Operating Profit", "income_statement", _NBFC,
           method="FORMULA", inputs=("nbfc_nii", "fee_income", "nbfc_operating_expenses"),
           formula="PPOP = NII + Fee Income − Operating Expenses",
           requirement=Requirement.OPTIONAL.value))
    reg(_d("nbfc_provisions", "Provisions", "income_statement", _NBFC, requirement=Requirement.OPTIONAL.value))
    reg(_d("nbfc_pbt", "PBT (NBFC)", "income_statement", _NBFC,
           method="FORMULA", inputs=("nbfc_ppop", "nbfc_provisions"),
           formula="PBT = PPOP − Provisions", requirement=Requirement.OPTIONAL.value))
    reg(_d("nbfc_tax", "Tax (NBFC)", "income_statement", _NBFC, requirement=Requirement.OPTIONAL.value))
    reg(_d("nbfc_pat", "PAT (NBFC)", "income_statement", _NBFC,
           method="FORMULA", inputs=("nbfc_pbt", "nbfc_tax"),
           formula="PAT = PBT − Tax", requirement=Requirement.OPTIONAL.value))
    reg(_d("loan_book", "Loans / Financing Assets", "balance_sheet", _NBFC,
           methodology="Net carrying value of loans and advances to customers."))
    reg(_d("nbfc_investments", "Investments", "balance_sheet", _NBFC, requirement=Requirement.OPTIONAL.value))
    reg(_d("nbfc_cash", "Cash & Bank Balances", "balance_sheet", _NBFC, requirement=Requirement.OPTIONAL.value))
    reg(_d("debt_securities", "Debt Securities", "balance_sheet", _NBFC, requirement=Requirement.OPTIONAL.value))
    reg(_d("bank_borrowings_nbfc", "Bank Borrowings", "balance_sheet", _NBFC, requirement=Requirement.OPTIONAL.value))
    reg(_d("commercial_paper", "Commercial Paper", "balance_sheet", _NBFC,
           requirement=Requirement.OPTIONAL.value,
           conditional_when="When CP is outstanding"))
    reg(_d("securitisation", "Securitisation / Assignment", "balance_sheet", _NBFC,
           requirement=Requirement.OPTIONAL.value,
           conditional_when="When securitisation/assignment is used"))
    reg(_d("nbfc_borrowings", "Total Borrowings", "balance_sheet", _NBFC,
           method="FORMULA",
           inputs=("bank_borrowings_nbfc", "debt_securities", "commercial_paper", "subordinated_debt"),
           formula="Total Borrowings = Bank Borrowings + Debt Securities + Commercial Paper + Subordinated Debt",
           requirement=Requirement.OPTIONAL.value))
    reg(_d("subordinated_debt", "Subordinated Debt", "balance_sheet", _NBFC, requirement=Requirement.OPTIONAL.value))
    reg(_d("other_liabilities_nbfc", "Other Liabilities", "balance_sheet", _NBFC,
           requirement=Requirement.OPTIONAL.value))
    reg(_d("nbfc_net_worth", "Net Worth (NBFC)", "balance_sheet", _NBFC,
           method="FORMULA", inputs=("share_capital", "bank_reserves"),
           formula="Net Worth = Share Capital + Reserves & Surplus"))
    reg(_d("aum", "Assets Under Management", "balance_sheet", _NBFC,
           requirement=Requirement.CONDITIONAL.value,
           conditional_when="When AUM is disclosed; on-balance-sheet loan book is the floor",
           methodology="Managed + on-balance-sheet assets. Finora reports disclosed AUM; loan book is reported separately."))
    reg(_d("nbfc_total_assets", "Total Assets (NBFC)", "balance_sheet", _NBFC))

    # ══════════════════════════════════════════════════════════════════
    # NBFC — growth / profitability / asset quality / leverage
    # ══════════════════════════════════════════════════════════════════
    reg(_d("aum_growth", "AUM Growth", "growth", _NBFC,
           unit=UnitType.PERCENT.value, formatting="percent", method="DERIVED",
           inputs=("aum",), formula="AUM Growth = YoY change in AUM",
           requirement=Requirement.CONDITIONAL.value, conditional_when="Requires disclosed AUM history",
           higher_is_better=True))
    reg(_d("loan_book_growth", "Loan Book Growth", "growth", _NBFC,
           unit=UnitType.PERCENT.value, formatting="percent", method="DERIVED",
           inputs=("loan_book",), formula="Loan Book Growth = YoY change in Loan Book",
           higher_is_better=True))
    reg(_d("nbfc_income_growth", "Income Growth", "growth", _NBFC,
           unit=UnitType.PERCENT.value, formatting="percent", method="DERIVED",
           inputs=("total_income_nbfc",), formula="Income Growth = YoY change in Total Income",
           higher_is_better=True))
    reg(_d("nbfc_nii_growth", "NII Growth (NBFC)", "growth", _NBFC,
           unit=UnitType.PERCENT.value, formatting="percent", method="DERIVED",
           inputs=("nbfc_nii",), formula="NII Growth = YoY change in NII",
           requirement=Requirement.CONDITIONAL.value, conditional_when="Requires NII disclosure",
           higher_is_better=True))
    reg(_d("nbfc_pat_growth", "PAT Growth", "growth", _NBFC,
           unit=UnitType.PERCENT.value, formatting="percent", method="DERIVED",
           inputs=("nbfc_pat",), formula="PAT Growth = YoY change in PAT", higher_is_better=True))
    reg(_d("nbfc_eps_growth", "EPS Growth", "growth", _NBFC,
           unit=UnitType.PERCENT.value, formatting="percent", method="DERIVED",
           inputs=("eps_diluted",), formula="EPS Growth = YoY change in diluted EPS", higher_is_better=True))
    reg(_d("nbfc_nim", "NIM (NBFC)", "profitability", _NBFC,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("nbfc_nii", "loan_book"),
           formula="NIM = NII / Loan Book × 100",
           requirement=Requirement.CONDITIONAL.value,
           conditional_when="When NII is disclosed; loan-book-based approximation",
           higher_is_better=True))
    reg(_d("nbfc_roa", "ROA (NBFC)", "profitability", _NBFC,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("nbfc_pat", "nbfc_total_assets"),
           formula="ROA = PAT / Total Assets × 100", higher_is_better=True))
    reg(_d("nbfc_roe", "ROE (NBFC)", "profitability", _NBFC,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("nbfc_pat", "nbfc_net_worth"),
           formula="ROE = PAT / Net Worth × 100", higher_is_better=True))
    reg(_d("nbfc_cost_to_income", "Cost / Income (NBFC)", "profitability", _NBFC,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("nbfc_operating_expenses", "total_income_nbfc"),
           formula="Cost / Income = Operating Expenses / Total Income × 100", higher_is_better=False))
    reg(_d("stage3_gross", "Gross Stage 3", "asset_quality", _NBFC,
           requirement=Requirement.OPTIONAL.value,
           methodology="Ind AS 109 Stage 3 loans (credit-impaired) — India's NBFC equivalent of GNPA."))
    reg(_d("stage3_gross_pct", "Gross Stage 3 %", "asset_quality", _NBFC,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("stage3_gross", "loan_book"),
           formula="Gross Stage 3 % = Stage 3 Loans / Loan Book × 100",
           requirement=Requirement.CONDITIONAL.value, conditional_when="When stage-3 disclosure exists",
           higher_is_better=False))
    reg(_d("stage3_net", "Net Stage 3", "asset_quality", _NBFC, requirement=Requirement.OPTIONAL.value))
    reg(_d("stage3_net_pct", "Net Stage 3 %", "asset_quality", _NBFC,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("stage3_net", "loan_book"),
           formula="Net Stage 3 % = Net Stage 3 / Loan Book × 100",
           requirement=Requirement.CONDITIONAL.value, conditional_when="When stage-3 disclosure exists",
           higher_is_better=False))
    reg(_d("nbfc_credit_cost", "Credit Cost (NBFC)", "asset_quality", _NBFC,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("nbfc_provisions", "loan_book"),
           formula="Credit Cost = Provisions / Loan Book × 100", higher_is_better=False))
    reg(_d("nbfc_provision_coverage", "Provision Coverage (NBFC)", "asset_quality", _NBFC,
           unit=UnitType.PERCENT.value, formatting="percent", method="FORMULA",
           inputs=("stage3_gross", "stage3_net"),
           formula="Provision Coverage = (Stage 3 Gross − Stage 3 Net) / Stage 3 Gross × 100",
           requirement=Requirement.CONDITIONAL.value, conditional_when="When stage-3 disclosure exists",
           higher_is_better=True))
    reg(_d("nbfc_debt_to_equity", "Debt / Equity (NBFC)", "leverage", _NBFC,
           unit=UnitType.RATIO.value, formatting="ratio", method="FORMULA",
           inputs=("nbfc_borrowings", "nbfc_net_worth"),
           formula="Debt / Equity = Total Borrowings / Net Worth", higher_is_better=False))
    reg(_d("nbfc_leverage_ratio", "Leverage Ratio", "leverage", _NBFC,
           unit=UnitType.TIMES.value, formatting="ratio", method="FORMULA",
           inputs=("nbfc_total_assets", "nbfc_net_worth"),
           formula="Leverage = Total Assets / Net Worth", higher_is_better=False))
    reg(_d("nbfc_capital_adequacy", "Capital Adequacy (NBFC)", "leverage", _NBFC,
           unit=UnitType.PERCENT.value, formatting="percent", method="REPORTED",
           requirement=Requirement.OPTIONAL.value,
           methodology="Capital to risk-weighted assets per NBFC norms (typically 15% minimum).",
           higher_is_better=True))
    reg(_d("nbfc_interest_coverage", "Interest Coverage (NBFC)", "leverage", _NBFC,
           unit=UnitType.TIMES.value, formatting="ratio", method="FORMULA",
           inputs=("nbfc_pbt", "nbfc_interest_expense"),
           formula="Interest Coverage = (PBT + Interest Expense) / Interest Expense",
           methodology="Earnings before interest and tax over interest expense; only meaningful when interest expense is disclosed.",
           requirement=Requirement.CONDITIONAL.value, conditional_when="When interest expense is disclosed",
           higher_is_better=True))
    reg(_d("book_value_per_share", "Book Value / Share", "valuation", _BANK | _NBFC,
           unit=UnitType.PER_SHARE.value, formatting="eps", method="DERIVED",
           inputs=("total_equity", "shares_outstanding"),
           formula="Book Value / Share = Total Equity / Shares Outstanding"))
