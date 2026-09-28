"""India entity classifier.

Classifies resolved India entities into CORPORATE / BANK / NBFC (future:
LIFE_INSURANCE, GENERAL_INSURANCE, REIT, INVIT) using explicit identifiers —
RBI licence records, exchange metadata and name signals. Classification
controls the metric schema, dashboard tabs and forensic models.

This phase ships deterministic, fixture-friendly classification. The India
Adapter phase will connect real registry lookups (RBI list of licensed banks
and NBFCs, exchange company metadata) through the same interface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from lib.core.entity_types import EntityType

# Name signals — deterministic, conservative. A match alone is a hint, not proof;
# explicit registry data (rbi_license) always wins.
_BANK_SIGNALS = re.compile(r"\b(bank|banking)\b", re.IGNORECASE)
_NBFC_SIGNALS = re.compile(
    r"\b(finance|financier|finvest|fincorp|capital|credit|loans?|housing finance|"
    r"investments?|mutual benefit)\b",
    re.IGNORECASE,
)
_REIT_SIGNALS = re.compile(r"\breit\b", re.IGNORECASE)
_INVIT_SIGNALS = re.compile(r"\binvit\b", re.IGNORECASE)
_INSURANCE_LIFE_SIGNALS = re.compile(r"\b(life insurance)\b", re.IGNORECASE)
_INSURANCE_GENERAL_SIGNALS = re.compile(
    r"\b(general insurance|insurance)\b", re.IGNORECASE)


@dataclass
class ClassificationResult:
    """Outcome of entity classification with evidence."""

    entity_type: EntityType
    confidence: float  # 0..1
    signals: list[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type.value,
            "confidence": self.confidence,
            "signals": list(self.signals),
            "reason": self.reason,
        }


def classify_entity(
    name: str = "",
    *,
    rbi_license: Optional[str] = None,  # "BANK" | "NBFC" from registry lookup
    exchange_metadata: Optional[dict] = None,  # {"entity_type": "BANK", ...}
    sector: str = "",
    industry: str = "",
) -> ClassificationResult:
    """Classify an India entity.

    Priority:
      1. explicit exchange metadata entity_type
      2. explicit RBI licence type (BANK / NBFC)
      3. sector/industry signals
      4. name signals (lowest confidence)
    """
    signals: list[str] = []

    # 1. Exchange metadata is authoritative when present.
    if exchange_metadata and exchange_metadata.get("entity_type"):
        raw = str(exchange_metadata["entity_type"]).strip().upper()
        try:
            et = EntityType(raw)
            return ClassificationResult(
                entity_type=et, confidence=1.0,
                signals=[f"exchange_metadata:{raw}"],
                reason="Entity type declared in exchange metadata",
            )
        except ValueError:
            pass

    # 2. RBI licence registry.
    if rbi_license:
        lic = str(rbi_license).strip().upper()
        if lic == "BANK":
            return ClassificationResult(
                entity_type=EntityType.BANK, confidence=0.98,
                signals=["rbi_license:BANK"],
                reason="RBI banking licence on record",
            )
        if lic in ("NBFC", "NBFC-D", "NBFC-ND", "NBFC-ND-SI", "NBFC-ICC", "HFC"):
            return ClassificationResult(
                entity_type=EntityType.NBFC, confidence=0.95,
                signals=[f"rbi_license:{lic}"],
                reason=f"RBI NBFC registration ({lic})",
            )

    # 3. Sector / industry signals.
    text_meta = f"{sector} {industry}".strip().lower()
    if "insurance" in text_meta:
        if "life" in text_meta:
            return ClassificationResult(
                entity_type=EntityType.LIFE_INSURANCE, confidence=0.9,
                signals=["sector:life insurance"],
                reason="Insurance (life) sector classification",
            )
        return ClassificationResult(
            entity_type=EntityType.GENERAL_INSURANCE, confidence=0.9,
            signals=["sector:insurance"],
            reason="Insurance sector classification",
        )
    if "reit" in text_meta:
        return ClassificationResult(
            entity_type=EntityType.REIT, confidence=0.9,
            signals=["sector:reit"], reason="REIT sector classification")
    if "invit" in text_meta:
        return ClassificationResult(
            entity_type=EntityType.INVIT, confidence=0.9,
            signals=["sector:invit"], reason="InvIT sector classification")
    if "bank" in text_meta:
        return ClassificationResult(
            entity_type=EntityType.BANK, confidence=0.85,
            signals=["sector:banking"],
            reason="Banking sector classification")
    if any(k in text_meta for k in ("nbfc", "finance", "housing finance", " lending")):
        return ClassificationResult(
            entity_type=EntityType.NBFC, confidence=0.85,
            signals=["sector:nbfc/finance"],
            reason="Finance sector classification")

    # 4. Name signals.
    full_name = name or ""
    if _BANK_SIGNALS.search(full_name):
        signals.append("name:bank")
        return ClassificationResult(
            entity_type=EntityType.BANK, confidence=0.7,
            signals=signals, reason="Name contains bank signal")
    if _REIT_SIGNALS.search(full_name):
        return ClassificationResult(
            entity_type=EntityType.REIT, confidence=0.7,
            signals=["name:reit"], reason="Name contains REIT signal")
    if _INVIT_SIGNALS.search(full_name):
        return ClassificationResult(
            entity_type=EntityType.INVIT, confidence=0.7,
            signals=["name:invit"], reason="Name contains InvIT signal")
    if _INSURANCE_LIFE_SIGNALS.search(full_name):
        return ClassificationResult(
            entity_type=EntityType.LIFE_INSURANCE, confidence=0.7,
            signals=["name:life insurance"],
            reason="Name contains life-insurance signal")
    if _INSURANCE_GENERAL_SIGNALS.search(full_name):
        return ClassificationResult(
            entity_type=EntityType.GENERAL_INSURANCE, confidence=0.65,
            signals=["name:insurance"],
            reason="Name contains insurance signal")
    if _NBFC_SIGNALS.search(full_name):
        return ClassificationResult(
            entity_type=EntityType.NBFC, confidence=0.6,
            signals=["name:finance/credit"],
            reason="Name contains finance/credit signal")

    # Default: corporate.
    return ClassificationResult(
        entity_type=EntityType.CORPORATE, confidence=0.5,
        signals=["default"],
        reason="No bank/NBFC/insurance/REIT signals — defaulting to corporate",
    )


# Alias used by package exports
IndiaEntityType = EntityType
