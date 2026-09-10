from __future__ import annotations

from typing import Any, Dict, Optional

from dcc_mcp_core.skill import skill_entry, skill_error, skill_exception, skill_success

from _poly_pizza import PolyPizzaError, search_models


@skill_entry
def main(
    query: Optional[str] = None,
    category: Optional[int] = None,
    license: Optional[str] = None,
    animated: bool = False,
    limit: int = 20,
    page: int = 0,
    **_: Any
) -> Dict[str, Any]:
    try:
        result = search_models(query, category, license, animated, limit, page)
        return skill_success("Poly Pizza models found", **result)
    except PolyPizzaError as exc:
        return skill_error("Poly Pizza search failed", exc.code, detail=str(exc), error_code=exc.code)
    except Exception as exc:
        return skill_exception(exc, message="Poly Pizza search failed")


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main
    run_main(main)

