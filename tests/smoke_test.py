from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skill" / "poly-pizza-assets"
SCRIPTS = SKILL / "scripts"
MISSING_MODULE = object()


class FakeResponse:
    def __init__(self, payload: bytes, url: str, status: int = 200, headers: Optional[Dict[str, str]] = None) -> None:
        self.payload = payload
        self.offset = 0
        self.url = url
        self.status = status
        self.headers = headers or {}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def geturl(self) -> str:
        return self.url

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self.payload) - self.offset
        chunk = self.payload[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk


def load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def api_model(license_value: Any = "CC0", creator: Optional[str] = "Ada") -> Dict[str, Any]:
    value = {
        "ID": "crate-42",
        "Title": "Wooden Crate",
        "Licence": license_value,
        "Download": "https://static.poly.pizza/crate-42.glb",
        "Tags": ["crate", "wood"],
        "Thumbnail": "https://static.poly.pizza/crate-42.png",
    }
    if creator is not None:
        value["Creator"] = {"Username": creator}
    return value


def validate_skill() -> None:
    from dcc_mcp_core import validate_skill

    report = validate_skill(str(SKILL))
    assert not report.has_errors, report


def metadata_smoke() -> None:
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(skill_text.split("---", 2)[1])
    assert frontmatter["compatibility"] == "dcc-mcp-core 0.19.90+, Python 3.7+"
    tools = yaml.safe_load((SKILL / "tools.yaml").read_text(encoding="utf-8"))["tools"]
    assert {tool["name"] for tool in tools} == {
        "search_poly_pizza_models", "get_poly_pizza_model", "download_poly_pizza_model"
    }
    marketplace = json.loads((ROOT / "marketplace.json").read_text(encoding="utf-8"))
    assert marketplace["entries"][0]["min_core_version"] == "0.19.90"
    for script in SCRIPTS.glob("*.py"):
        ast.parse(script.read_text(encoding="utf-8"), filename=str(script), feature_version=(3, 7))


def license_fail_closed_smoke() -> None:
    helper = load("_poly_pizza")
    assert helper.normalize_model(api_model())["license_spdx"] == "CC0-1.0"
    assert helper.normalize_model(api_model("CC-BY"))["license_spdx"] == "CC-BY-4.0"
    for model in (api_model("proprietary"), api_model("CC-BY", creator=None)):
        try:
            helper.normalize_model(model)
        except helper.PolyPizzaError as exc:
            assert exc.code in ("license_unrecognized", "attribution_missing")
        else:
            raise AssertionError("unsafe provenance must fail closed")


def search_contract_smoke() -> None:
    helper = load("_poly_pizza")
    captured = {}  # type: Dict[str, Any]

    def open_search(request: Any, timeout: int = 0) -> FakeResponse:
        captured["request"] = request
        payload = json.dumps({"total": 1, "results": [api_model()]}).encode("utf-8")
        return FakeResponse(payload, request.full_url)

    with patch.dict(os.environ, {"POLY_PIZZA_API_KEY": "top-secret"}, clear=False):
        with patch("urllib.request.urlopen", side_effect=open_search):
            result = helper.search_models("wood crate", 3, "CC0", True, 7, 2)
    request = captured["request"]
    parsed = __import__("urllib.parse", fromlist=["urlsplit", "parse_qs"])
    params = parsed.parse_qs(parsed.urlsplit(request.full_url).query)
    assert params == {"Limit": ["7"], "Page": ["2"], "Category": ["3"], "License": ["1"], "Animated": ["1"]}
    assert request.headers.get("X-auth-token") == "top-secret"
    assert "top-secret" not in json.dumps(result)
    assert result["models"][0]["id"] == "crate-42"


def download_contract_smoke() -> None:
    helper = load("_poly_pizza")
    requests = []

    def open_download(request: Any, timeout: int = 0) -> FakeResponse:
        requests.append(request)
        if request.full_url.startswith(helper.API_BASE):
            return FakeResponse(json.dumps(api_model("CC-BY")).encode("utf-8"), request.full_url)
        return FakeResponse(b"glTF" + b"valid-model", request.full_url, headers={"Content-Length": "15"})

    with tempfile.TemporaryDirectory() as output_dir:
        with patch.dict(os.environ, {"POLY_PIZZA_API_KEY": "top-secret"}, clear=False):
            with patch("urllib.request.urlopen", side_effect=open_download):
                result = helper.download_model("crate-42", output_dir, False, 1024)
        asset_path = Path(result["file"])
        receipt_path = Path(result["receipt_file"])
        assert asset_path.read_bytes().startswith(b"glTF")
        assert receipt_path.exists()
        assert result["receipt"]["sha256"] == result["asset_descriptor"]["extra"]["sha256"]
        assert result["asset_descriptor"]["attribution"]["author"] == "Ada"
        assert result["asset_descriptor"]["variants"][0]["format"] == "glb"
        assert not list(Path(output_dir).glob("*.part"))
    assert requests[0].headers.get("X-auth-token") == "top-secret"
    assert all("top-secret" not in str(value) for value in requests[1].headers.values())


def rejection_smoke() -> None:
    helper = load("_poly_pizza")

    def open_invalid(request: Any, timeout: int = 0) -> FakeResponse:
        if request.full_url.startswith(helper.API_BASE):
            return FakeResponse(json.dumps(api_model()).encode("utf-8"), request.full_url)
        return FakeResponse(b"<html>challenge</html>", request.full_url)

    with tempfile.TemporaryDirectory() as output_dir:
        with patch.dict(os.environ, {"POLY_PIZZA_API_KEY": "key"}, clear=False):
            with patch("urllib.request.urlopen", side_effect=open_invalid):
                try:
                    helper.download_model("crate-42", output_dir, False, 1024)
                except helper.PolyPizzaError as exc:
                    assert exc.code == "invalid_glb"
                else:
                    raise AssertionError("HTML payload must be rejected")
        assert not list(Path(output_dir).iterdir())

    untrusted = api_model()
    untrusted["Download"] = "https://poly.pizza.evil.example/model.glb"
    try:
        helper.normalize_model(untrusted, require_download=True)
    except helper.PolyPizzaError as exc:
        assert exc.code == "unsafe_url"
    else:
        raise AssertionError("untrusted download host must be rejected")

    def open_oversized(request: Any, timeout: int = 0) -> FakeResponse:
        if request.full_url.startswith(helper.API_BASE):
            return FakeResponse(json.dumps(api_model()).encode("utf-8"), request.full_url)
        return FakeResponse(b"glTFpayload", request.full_url, headers={"Content-Length": "2048"})

    with tempfile.TemporaryDirectory() as output_dir:
        with patch.dict(os.environ, {"POLY_PIZZA_API_KEY": "key"}, clear=False):
            with patch("urllib.request.urlopen", side_effect=open_oversized):
                try:
                    helper.download_model("crate-42", output_dir, False, 1024)
                except helper.PolyPizzaError as exc:
                    assert exc.code == "download_too_large"
                else:
                    raise AssertionError("oversized payload must be rejected")
        assert not list(Path(output_dir).iterdir())


def runtime_smoke() -> None:
    from dcc_mcp_core._server import run_skill_script

    payload = json.dumps({"results": [api_model()], "total": 1}).encode("utf-8")
    path_identity = sys.path
    path_snapshot = list(sys.path)
    helper_before = sys.modules.get("_poly_pizza", MISSING_MODULE)
    with patch.dict(os.environ, {"POLY_PIZZA_API_KEY": "key"}, clear=False):
        with patch("urllib.request.urlopen", return_value=FakeResponse(payload, "https://api.poly.pizza/v1.1/search/crate?Limit=1&Page=0")):
            result = run_skill_script(str(SCRIPTS / "search_poly_pizza_models.py"), {"query": "crate", "limit": 1})
    assert result["success"], result
    assert result["context"]["models"][0]["id"] == "crate-42"
    assert sys.path is path_identity and sys.path == path_snapshot
    assert sys.modules.get("_poly_pizza", MISSING_MODULE) is helper_before


def live_smoke() -> None:
    if os.environ.get("RUN_LIVE_API_SMOKE") != "true" or not os.environ.get("POLY_PIZZA_API_KEY"):
        print("skip live Poly Pizza smoke")
        return
    helper = load("_poly_pizza")
    result = helper.search_models("crate", None, None, False, 1, 0)
    assert result["models"] or result["rejected"], result


def main() -> None:
    validate_skill()
    metadata_smoke()
    license_fail_closed_smoke()
    search_contract_smoke()
    download_contract_smoke()
    rejection_smoke()
    runtime_smoke()
    live_smoke()


if __name__ == "__main__":
    main()
