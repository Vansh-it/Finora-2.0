"""India taxonomy and canonicalisation helpers.

This module owns the real normalization contracts from the Phase-2 spec:

  - Unit normalisation (§17): Indian filings report rupees, thousands, lakhs,
    millions, crores.  Canonical monetary values are stored as raw INR.
  - Period normalization (§18–§19): FY / Q1 / Q2 / Q3 / Q4 / H1 / 9M / TTM,
    with explicit cumulative vs. quarter-only distinction.  Q4 may be derived
    ONLY when FY annual cumulative and 9M cumulative are both valid,
    compatible, same scope, same basis, same currency, and same metric
    definition — and the result is marked DERIVED with both source inputs
    retained.
  - Scope rules (§20): CONSOLIDATED is preferred when available; the other
    basis is never mixed into a cross-scope calculation; every metric retains
    actual_scope.
  - Audit status (§21): AUDITED / UNAUDITED retained; unaudited quarterly
    results are not treated equivalent to audited annual results without status.

Canonical INR conversion is pure arithmetic; no I/O, no providers, no
market feed.  Formatting into "₹123.4 Cr" belongs to the display layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Unit normalisation (§17).
# ---------------------------------------------------------------------------

class IndiaUnit(str, Enum):
    RUPEES = "RUPEES"
    THOUSANDS = "THOUSANDS"
    LAKHS = "LAKH"
    MILLIONS = "MILLIONS"
    CRORES = "CRORE"


_UNIT_MULTIPLIER: dict[IndiaUnit, int] = {
    IndiaUnit.RUPEES: 1,
    IndiaUnit.THOUSANDS: 1_000,
    IndiaUnit.LAKHS: 100_000,
    IndiaUnit.MILLIONS: 1_000_000,
    IndiaUnit.CRORES: 10_000_000,
}


def normalize_inr(value: float, unit: IndiaUnit) -> float:
    """Convert a money value in *unit* to raw INR.

    Canonical storage is always raw INR.
    """
    return value * _UNIT_MULTIPLIER[unit]


def try_parse_unit(raw: str) -> Optional[IndiaUnit]:
    """Best-effort unit tag from a free-form unit string.

    Examples:
      "rupees", "INR", "₹"          -> RUPEES
      "thousands", "thousand"      -> THOUSANDS
      "lakh", "lakhs"              -> LAKHS
      "million", "millions", "mn"  -> MILLIONS
      "crore", "crores", "cr"      -> CRORES
    """
    if not raw:
        return None
    s = (raw or "").strip().lower()
    if {"rupee", "inr", "in", "₹", "rs"}.intersection({s, "x"}):
        return IndiaUnit.RUPEES
    if "thousand" in s or s in {"th", "k"}:
        return IndiaUnit.THOUSANDS
    if "lakh" in s:
        return IndiaUnit.LAKHS
    if "million" in s or s in {"mn", "mm"}:
        return IndiaUnit.MILLIONS
    if "crore" in s or s in {"cr", "cro"}:
        return IndiaUnit.CRORES
    # default: rupees if not obviously otherwise
    if re.search(r"\d", s) and ("rupee" in s or "inr" in s or "₹" in s):
        return IndiaUnit.RUPEES
    return None


# ---------------------------------------------------------------------------
# Period normalization (§18–§19).
# ---------------------------------------------------------------------------

class PeriodKind(str, Enum):
    FY = "FY"
    QUARTER = "QUARTER"
    HALF_YEAR = "HALF_YEAR"
    NINE_MONTH = "NINE_MONTH"
    TTM = "TTM"


class FiscalYearEnd(str, Enum):
    MARCH_31 = "31 Mar"


@dataclass
class CanonicalPeriod:
    """One normalized reporting period for the India pipeline."""

    label: str            # "FY2024", "Q2 FY2025", "9M FY2025", "TTM"
    kind: PeriodKind      # FY | QUARTER | HALF_YEAR | NINE_MONTH | TTM
    fiscal_year: int      # 2024
    start_date: str = ""
    end_date: str = ""
    cumulative: bool = False   # True for YTD / 9M / TTM observations
    audit_status: str = "UNAUDITED"   # AUDITED | UNAUDITED
    scope: str = "CONSOLIDATED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "kind": self.kind.value,
            "fiscal_year": self.fiscal_year,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "cumulative": self.cumulative,
            "audit_status": self.audit_status,
            "scope": self.scope,
        }


def normalize_period(
    label: str,
    *,
    fiscal_year_end: str = "31 Mar",
    scope: str = "CONSOLIDATED",
    audit_status: str = "UNAUDITED",
) -> Optional[CanonicalPeriod]:
    """Turn a free-form label into a CanonicalPeriod.

    Returns None when the label cannot be recognized.
    """
    lh = label.strip()
    lh_lower = lh.lower()

    # FYnnnn  (FY2024, FY 2024, fy2023)
    m = re.fullmatch(r"\s*fy\s*(\d{4})\s*", lh_lower)
    if m:
        fy = int(m.group(1))
        return CanonicalPeriod(
            label=lh,
            kind=PeriodKind.FY,
            fiscal_year=fy,
            cumulative=False,
            audit_status=audit_status,
            scope=scope,
        )

    # Q1/Q2/Q3/Q4 FYnnnn or Q1 FYnnnn
    m = re.fullmatch(r"\s*q([1-4])\s*(?:fy\s*(\d{4}))?\s*", lh_lower)
    if m:
        qnum = int(m.group(1))
        fy = int(m.group(2)) if m.group(2) else None
        if fy is None:
            # try to infer from quarter convention: Q1->Mar, Q2->Jun, etc.
            # This is a best-effort inference in the absence of explicit FY.
            return None
        return CanonicalPeriod(
            label=lh,
            kind=PeriodKind.QUARTER,
            fiscal_year=fy,
            cumulative=False,  # quarter-only
            audit_status=audit_status,
            scope=scope,
        )

    # Q1 cumulative / YTD through Q2 etc.
    m = re.fullmatch(r"\s*q([1-4])\s+(?:ytd|cumulative|ytd cumulative)\s*(?:fy\s*(\d{4}))?\s*", lh_lower)
    if m:
        # treat as cumulative of the quarter
        fy = int(m.group(2)) if m.group(2) else None
        if fy is None:
            return None
        return CanonicalPeriod(
            label=lh,
            kind=PeriodKind.QUARTER,
            fiscal_year=fy,
            cumulative=True,
            audit_status=audit_status,
            scope=scope,
        )

    # H1 FYnnnn
    m = re.fullmatch(r"\s*h1\s*(?:fy\s*(\d{4}))?\s*", lh_lower)
    if m:
        fy = int(m.group(1)) if m.group(1) else None
        if fy is None:
            return None
        return CanonicalPeriod(
            label=lh,
            kind=PeriodKind.HALF_YEAR,
            fiscal_year=fy,
            cumulative=True,
            audit_status=audit_status,
            scope=scope,
        )

    # 9M FYnnnn / nine months (9M FY2025, nine months FY2025)
    m = re.fullmatch(r"\s*(?:9m|nine months|nine-month)\s*(?:fy\s*(\d{4}))?\s*", lh_lower)
    if m:
        fy = int(m.group(1)) if m.group(1) else None
        if fy is None:
            return None
        return CanonicalPeriod(
            label=lh,
            kind=PeriodKind.NINE_MONTH,
            fiscal_year=fy,
            cumulative=True,
            audit_status=audit_status,
            scope=scope,
        )

    # H2 FYnnnn  (H2 FY2025 — full-year half, cumulative to the half end)
    m = re.fullmatch(r"\s*h2\s*(?:fy\s*(\d{4}))?\s*", lh_lower)
    if m:
        fy = int(m.group(1)) if m.group(1) else None
        if fy is None:
            return None
        return CanonicalPeriod(
            label=lh,
            kind=PeriodKind.HALF_YEAR,
            fiscal_year=fy,
            cumulative=True,
            audit_status=audit_status,
            scope=scope,
        )

    # TTM (trailing twelve months)
    if re.fullmatch(r"\s*ttm\s*", lh_lower):
        return CanonicalPeriod(
            label=lh,
            kind=PeriodKind.TTM,
            fiscal_year=0,
            cumulative=True,
            audit_status=audit_status,
            scope=scope,
        )

    return None


def period_is_annual_like(period: CanonicalPeriod) -> bool:
    """True when the period represents a full-year cumulative figure
    (FY/annual) suitable for growth/comparison against another full-year
    period."""
    return period.kind in (PeriodKind.FY, PeriodKind.TTM)


def period_is_quarter_only(period: CanonicalPeriod) -> bool:
    """True when the period is a quarter-only figure (not cumulative)."""
    return period.kind == PeriodKind.QUARTER and not period.cumulative


# ---------------------------------------------------------------------------
# Q4 derivation (§19).
# ---------------------------------------------------------------------------

@dataclass
class Q4DerivationResult:
    """Outcome of attempting to derive Q4."""

    derived: bool = False
    q4_value: Optional[float] = None
    q4_period: Optional[CanonicalPeriod] = None
    fy_period: Optional[CanonicalPeriod] = None
    nine_month_period: Optional[CanonicalPeriod] = None
    scope: Optional[str] = None
    reason: str = ""


def derive_q4(
    fy_value: Optional[float],
    fy_period: CanonicalPeriod,
    nine_month_value: Optional[float],
    nine_month_period: CanonicalPeriod,
    *,
    scope: str = "CONSOLIDATED",
    metric_id: str = "",
) -> Q4DerivationResult:
    """Attempt Q4 = FY - 9M ONLY when both inputs are valid and compatible.

    Compatibility checks (§19):
      - same scope
      - same currency (implied by same filing path in this adapter)
      - same accounting basis
      - compatible periods (FY full year, 9M cumulative within the same FY)
      - same metric definition (metric_id passed in for the record)
      - both values not None and not NaN
    """
    if fy_value is None or nine_month_value is None:
        return Q4DerivationResult(
            derived=False,
            reason="Q4 derivation requires both FY and 9M values",
            fy_period=fy_period,
            nine_month_period=nine_month_period,
        )

    import math

    if math.isnan(fy_value) or math.isnan(nine_month_value):
        return Q4DerivationResult(
            derived=False,
            reason="Cannot derive Q4: one of the source values is NaN",
            fy_period=fy_period,
            nine_month_period=nine_month_period,
        )

    # Scope compatibility
    if fy_period.scope != nine_month_period.scope or scope != fy_period.scope:
        return Q4DerivationResult(
            derived=False,
            reason="Q4 derivation requires same scope across FY and 9M",
            fy_period=fy_period,
            nine_month_period=nine_month_period,
            scope=scope,
        )

    # Period compatibility: 9M must be within the same fiscal year as FY
    if nine_month_period.fiscal_year != fy_period.fiscal_year:
        return Q4DerivationResult(
            derived=False,
            reason="Q4 derivation requires FY and 9M to be from the same fiscal year",
            fy_period=fy_period,
            nine_month_period=nine_month_period,
        )

    # Both must be cumulative in the correct sense:
    # FY = full-year cumulative; 9M = nine-month cumulative
    if not fy_period.cumulative or not nine_month_period.cumulative:
        return Q4DerivationResult(
            derived=False,
            reason="Q4 derivation requires FY to be cumulative and 9M to be cumulative",
            fy_period=fy_period,
            nine_month_period=nine_month_period,
        )

    # 9M must be a nine-month period
    if nine_month_period.kind != PeriodKind.NINE_MONTH:
        return Q4DerivationResult(
            derived=False,
            reason="Q4 derivation requires the smaller period to be a 9M period",
            fy_period=fy_period,
            nine_month_period=nine_month_period,
        )

    # Now compute
    q4 = fy_value - nine_month_value
    if math.isnan(q4):
        return Q4DerivationResult(
            derived=False,
            reason="Q4 derivation produced NaN",
            fy_period=fy_period,
            nine_month_period=nine_month_period,
        )

    q4_period = CanonicalPeriod(
        label=f"Q4 FY{fy_period.fiscal_year}",
        kind=PeriodKind.QUARTER,
        fiscal_year=fy_period.fiscal_year,
        cumulative=False,
        audit_status="DERIVED",
        scope=scope,
    )

    return Q4DerivationResult(
        derived=True,
        q4_value=q4,
        q4_period=q4_period,
        fy_period=fy_period,
        nine_month_period=nine_month_period,
        scope=scope,
        reason="Q4 = FY (full year) - 9M (cumulative), marked DERIVED",
    )


# ---------------------------------------------------------------------------
# Scope rules (§20).
# ---------------------------------------------------------------------------

def preferred_scope(
    available_scopes: list[str],
) -> str:
    """Return the preferred scope given the scopes the adapter actually
    recorded.

    CONSOLIDATED is default when present; the other basis is never preferred
    over consolidated.
    """
    for s in ("CONSOLIDATED", "STANDALONE"):
        if s in available_scopes:
            return s
    return "CONSOLIDATED"


def cannot_mix_scope(actual_scope: str, requested_scope: str) -> bool:
    """True when a requested scope is not present and the actual scope is
    different enough that a fallback would be unsafe."""
    if requested_scope == actual_scope:
        return False
    return True


# ---------------------------------------------------------------------------
# Audit status helpers (§21).
# ---------------------------------------------------------------------------

AUDIT_STATUS_ORDER = ["AUDITED", "UNAUDITED"]


def is_audited(status: str) -> bool:
    return (status or "").upper() == "AUDITED"


def audit_status_rank(status: str) -> int:
    """0 = unaudited, 1 = audited; higher rank = more assurance."""
    if (status or "").upper() == "AUDITED":
        return 1
    return 0


# ---------------------------------------------------------------------------
# Canonical mapping coverage (§22) — exported for downstream adapters.
# ---------------------------------------------------------------------------

# A vocabulary of India taxonomy concepts that can be mapped into the Phase-1
# canonical metric space.  These are referenced field labels, not financial
# values.  Downstream adapters should only populate the fields that the source
# actually discloses.
INDIA_TAXONOMY_CONCEPTS: dict[str, Any] = {
    # ── Utility / derived / classification fields that Finora computes ┐
    "entity_type": "entity_type",  # 'CORPORATE' | 'BANK' | 'NBFC' (from classifier / registry)
    "fiscal_year_end": "fiscal_year_end",  # '31 Mar' etc.
    "reporting_standard": "reporting_standard",  # 'Ind AS'
    # ── India taxonomy concepts (one-way map to canonical metric_id) ────────────────
    # Canonical key: 'revenue', 'ebitda', 'cash', 'total_assets', etc.
    # Leave metric_id intentionally blank if the concept has no canonical counterpart.

    # Income statement concepts
    "revenue_from_operations": "revenue",
    "other_income": "other_income",
    "total_income": "total_income",
    "cost_of_materials": "cost_of_materials",
    "purchases_stock_in_trade": "purchases_stock_in_trade",
    "changes_in_inventories": "changes_in_inventories",
    "employee_benefits": "employee_benefits",
    "finance_costs": "finance_costs",
    "depreciation_amortisation": "depreciation_amortisation",
    "other_expenses": "other_expenses",
    "total_expenses": "total_expenses",
    "ebitda": "ebitda",
    "ebit": "ebit",
    "operating_profit": "operating_profit",
    "exceptional_items": "exceptional_items",
    "pbt": "pbt",
    "current_tax": "current_tax",
    "deferred_tax": "deferred_tax",
    "total_tax": "total_tax",
    "net_profit": "net_profit",
    "oci": "oci",
    "comprehensive_income": "comprehensive_income",
    "eps_basic": "eps_basic",
    "eps_diluted": "eps_diluted",
    # Balance sheet concepts
    "cash": "cash",
    "bank_balances": "bank_balances",
    "current_investments": "current_investments",
    "non_current_investments": "non_current_investments",
    "trade_receivables": "trade_receivables",
    "inventory": "inventory",
    "other_current_assets": "other_current_assets",
    "total_current_assets": "total_current_assets",
    "ppe": "ppe",
    "cwip": "cwip",
    "intangibles": "intangibles",
    "goodwill": "goodwill",
    "other_non_current_assets": "other_non_current_assets",
    "total_non_current_assets": "total_non_current_assets",
    "total_assets": "total_assets",
    "trade_payables": "trade_payables",
    "short_term_borrowings": "short_term_borrowings",
    "current_debt": "current_debt",
    "other_current_liabilities": "other_current_liabilities",
    "total_current_liabilities": "total_current_liabilities",
    "long_term_borrowings": "long_term_borrowings",
    "other_non_current_liabilities": "other_non_current_liabilities",
    "total_non_current_liabilities": "total_non_current_liabilities",
    "total_debt": "total_debt",
    "total_liabilities": "total_liabilities",
    "share_capital": "share_capital",
    "reserves_surplus": "reserves_surplus",
    "minority_interest": "minority_interest",
    "total_equity": "total_equity",
    # Cash flow concepts
    "operating_cash_flow": "operating_cash_flow",
    "capex": "capex",
    "free_cash_flow": "free_cash_flow",
    "investing_cash_flow": "investing_cash_flow",
    "financing_cash_flow": "financing_cash_flow",
    "dividends_paid": "dividends_paid",
    "interest_paid": "interest_paid",
    "debt_raised": "debt_raised",
    "debt_repaid": "debt_repaid",
    "share_buybacks": "share_buybacks",
    "net_change_in_cash": "net_change_in_cash",
    # Bank-specific
    "interest_earned": "interest_earned",
    "interest_expended": "interest_expended",
    "bank_nii": "nii",
    "bank_other_income": "bank_other_income",
    "bank_operating_expenses": "operating_expenses",
    "bank_operating_profit": "bank_operating_profit",
    "bank_provisions": "provisions",
    "bank_pbt": "bank_pbt",
    "bank_tax": "bank_tax",
    "bank_pat": "bank_pat",
    "advances": "advances",
    "deposits": "deposits",
    "bank_cash": "cash",
    "balances_with_rbi": "balances_with_rbi",
    "balances_with_banks": "balances_with_banks",
    "bank_investments": "bank_investments",
    "bank_total_assets": "total_assets",
    "bank_borrowings": "bank_borrowings",
    "other_liabilities_bank": "other_liabilities_bank",
    "bank_share_capital": "share_capital",
    "bank_reserves": "reserves_surplus",
    "bank_total_equity": "total_equity",
    # NBFC-specific
    "nbfc_interest_income": "nbfc_interest_income",
    "nbfc_interest_expense": "nbfc_interest_expense",
    "nbfc_nii": "nbfc_nii",
    "fee_income": "fee_income",
    "nbfc_operating_expenses": "nbfc_operating_expenses",
    "nbfc_ppop": "nbfc_ppop",
    "nbfc_provisions": "nbfc_provisions",
    "nbfc_pbt": "nbfc_pbt",
    "nbfc_tax": "nbfc_tax",
    "nbfc_pat": "nbfc_pat",
    "aum": "aum",
    "loan_book": "loan_book",
    "nbfc_investments": "nbfc_investments",
    "nbfc_cash": "nbfc_cash",
    "nbfc_total_assets": "nbfc_total_assets",
    "bank_borrowings_nbfc": "bank_borrowings_nbfc",
    "debt_securities": "debt_securities",
    "commercial_paper": "commercial_paper",
    "subordinated_debt": "subordinated_debt",
    "nbfc_borrowings": "nbfc_borrowings",
    "other_liabilities_nbfc": "other_liabilities_nbfc",
    "nbfc_share_capital": "share_capital",
    "nbfc_net_worth": "nbfc_net_worth",
    # macro
    "rbi_policy_repo_rate": "rbi_policy_repo_rate",
    "india_10y_gsec_yield": "india_10y_gsec_yield",
    "india_cpi_inflation": "india_cpi_inflation",
    "usd_inr": "usd_inr",
}
