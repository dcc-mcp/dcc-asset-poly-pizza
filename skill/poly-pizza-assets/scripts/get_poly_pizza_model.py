from __future__ import annotations

from typing import Any, Dict

from dcc_mcp_core.skill import skill_entry, skill_error, skill_exception, skill_success

from _poly_pizza import PolyPizzaError, get_model


@skill_entry
def main(model_id: str, **_: Any) -> Dict[str, Any]:
    try:
        return skill_success("Poly Pizza model metadata validated", model=get_model(model_id))
    except PolyPizzaError as exc:
        return skill_error("Poly Pizza model lookup failed", exc.code, detail=str(exc), error_code=exc.code)
    except Exception as exc:
        return skill_exception(exc, message="Poly Pizza model lookup failed")


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main
    run_main(main)

