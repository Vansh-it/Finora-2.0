"""India architecture: models, classifier, schemas, dashboard builders.

This package holds the India-facing product contracts. Live NSE/BSE/XBRL
retrieval is NOT part of this phase — the India Adapter (next phase) will
populate the canonical data layer from official sources. Until then,
fixtures exercise the full pipeline.
"""

from lib.india.classifier import classify_entity, IndiaEntityType
from lib.india.models import IndiaMacroStrip, fixture_macro_strip
from lib.india.resolver import (
    resolve_india_company,
    IndiaCompany,
    IndiaResolutionResult,
    AmbiguousIndiaCompanyError,
    discover_india_documents,
)

__all__ = [
    "classify_entity",
    "IndiaEntityType",
    "IndiaMacroStrip",
    "fixture_macro_strip",
    "resolve_india_company",
    "IndiaCompany",
    "IndiaResolutionResult",
    "AmbiguousIndiaCompanyError",
    "discover_india_documents",
]
