"""India backend smoke test — import the full research path and exercise resolver."""
from __future__ import annotations

import sys
import os

# Make backend/lib importable the same way app.py does.
_backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "backend"))
sys.path.insert(0, _backend_dir)

from lib.india.company_resolver import IndiaCompany, resolve_india_company  # noqa: E402
from lib.india.live_resolver import resolve as live_resolve, get_master  # noqa: E402
from lib.india.adapter import IndiaAdapter, IndiaResearchResult  # noqa: E402

COMPANY_FILES = {
    "RELIANCE": "RELIANCE_Q3FY24_Results.pdf",
    "HDFCBANK": "HDFC_BANK_Q4FY23_Results.pdf",
    "BAJFINANCE": "BAJFINANCE_Q3FY24_Results.pdf",
}

def test_resolver_reliance() -> bool:
    r = resolve_india_company("Reliance")
    assert r.company.nse_symbol == "RELIANCE"
    assert r.company.entity_type == "CORPORATE"
    print("resolver(reliance):", r.company.nse_symbol, r.company.entity_type)
    return True

def test_resolver_bajaj() -> bool:
    r = resolve_india_company("Bajaj Finance")
    assert r.company.nse_symbol == "BAJFINANCE"
    assert r.company.entity_type == "NBFC"
    print("resolver(bajaj):", r.company.nse_symbol, r.company.entity_type)
    return True

def test_resolver_hdfc() -> bool:
    r = resolve_india_company("HDFC Bank")
    assert r.company.nse_symbol == "HDFCBANK"
    assert r.company.entity_type == "BANK"
    print("resolver(hdfc):", r.company.nse_symbol, r.company.entity_type)
    return True

def test_resolver_unseen() -> bool:
    r = resolve_india_company("Asian Paints")
    assert r.company.nse_symbol == "ASIANPAINT"
    assert r.company.entity_type == "CORPORATE"
    print("resolver(asian):", r.company.nse_symbol, r.company.entity_type)
    return True

def test_resolver_ambiguity() -> None:
    try:
        resolve_india_company("RIL")
    except Exception as e:
        print("resolver(RIL) raised (expected ambiguity or resolution):", type(e).__name__)
    else:
        print("resolver(RIL) returned:", resolve_india_company("RIL").company.display_name)

def test_adapter_minimal() -> None:
    a = IndiaAdapter()
    result: IndiaResearchResult = a.research("Reliance Industries")
    print("adapter.research(reliance) status:", result.status, "usable:", result.usable)
    if result.data is not None:
        print("  entity_type:", result.data.identity.entity_type)
        print("  statements:", list(result.data.statements.keys()))
        print("  ownership rows:", len(result.data.ownership))
        if result.data.market_data:
            print("  market price:", result.data.market_data.price)
    if result.dashboard is not None:
        print("  dashboard keys:", sorted(result.dashboard.keys())[:8])

if __name__ == "__main__":
    ok = True
    for fn in (test_resolver_reliance, test_resolver_bajaj, test_resolver_hdfc,
               test_resolver_unseen):
        try:
            fn()
        except Exception as e:
            print("FAIL", fn.__name__, e)
            ok = False
    test_resolver_ambiguity()
    try:
        test_adapter_minimal()
    except Exception as e:
        print("FAIL test_adapter_minimal", e)
        ok = False
    print("ALL OK" if ok else "SOME FAILURES")
    sys.exit(0 if ok else 1)
