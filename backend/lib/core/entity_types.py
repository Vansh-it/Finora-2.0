"""Entity type contracts and metric applicability.

Entity type drives which metric schema, dashboard tabs, financial statement
structure, calculations, forensic models and red flags apply.
"""

from __future__ import annotations

from enum import Enum


class EntityType(str, Enum):
    """Supported India entity classifications.

    CORPORATE / BANK / NBFC have dashboards in this phase. The remaining
    values are reserved so future adapters can plug in without schema churn.
    """

    CORPORATE = "CORPORATE"
    BANK = "BANK"
    NBFC = "NBFC"
    LIFE_INSURANCE = "LIFE_INSURANCE"
    GENERAL_INSURANCE = "GENERAL_INSURANCE"
    REIT = "REIT"
    INVIT = "INVIT"


# Entity types with dashboards in this phase
DASHBOARD_ENTITY_TYPES: tuple[EntityType, ...] = (
    EntityType.CORPORATE,
    EntityType.BANK,
    EntityType.NBFC,
)

# Entity types whose core business is lending / deposits — no inventory,
# no trade payables, no cost-of-goods economics.
FINANCIAL_INSTITUTION_TYPES: tuple[EntityType, ...] = (
    EntityType.BANK,
    EntityType.NBFC,
    EntityType.REIT,
    EntityType.INVIT,
)


def is_financial_institution(entity_type: EntityType) -> bool:
    """True when inventory/COGS-style metrics are economically meaningless."""
    return entity_type in FINANCIAL_INSTITUTION_TYPES


class EntityApplicability(str, Enum):
    """Applicability of a metric to an entity type.

    Feeds the completeness engine: NOT_APPLICABLE metrics are excluded from
    expected coverage; PENDING_SOURCE metrics are expected but cannot be
    populated until real India ingestion exists.
    """

    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CONDITIONAL = "CONDITIONAL"  # applicable only when specific inputs exist
