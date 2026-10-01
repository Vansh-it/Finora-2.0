"""Arithmetic validation of extracted statements.

This is the check that decides whether Finora believes a number. A PDF text
layer damages digits silently, so a row can parse cleanly, pass every format
check, and still be wrong. The only defence that does not involve guessing is
arithmetic: statements are internally consistent, and a filing whose own totals
do not add up is reporting either damage or a misread column.

Every check here is an identity the filing itself asserts. Nothing is
reconstructed: a failure is reported and the affected metrics are withheld.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("finora.india.validator")


#: Relative tolerance for an identity. Indian statements round to the nearest
#: lakh, so exact equality is the wrong test; 0.5% of the larger side absorbs
#: rounding while still catching a single transposed or dropped digit.
DEFAULT_TOLERANCE = 0.005

#: Below this magnitude an identity is not tested. A statement in absolute
#: rupees can legitimately differ by rounding in the last digits, and small
#: totals make a percentage test meaningless.
MIN_MAGNITUDE = 1.0

#: Per-share earnings above this are treated as a reading error. The highest
#: EPS among Nifty 500 constituents sits in the low hundreds, so the bound is
#: loose enough not to catch a real outlier and tight enough to catch the
#: hundredfold shift a misplaced decimal point produces.
MAX_PLAUSIBLE_EPS = 1_000.0

#: A statement must test at least this many identities to count as verified.
#: One is the minimum that can distinguish a figure from the rest of its own
#: statement; below that the page is being read, not checked.
MIN_CHECKS_FOR_EVIDENCE = 1


@dataclass
class IdentityCheck:
    """One arithmetic identity and the outcome of testing it."""

    name: str
    lhs: float
    rhs: float
    passed: bool
    difference: float = 0.0
    #: The metrics whose value is in doubt if this identity fails.
    metrics: tuple[str, ...] = ()
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "lhs": self.lhs,
            "rhs": self.rhs,
            "passed": self.passed,
            "difference": round(self.difference, 4),
            "metrics": list(self.metrics),
            "detail": self.detail,
        }


@dataclass
class ValidationReport:
    """The outcome of validating one statement, for one period and column."""

    passed: bool = True
    checks: list[IdentityCheck] = field(default_factory=list)
    #: Metrics that a failed identity makes untrustworthy.
    quarantined: set[str] = field(default_factory=set)
    tolerance: float = DEFAULT_TOLERANCE
    notes: list[str] = field(default_factory=list)

    @property
    def failures(self) -> list[IdentityCheck]:
        return [c for c in self.checks if not c.passed]

    def merge(self, other: "ValidationReport") -> "ValidationReport":
        """Fold another report for the same statement into this one.

        A statement produces more than one report: the arithmetic identities,
        then the provenance rules for reconstructed figures. Publishing needs
        the union of what both withheld, and merge returns a new report rather
        than mutating either so the individual passes stay inspectable.
        """
        return ValidationReport(
            passed=self.passed and other.passed,
            checks=[*self.checks, *other.checks],
            quarantined={*self.quarantined, *other.quarantined},
            tolerance=self.tolerance,
            notes=[*self.notes, *other.notes],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "tolerance": self.tolerance,
            "checks": [c.to_dict() for c in self.checks],
            "failed": [c.name for c in self.failures],
            "quarantined": sorted(self.quarantined),
            "notes": list(self.notes),
        }


class StatementValidator:
    """Test the arithmetic identities a statement of accounts asserts.

    Identities are supplied as data rather than hard-coded per company, because
    the line items an Indian filing prints vary by sector and by entity type.
    An identity is a name, the metrics summed on each side, and whether the
    left side should equal the right side or merely not exceed it.
    """

    def __init__(self, tolerance: float = DEFAULT_TOLERANCE) -> None:
        self.tolerance = tolerance

    # -- comparison ------------------------------------------------------
    def _within(self, lhs: float, rhs: float) -> tuple[bool, float]:
        difference = abs(lhs - rhs)
        scale = max(abs(lhs), abs(rhs))
        if scale < MIN_MAGNITUDE:
            return difference < 1e-9, difference
        return difference <= scale * self.tolerance, difference

    # -- the standard income statement identities ------------------------
    def validate_income_statement(
        self,
        values: dict[str, float],
        *,
        period_label: str = "",
        scope: str = "",
        require_evidence: bool = True,
    ) -> ValidationReport:
        """Check the identities that must hold in a profit and loss account.

        Each identity is only tested when every metric it needs is present, so
        a partial extraction yields a partial report rather than false alarms.

        With ``require_evidence`` a statement that tested no identity at all is
        not treated as validated. This is the failure the live filing exposed:
        the standalone profit and loss page is too damaged to read its total
        income or total expenses, so no identity could run, and a naive report
        recorded a pass. It published revenue of 166,013 crore against a real
        figure near 41,000, and a prior period's profit after tax, every value
        individually well formed and collectively unverified. A pass that
        checked nothing is not a pass.
        """
        report = ValidationReport(tolerance=self.tolerance)
        where = f" ({period_label})" if period_label else ""
        if scope:
            where += f" {scope}"

        def add(name: str, lhs: float, rhs: float, metrics: tuple[str, ...]) -> None:
            passed, difference = self._within(lhs, rhs)
            report.checks.append(
                IdentityCheck(name=name, lhs=lhs, rhs=rhs, passed=passed,
                              difference=difference, metrics=metrics,
                              detail=f"{lhs:,.2f} vs {rhs:,.2f}{where}")
            )
            if not passed:
                report.passed = False
                report.quarantined.update(metrics)

        v = values

        # Revenue from operations is gross of GST, so the identity is that
        # total income is revenue plus other income, not revenue plus tax.
        if {"revenue", "other_income", "total_income"} <= v.keys():
            add("total_income = revenue + other_income",
                v["total_income"], v["revenue"] + v["other_income"],
                ("total_income", "revenue", "other_income"))

        # Total expenses must at least cover its largest single component. This
        # is the only expense-side check that holds on a partial extraction.
        #
        # A "total expenses equals the sum of its components" identity was tried
        # and removed: it assumes the mapper read every printed expense line,
        # and a filing that also prints excise duty or a change in inventories
        # makes the sum legitimately fall short. Measured on the Reliance
        # consolidated P&L the sum came to 268,132 against a stated 275,873,
        # and the 7,741 gap was exactly the two lines the mapper does not track.
        # A check that fails on correct data is worse than no check.
        components = [
            abs(v[m]) for m in (
                "cost_of_materials", "purchases_stock_in_trade",
                "employee_benefits", "other_expenses", "finance_costs",
                "depreciation_amortisation",
            ) if m in v
        ]
        if components and "total_expenses" in v:
            largest = max(components)
            if abs(v["total_expenses"]) + 1e-9 < largest:
                report.checks.append(
                    IdentityCheck(
                        name="total_expenses >= its largest component",
                        lhs=abs(v["total_expenses"]), rhs=largest, passed=False,
                        difference=largest - abs(v["total_expenses"]),
                        metrics=("total_expenses",),
                        detail=(f"total {abs(v['total_expenses']):,.2f} is below "
                                f"a component of {largest:,.2f}{where}"),
                    )
                )
                report.passed = False
                report.quarantined.add("total_expenses")

        # Profit before tax is total income less total expenses. Share of an
        # associate's profit is added when the statement prints it, because it
        # sits inside the printed profit before tax without being income or an
        # expense. It is only folded in when present, so a company without
        # associates tests exactly as before.
        #
        # When the filing also prints provisions, this base identity is skipped:
        # the provisions-aware check below is authoritative, and running both
        # would quarantine the metrics on the base failure before the provisions
        # variant has a chance to pass.
        if {"total_income", "total_expenses", "pbt"} <= v.keys() and "provisions" not in v:
            share = v.get("share_of_associates", 0.0)
            add("pbt = total_income - total_expenses + share of associates",
                v["pbt"], v["total_income"] - v["total_expenses"] + share,
                ("pbt", "total_income", "total_expenses",
                 "share_of_associates" if "share_of_associates" in v else "pbt"))

        # A bank prints total expenditure *excluding* provisions and deducts
        # provisions to reach profit before tax, so the identity above
        # over-states profit by exactly the provision. A company that prints
        # impairment inside total expenses must not have it deducted again.
        #
        # Which of the two a filing uses is stated by the filing, so both are
        # tested and whichever holds is the one recorded. They differ by twice
        # the provision, so no reading but the printed one satisfies either:
        # the check corroborates without choosing on the filing's behalf.
        if {"total_income", "total_expenses", "pbt", "provisions"} <= v.keys():
            share = v.get("share_of_associates", 0.0)
            base = v["total_income"] - v["total_expenses"] + share
            for name, rhs in (
                ("pbt = total_income - total_expenses + share - provisions",
                 base - v["provisions"]),
                ("pbt = total_income - total_expenses + share "
                 "(provisions printed within total expenses)", base),
            ):
                passed, difference = self._within(v["pbt"], rhs)
                if passed:
                    report.checks.append(
                        IdentityCheck(
                            name=name, lhs=v["pbt"], rhs=rhs, passed=True,
                            difference=difference,
                            metrics=("pbt", "total_income", "total_expenses",
                                     "provisions"),
                            detail=f"{v['pbt']:,.2f} vs {rhs:,.2f}{where}",
                        )
                    )
                    break
            else:
                add("pbt = total_income - total_expenses, provisions "
                    "inside or outside total expenses",
                    v["pbt"], base - v["provisions"],
                    ("pbt", "total_income", "total_expenses", "provisions"))

        # Profit after tax is profit before tax less tax.
        if {"pbt", "total_tax", "net_profit"} <= v.keys():
            add("net_profit = pbt - total_tax",
                v["net_profit"], v["pbt"] - v["total_tax"],
                ("net_profit", "pbt", "total_tax"))

        # Tax is the sum of its printed components when both are present.
        if {"current_tax", "deferred_tax", "total_tax"} <= v.keys():
            add("total_tax = current_tax + deferred_tax",
                v["total_tax"], v["current_tax"] + v["deferred_tax"],
                ("total_tax", "current_tax", "deferred_tax"))

        # Total comprehensive income is profit after tax plus other
        # comprehensive income.
        if {"net_profit", "oci", "comprehensive_income"} <= v.keys():
            add("comprehensive_income = net_profit + oci",
                v["comprehensive_income"], v["net_profit"] + v["oci"],
                ("comprehensive_income", "net_profit", "oci"))

        self._plausibility(v, report, where)
        self._require_evidence(report, values, where, require_evidence)
        return report

    # -- evidence, not just absence of error ------------------------------
    def _require_evidence(
        self,
        report: ValidationReport,
        values: dict[str, float],
        where: str,
        required: bool,
    ) -> None:
        """Refuse to certify a statement that was too damaged to test.

        Passing every available identity is necessary but not sufficient. A page
        whose totals are unreadable tests nothing, and reporting that as a pass
        is how a figure that is off by a factor of four reaches production with
        an audit trail attached.
        """
        if not required or not values:
            return
        if any(c.passed for c in report.checks):
            return
        report.passed = False
        report.quarantined.update(values)
        report.checks.append(
            IdentityCheck(
                name="the statement is legible enough to verify",
                lhs=float(len(values)), rhs=float(MIN_CHECKS_FOR_EVIDENCE),
                passed=False, difference=float(len(report.checks)),
                metrics=tuple(sorted(values)),
                detail=(f"{len(values)} value(s) extracted but no identity could "
                        f"be tested; the totals that anchor the statement were "
                        f"not readable{where}"),
            )
        )
        report.notes.append(
            "nothing on this page could be corroborated: the figures that tie a "
            "statement together are missing, so every value on it is withheld"
        )

    # -- the standard balance sheet identities ----------------------------
    def validate_cash_flow(
        self,
        values: dict[str, float],
        *,
        period_label: str = "",
        scope: str = "",
        require_evidence: bool = True,
    ) -> ValidationReport:
        """Check that the cash movements add up to the movement in cash.

        A cash flow statement used to be accepted merely for parsing, because
        no identity had been written for it. That is the failure this method
        exists to remove: a page read from the wrong column produces a full set
        of plausible cash flow lines that reconcile to nothing, and publishing
        them unchecked is indistinguishable from publishing the truth.

        Indian filings state the reconciliation directly, so it can be checked
        the same way as a profit and loss account. The three activity subtotals
        plus the net movement must account for the change between the opening
        and closing cash balances, allowing for the exchange-difference line
        that Indian statements print separately. When the opening and closing
        balances are not both readable the statement has no total to reconcile
        against, and ``_require_evidence`` withholds it whole.
        """
        report = ValidationReport(tolerance=self.tolerance)
        where = f" ({period_label})" if period_label else ""
        if scope:
            where += f" {scope}"
        v = values

        def add(name: str, lhs: float, rhs: float, metrics: tuple[str, ...]) -> None:
            passed, difference = self._within(lhs, rhs)
            report.checks.append(
                IdentityCheck(name=name, lhs=lhs, rhs=rhs, passed=passed,
                              difference=difference, metrics=metrics,
                              detail=f"{lhs:,.2f} vs {rhs:,.2f}{where}")
            )
            if not passed:
                report.passed = False
                report.quarantined.update(metrics)

        activities = {"operating_cash_flow", "investing_cash_flow", "financing_cash_flow"}
        if activities <= v.keys():
            movement = sum(v[m] for m in activities)
            if "net_change_in_cash" in v:
                # The printed net movement also carries the effect of exchange
                # rate changes, so it is reconciled against the activities plus
                # that line rather than against the activities alone.
                fx = v.get("exchange_rate_effect")
                metrics = tuple(sorted(activities)) + ("net_change_in_cash",)
                if fx is not None:
                    metrics += ("exchange_rate_effect",)
                add(
                    "net_change_in_cash = operating + investing + financing (+ FX)",
                    v["net_change_in_cash"],
                    movement + (fx or 0.0),
                    metrics,
                )
            if {"opening_cash", "closing_cash"} <= v.keys():
                add(
                    "closing_cash = opening_cash + net movement",
                    v["closing_cash"],
                    v["opening_cash"] + v.get("net_change_in_cash", movement),
                    ("opening_cash", "closing_cash", "net_change_in_cash"),
                )

        self._require_evidence(report, values, where, require_evidence)
        return report

    def validate_balance_sheet(
        self,
        values: dict[str, float],
        *,
        as_at: str = "",
        scope: str = "",
    ) -> ValidationReport:
        """Check that assets equal liabilities plus equity."""
        report = ValidationReport(tolerance=self.tolerance)
        where = f" (as at {as_at})" if as_at else ""
        if scope:
            where += f" {scope}"
        v = values

        def add(name: str, lhs: float, rhs: float, metrics: tuple[str, ...]) -> None:
            passed, difference = self._within(lhs, rhs)
            report.checks.append(
                IdentityCheck(name=name, lhs=lhs, rhs=rhs, passed=passed,
                              difference=difference, metrics=metrics,
                              detail=f"{lhs:,.2f} vs {rhs:,.2f}{where}")
            )
            if not passed:
                report.passed = False
                report.quarantined.update(metrics)

        if {"total_assets", "total_liabilities", "total_equity"} <= v.keys():
            add("total_assets = total_liabilities + total_equity",
                v["total_assets"], v["total_liabilities"] + v["total_equity"],
                ("total_assets", "total_liabilities", "total_equity"))

        # Total assets cannot be less than the current assets that make them up.
        # This was wired to the equality helper, which made it unsatisfiable on
        # any real balance sheet: assets always equal a sum of parts, so the
        # only way to pass would have been current assets equal to all assets.
        if {"total_assets", "total_current_assets"} <= v.keys():
            lhs, rhs = abs(v["total_assets"]), abs(v["total_current_assets"])
            if lhs + 1e-9 < rhs:
                report.checks.append(
                    IdentityCheck(
                        name="total_assets >= total_current_assets",
                        lhs=lhs, rhs=rhs, passed=False, difference=rhs - lhs,
                        metrics=("total_assets", "total_current_assets"),
                        detail=(f"assets {lhs:,.2f} are below current assets "
                                f"{rhs:,.2f}{where}"),
                    )
                )
                report.passed = False
                report.quarantined.update({"total_assets", "total_current_assets"})

        if {"total_assets", "total_equity"} <= v.keys():
            # Equity cannot exceed total assets in a going concern.
            if abs(v["total_equity"]) > abs(v["total_assets"]):
                report.checks.append(
                    IdentityCheck(
                        name="total_equity <= total_assets",
                        lhs=abs(v["total_equity"]), rhs=abs(v["total_assets"]),
                        passed=False,
                        difference=abs(v["total_equity"]) - abs(v["total_assets"]),
                        metrics=("total_equity", "total_assets"),
                        detail=f"equity {abs(v['total_equity']):,.2f} exceeds "
                               f"assets {abs(v['total_assets']):,.2f}{where}",
                    )
                )
                report.passed = False
                report.quarantined.update({"total_equity", "total_assets"})

        return report

    # -- sign and magnitude sanity ---------------------------------------
    def _plausibility(
        self,
        values: dict[str, float],
        report: ValidationReport,
        where: str,
    ) -> None:
        """Reject values that are impossible regardless of arithmetic.

        A negative revenue or a negative total income is not a rounding
        artefact, it is a misread digit or column. These are checked before the
        identities so the failure is reported against the value itself.

        Profit before tax, profit after tax and earnings per share are
        deliberately absent. An Indian listed company that reports a loss
        prints a negative number on those lines, and that number is a result
        rather than an error. Treating it as damage would withhold precisely
        the filings a reader most wants to see, and would do it silently.
        """
        nonnegative = (
            "revenue", "other_income", "total_income", "total_expenses",
            "total_assets", "total_equity",
        )
        for metric in nonnegative:
            if metric in values and values[metric] < 0:
                report.checks.append(
                    IdentityCheck(
                        name=f"{metric} is not negative",
                        lhs=values[metric], rhs=0.0, passed=False,
                        difference=values[metric], metrics=(metric,),
                        detail=f"{values[metric]:,.2f}{where}",
                    )
                )
                report.passed = False
                report.quarantined.add(metric)

        # Tax is a charge, so profit after tax cannot exceed profit before
        # tax. This holds for a loss as well as a profit, and unlike the full
        # net profit identity it does not need the tax line to be present.
        if {"pbt", "net_profit"} <= values.keys():
            if values["net_profit"] > values["pbt"] + 1e-9:
                report.checks.append(
                    IdentityCheck(
                        name="net_profit <= pbt",
                        lhs=values["net_profit"], rhs=values["pbt"],
                        passed=False,
                        difference=values["net_profit"] - values["pbt"],
                        metrics=("net_profit", "pbt"),
                        detail=(f"profit after tax {values['net_profit']:,.2f} "
                                f"exceeds profit before tax "
                                f"{values['pbt']:,.2f}{where}"),
                    )
                )
                report.passed = False
                report.quarantined.update({"net_profit", "pbt"})

        # Per-share earnings are bounded by what Indian listed companies
        # actually report. The highest EPS in the Nifty universe is in the low
        # hundreds, so a figure far past that is a decimal-point or column
        # error.
        #
        # The earlier bound of 10,000 was too loose to be useful. Tightening it
        # to 1,000 catches thousandfold and larger shifts. It cannot catch a
        # hundredfold shift on a small EPS, because 5.48 printed as 548 is
        # still inside the range a real company could report, and no
        # share-count-free test separates the two. Closing that gap needs the
        # weighted average share count, which the mapper does not yet read.
        for metric in ("eps_basic", "eps_diluted"):
            if metric in values and abs(values[metric]) > MAX_PLAUSIBLE_EPS:
                report.checks.append(
                    IdentityCheck(
                        name=f"{metric} is within a plausible range",
                        lhs=abs(values[metric]), rhs=MAX_PLAUSIBLE_EPS, passed=False,
                        difference=abs(values[metric]) - MAX_PLAUSIBLE_EPS,
                        metrics=(metric,),
                        detail=f"{values[metric]:,.2f}{where}",
                    )
                )
                report.passed = False
                report.quarantined.add(metric)

    # -- recovered values -------------------------------------------------
    def check_recovered(
        self,
        values: dict[str, float],
        recovered_metrics: set[str],
        *,
        statement_report: Optional[ValidationReport] = None,
    ) -> ValidationReport:
        """Decide whether reconstructed figures may be published.

        A figure rebuilt from a damaged glyph is a hypothesis, so it is not
        published on the strength of the repair alone. It becomes publishable
        when the statement's own arithmetic corroborates it: if an identity
        that directly involves the metric holds, then the filing says the
        repaired number is consistent with the rest of itself, which is the
        only independent evidence available.

        This is deliberately not "the report passed overall". A statement with
        nine sound identities and one unrecognised damaged line still passes,
        and quarantining every recovered figure on the back of an unrelated
        failure would discard good data. The test is per-metric: did an
        identity naming this metric hold?

        Without a statement report there is no corroboration, so everything
        stays quarantined.
        """
        report = ValidationReport()
        if not recovered_metrics:
            return report

        corroborated: set[str] = set()
        if statement_report is not None:
            for check in statement_report.checks:
                if check.passed:
                    corroborated.update(check.metrics)

        publishable = recovered_metrics & corroborated
        withheld = recovered_metrics - publishable

        report.quarantined.update(withheld)
        report.passed = True
        report.notes.append(
            f"{len(recovered_metrics)} value(s) were reconstructed from damaged "
            f"text; {len(publishable)} corroborated by the statement's own "
            f"arithmetic, {len(withheld)} withheld"
        )
        if withheld:
            logger.debug(
                "withholding %d recovered metric(s) with no corroborating identity",
                len(withheld),
            )
        for metric in publishable:
            report.notes.append(
                f"{metric} was reconstructed and is corroborated by a passed identity"
            )
        return report


def apply_report(
    values: dict[str, float],
    report: ValidationReport,
) -> dict[str, float]:
    """Drop every metric the report could not vouch for.

    Partial results are a valid outcome, so the surviving metrics are returned
    rather than the whole statement being discarded. The caller is expected to
    surface the quarantine, so a low-coverage result is visible rather than
    silently thin.
    """
    if not report.quarantined:
        return dict(values)
    return {k: v for k, v in values.items() if k not in report.quarantined}
