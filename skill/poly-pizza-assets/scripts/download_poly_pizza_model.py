from __future__ import annotations

from typing import Any, Dict

from dcc_mcp_core.skill import skill_entry, skill_error, skill_exception, skill_success

from _poly_pizza import DEFAULT_MAX_BYTES, PolyPizzaError, download_model


@skill_entry
def main(
    model_id: str,
    output_dir: str,
    overwrite: bool = False,
    max_bytes: int = DEFAULT_MAX_BYTES,
    **_: Any
) -> Dict[str, Any]:
    try:
        result = download_model(model_id, output_dir, overwrite, max_bytes)
        return skill_success("Poly Pizza GLB downloaded and verified", **result)
    except PolyPizzaError as exc:
        return skill_error("Poly Pizza model download failed", exc.code, detail=str(exc), error_code=exc.code)
    except Exception as exc:
        return skill_exception(exc, message="Poly Pizza model download failed")


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main
    run_main(main)

