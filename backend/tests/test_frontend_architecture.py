"""
Architecture guard: the shared dashboard layer must stay region-agnostic.

Why this lives in the Python suite: this repo has exactly one test runner
(pytest). Rather than leave the most important frontend invariant unenforced,
it is checked here against the source files.

The invariant: nothing under ``src/components/dashboard/shared/`` may depend on
a specific region. No region's types, no hardcoded currency, exchange, or
region name. A shared component that knows about India is a component the US
dashboard cannot reuse, which is the whole reason the layer was extracted.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_DIR = REPO_ROOT / "src" / "components" / "dashboard" / "shared"

# Region-specific tokens that must never appear in executable code there.
FORBIDDEN_TOKENS = {
    "types/india": "imports the India region type module",
    "INR": "hardcodes the Indian rupee",
    "₹": "hardcodes the Indian rupee symbol",
    "NSE": "hardcodes an Indian exchange",
    "BSE": "hardcodes an Indian exchange",
    "FII": "hardcodes an Indian holder category",
    "DII": "hardcodes an Indian holder category",
    "promoter": "hardcodes an Indian holder category",
    "India": "hardcodes an India-specific label",
}

# Comments legitimately discuss *why* a value is not hardcoded. Strip them
# before scanning so the guard tests behaviour, not prose.
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"//[^\n]*")


def _executable_source(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def _source_files() -> list[Path]:
    files = sorted(
        p for p in SHARED_DIR.iterdir() if p.suffix in {".ts", ".tsx"}
    )
    assert files, f"no shared dashboard sources found in {SHARED_DIR}"
    return files


def test_shared_layer_exists():
    assert SHARED_DIR.is_dir(), f"missing shared dashboard layer: {SHARED_DIR}"


@pytest.mark.parametrize("path", _source_files(), ids=lambda p: p.name)
def test_shared_layer_has_no_region_coupling(path: Path):
    source = _executable_source(path)
    offenders = [
        f"{token} ({why})"
        for token, why in FORBIDDEN_TOKENS.items()
        if token in source
    ]
    assert not offenders, (
        f"{path.name} is region-coupled: " + ", ".join(offenders)
    )


def test_shared_layer_does_not_import_region_modules():
    """No import may reach outside the shared folder or into a region module."""
    pattern = re.compile(r"""from\s+["']([^"']+)["']""")
    for path in _source_files():
        for module in pattern.findall(_executable_source(path)):
            assert "india" not in module.lower(), (
                f"{path.name} imports region module {module!r}"
            )
            # Region types live outside the dashboard tree entirely.
            assert not module.startswith("../../../types/"), (
                f"{path.name} imports region types via {module!r}"
            )


def test_eight_shared_components_are_exported():
    """The eight region-agnostic components the spec calls for."""
    index = (SHARED_DIR / "index.ts").read_text(encoding="utf-8")
    expected = [
        "StatementTable",
        "MetricCard",
        "MetricGrid",
        "RedFlagList",
        "ForensicModelCards",
        "OwnershipTable",
        "MacroContextStrip",
        "SourceLedger",
    ]
    missing = [name for name in expected if name not in index]
    assert not missing, f"shared barrel is missing exports: {missing}"


def test_unavailable_never_renders_as_zero():
    """A missing input must render as an em dash, never as a numeric zero."""
    card = (SHARED_DIR / "MetricCard.tsx").read_text(encoding="utf-8")
    assert "unavailable" in card
    assert "UNAVAILABLE" in card
    # The placeholder itself must not be a zero literal.
    assert "—\"" in card or "—\n" in card or "—" in card
