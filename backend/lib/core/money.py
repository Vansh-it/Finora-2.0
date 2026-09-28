"""INR money model and formatting utilities.

Indian data stays natively INR. Internally store full numeric INR values —
never "₹1,230 Cr" strings. Formatting happens only at the presentation edge.

Indian numbering: 1 lakh = 100,000; 1 crore = 10,000,000;
1 lakh crore = 1,000,000,000,000 (1e12).
"""

from __future__ import annotations

from typing import Optional

LAKH = 100_000.0
CRORE = 10_000_000.0
LAKH_CRORE = 1_000_000_000_000.0  # 1e12
RUPEE = 1.0

THRESHOLD_CRORE = 1_00_000.0  # below this, show plain ₹ with Indian digit grouping
THRESHOLD_LAKH_CRORE = 100_000.0 * CRORE  # ≥ ₹1,00,000 Cr → lakh crore


def _format_indian_integer(n: int) -> str:
    """Indian digit grouping: 12,43,00,000 (last 3, then pairs)."""
    s = str(abs(n))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def format_inr(
    value: Optional[float],
    *,
    decimals: Optional[int] = None,
    explicit_zero: bool = False,
) -> str:
    """Format a full numeric INR value for display.

    - ≥ ₹1 lakh crore → ₹X.XX lakh Cr
    - ≥ ₹1 lakh (1e5) → ₹X Cr / ₹X.X Cr (₹X Cr from 10 Cr upward)
    - below ₹1 lakh   → plain ₹ with Indian grouping
    - negative → -₹…, zero → "₹0" (only when the value is genuinely zero),
      None → "—" (never ₹0 for missing data).
    """
    if value is None:
        return "—"
    if isinstance(value, str):
        raise TypeError("format_inr expects a number, not a formatted string")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"format_inr expects a number, got {type(value).__name__}")
    v = float(value)
    if v != v or v in (float("inf"), float("-inf")):  # NaN / inf guard
        return "—"

    sign = "-" if v < 0 else ""
    a = abs(v)

    if a >= LAKH_CRORE:
        if decimals is None:
            text = f"{a / LAKH_CRORE:.2f}".rstrip("0").rstrip(".")
            if len(text.split(".")[0]) >= 2:
                text = f"{a / LAKH_CRORE:.1f}".rstrip("0").rstrip(".")
        else:
            text = f"{a / LAKH_CRORE:.{decimals}f}"
        return f"{sign}₹{text} lakh Cr"

    if a >= CRORE:
        if decimals is not None:
            text = f"{a / CRORE:.{decimals}f}"
        elif a >= 10 * CRORE:
            text = f"{a / CRORE:,.0f}"
        else:
            text = f"{a / CRORE:.1f}".rstrip("0").rstrip(".")
        return f"{sign}₹{text} Cr"

    if a >= LAKH:
        if decimals is not None:
            text = f"{a / LAKH:.{decimals}f}"
        else:
            text = f"{a / LAKH:.2f}".rstrip("0").rstrip(".")
        return f"{sign}₹{text} lakh"

    if a == 0 and not explicit_zero:
        return "₹0"
    return f"{sign}₹{_format_indian_integer(int(round(a)))}"


def format_eps(value: Optional[float]) -> str:
    """EPS always shows paise precision: ₹42.71, -₹3.20, — for missing."""
    if value is None:
        return "—"
    return f"₹{value:,.2f}" if value >= 0 else f"-₹{abs(value):,.2f}"


def format_percent(value: Optional[float], decimals: int = 1) -> str:
    """Format a percentage already expressed in percent units: 18.4%."""
    if value is None:
        return "—"
    return f"{value:.{decimals}f}%"


def format_ratio(value: Optional[float], decimals: int = 1, suffix: str = "×") -> str:
    """Format a multiple/ratio: 3.2×, 24.7×, 0.85×."""
    if value is None:
        return "—"
    return f"{value:.{decimals}f}{suffix}"


def format_years(value: Optional[float], decimals: int = 1) -> str:
    """Format a days-style value: 47.3 days."""
    if value is None:
        return "—"
    return f"{value:.{decimals}f} days"


def format_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    """YoY growth in percent; None when not computable (never 0 for missing)."""
    if current is None or previous is None:
        return None
    if previous == 0:
        return None
    if previous < 0:
        # Sign-changing bases make growth meaningless.
        return None
    return (current - previous) / abs(previous) * 100.0
