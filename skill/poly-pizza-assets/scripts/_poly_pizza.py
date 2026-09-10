from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dcc_mcp_core.asset_import import AssetAttribution, AssetDescriptor, AssetFileVariant


API_BASE = "https://api.poly.pizza/v1.1"
API_HOST = "api.poly.pizza"
TOKEN_ENV = "POLY_PIZZA_API_KEY"
USER_AGENT = "dcc-asset-poly-pizza/0.1"
DEFAULT_MAX_BYTES = 256 * 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024
LICENSE_FILTERS = {"CC-BY": 0, "CC0": 1}


class PolyPizzaError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        RuntimeError.__init__(self, message)
        self.code = code


def _token() -> str:
    value = os.environ.get(TOKEN_ENV, "").strip()
    if not value:
        raise PolyPizzaError(
            "credential_missing",
            "POLY_PIZZA_API_KEY is not configured in the gateway process",
        )
    return value


def _host_is_poly_pizza(hostname: Optional[str]) -> bool:
    host = (hostname or "").lower().rstrip(".")
    return host == "poly.pizza" or host.endswith(".poly.pizza")


def _validate_https_url(url: str, api_only: bool = False) -> str:
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError as exc:
        raise PolyPizzaError("unsafe_url", "Poly Pizza returned an invalid URL") from exc
    if parsed.scheme.lower() != "https" or parsed.username or parsed.password:
        raise PolyPizzaError("unsafe_url", "Poly Pizza URLs must use credential-free HTTPS")
    if api_only:
        valid_host = (parsed.hostname or "").lower() == API_HOST
    else:
        valid_host = _host_is_poly_pizza(parsed.hostname)
    if not valid_host:
        raise PolyPizzaError("unsafe_url", "Poly Pizza returned an untrusted host")
    return url


def _status(response: Any) -> int:
    return int(getattr(response, "status", getattr(response, "code", 200)))


def _final_url(response: Any, fallback: str) -> str:
    getter = getattr(response, "geturl", None)
    return str(getter() if getter else fallback)


def _api_json(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    query = urllib.parse.urlencode(params or {})
    url = API_BASE + path + (("?" + query) if query else "")
    _validate_https_url(url, api_only=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "X-Auth-Token": _token(), "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            final_url = _final_url(response, url)
            _validate_https_url(final_url, api_only=True)
            status = _status(response)
            payload = response.read(MAX_JSON_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise PolyPizzaError("authentication_failed", "Poly Pizza rejected the configured API key")
        if exc.code == 404:
            raise PolyPizzaError("not_found", "The requested Poly Pizza model was not found")
        if exc.code == 429:
            raise PolyPizzaError("rate_limited", "Poly Pizza rate limit exceeded; retry later")
        raise PolyPizzaError("upstream_http_error", "Poly Pizza API returned HTTP %s" % exc.code)
    except urllib.error.URLError as exc:
        raise PolyPizzaError("upstream_unavailable", "Poly Pizza API request failed: %s" % exc.reason)
    if status != 200:
        raise PolyPizzaError("upstream_http_error", "Poly Pizza API returned HTTP %s" % status)
    if len(payload) > MAX_JSON_BYTES:
        raise PolyPizzaError("response_too_large", "Poly Pizza API response exceeded the safety limit")
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PolyPizzaError("invalid_response", "Poly Pizza API returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise PolyPizzaError("invalid_response", "Poly Pizza API returned an unexpected JSON shape")
    return data


def _field(model: Dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in model and model[name] is not None:
            return model[name]
    return None


def _creator(model: Dict[str, Any]) -> Optional[str]:
    value = _field(model, "Creator", "creator")
    if isinstance(value, dict):
        value = _field(value, "Username", "Name", "username", "name")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _license(model: Dict[str, Any]) -> Tuple[str, str, str]:
    value = _field(model, "Licence", "License", "licence", "license")
    if isinstance(value, dict):
        value = _field(value, "Name", "Title", "Slug", "name", "title", "slug", "ID", "id")
    normalized = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if normalized == "1" or normalized.startswith("CC0") or normalized in ("CCZERO", "PUBLICDOMAIN"):
        return "CC0-1.0", "CC0 1.0 Universal", "https://creativecommons.org/publicdomain/zero/1.0/"
    if normalized == "0" or normalized.startswith("CCBY") or normalized in (
        "CCATTRIBUTION", "ATTRIBUTION", "CREATIVECOMMONSATTRIBUTION"
    ):
        # Poly Pizza's current filter identifies this family as CC-BY. Preserve
        # a conservative SPDX value rather than silently declaring CC0.
        return "CC-BY-4.0", "Creative Commons Attribution 4.0 International", "https://creativecommons.org/licenses/by/4.0/"
    raise PolyPizzaError("license_unrecognized", "Model license is missing or is not recognized as CC0/CC-BY")


def _model_id(model: Dict[str, Any]) -> str:
    value = str(_field(model, "ID", "Id", "id") or "").strip()
    if not value or len(value) > 128:
        raise PolyPizzaError("invalid_metadata", "Model ID is missing or invalid")
    return value


def _source_url(model: Dict[str, Any], model_id: str) -> str:
    value = _field(model, "URL", "Url", "Permalink", "Source", "url", "permalink")
    if value:
        return _validate_https_url(str(value))
    return "https://poly.pizza/m/%s" % urllib.parse.quote(model_id, safe="")


def normalize_model(model: Dict[str, Any], require_download: bool = False) -> Dict[str, Any]:
    model_id = _model_id(model)
    spdx, license_name, license_url = _license(model)
    creator = _creator(model)
    if spdx.startswith("CC-BY") and not creator:
        raise PolyPizzaError("attribution_missing", "CC-BY model metadata does not include a creator")
    title = str(_field(model, "Title", "title") or model_id).strip() or model_id
    download_url = _field(model, "Download", "download")
    if require_download and not download_url:
        raise PolyPizzaError("download_missing", "Model metadata has no downloadable GLB URL")
    if download_url:
        download_url = _validate_https_url(str(download_url))
    source_url = _source_url(model, model_id)
    attribution = "%s by %s (%s) — %s" % (
        title,
        creator or "Poly Pizza contributor",
        spdx,
        source_url,
    )
    tags = _field(model, "Tags", "tags") or []
    if not isinstance(tags, list):
        tags = []
    return {
        "id": model_id,
        "title": title,
        "creator": creator,
        "license_spdx": spdx,
        "license_name": license_name,
        "license_url": license_url,
        "source_url": source_url,
        "attribution_text": attribution,
        "triangle_count": _field(model, "Tri Count", "TriCount", "triangle_count"),
        "animated": bool(_field(model, "Animated", "animated")),
        "category": _field(model, "Category", "category"),
        "tags": tags,
        "thumbnail_url": _field(model, "Thumbnail", "thumbnail"),
        "download_url": download_url,
    }


def search_models(
    query: Optional[str], category: Optional[int], license_name: Optional[str],
    animated: bool, limit: int, page: int,
) -> Dict[str, Any]:
    keyword = (query or "").strip()
    if category is not None and not 0 <= int(category) <= 11:
        raise PolyPizzaError("invalid_argument", "category must be an integer from 0 through 11")
    canonical_license = license_name.upper() if license_name else None
    if canonical_license and canonical_license not in LICENSE_FILTERS:
        raise PolyPizzaError("invalid_argument", "license must be CC0 or CC-BY")
    if not 1 <= int(limit) <= 32 or int(page) < 0:
        raise PolyPizzaError("invalid_argument", "limit must be 1-32 and page must be non-negative")
    params = {"Limit": int(limit), "Page": int(page)}
    if category is not None:
        params["Category"] = int(category)
    if canonical_license:
        params["License"] = LICENSE_FILTERS[canonical_license]
    if animated:
        params["Animated"] = 1
    if not keyword and len(params) == 2:
        raise PolyPizzaError("invalid_argument", "Provide a query or at least one catalog filter")
    path = "/search/%s" % urllib.parse.quote(keyword, safe="") if keyword else "/search"
    data = _api_json(path, params)
    records = data.get("results", [])
    if not isinstance(records, list):
        raise PolyPizzaError("invalid_response", "Poly Pizza search results are not a list")
    models = []  # type: List[Dict[str, Any]]
    rejected = []  # type: List[Dict[str, str]]
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            models.append(normalize_model(record))
        except PolyPizzaError as exc:
            rejected.append({"id": str(_field(record, "ID", "id") or ""), "reason": exc.code})
    return {
        "models": models,
        "total": data.get("total", len(records)),
        "page": int(page),
        "rejected": rejected,
        "filters": params,
    }


def get_model(model_id: str) -> Dict[str, Any]:
    clean_id = str(model_id or "").strip()
    if not clean_id or len(clean_id) > 128:
        raise PolyPizzaError("invalid_argument", "model_id must contain 1-128 characters")
    data = _api_json("/model/%s" % urllib.parse.quote(clean_id, safe=""))
    return normalize_model(data, require_download=True)


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("._-")
    return (stem[:96] or "model")


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _content_length(response: Any) -> Optional[int]:
    headers = getattr(response, "headers", {}) or {}
    value = headers.get("Content-Length") if hasattr(headers, "get") else None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def download_model(model_id: str, output_dir: str, overwrite: bool, max_bytes: int) -> Dict[str, Any]:
    if not 1024 <= int(max_bytes) <= 1024 * 1024 * 1024:
        raise PolyPizzaError("invalid_argument", "max_bytes must be between 1024 and 1073741824")
    model = get_model(model_id)
    target_dir = Path(output_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / (_safe_stem(model["id"]) + ".glb")
    receipt_path = target.with_suffix(target.suffix + ".receipt.json")
    if not overwrite and (target.exists() or receipt_path.exists()):
        raise PolyPizzaError("destination_exists", "Destination asset or receipt already exists; set overwrite=true to replace it")

    url = str(model["download_url"])
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "model/gltf-binary"})
    temp_asset = None  # type: Optional[Path]
    temp_receipt = None  # type: Optional[Path]
    try:
        try:
            response = urllib.request.urlopen(request, timeout=60)
        except urllib.error.HTTPError as exc:
            content_type = str((exc.headers or {}).get("Content-Type", "")).lower()
            challenged = bool((exc.headers or {}).get("cf-mitigated")) or "text/html" in content_type
            code = "upstream_access_blocked" if challenged or exc.code == 403 else "upstream_http_error"
            raise PolyPizzaError(code, "Poly Pizza CDN did not return the model (HTTP %s)" % exc.code)
        except urllib.error.URLError as exc:
            raise PolyPizzaError("upstream_unavailable", "Poly Pizza model download failed: %s" % exc.reason)
        with response:
            final_url = _validate_https_url(_final_url(response, url))
            if _status(response) != 200:
                raise PolyPizzaError("upstream_http_error", "Poly Pizza CDN returned HTTP %s" % _status(response))
            expected = _content_length(response)
            if expected is not None and expected > int(max_bytes):
                raise PolyPizzaError("download_too_large", "GLB exceeds max_bytes")
            handle = tempfile.NamedTemporaryFile(prefix=".poly-pizza-", suffix=".glb.part", dir=str(target_dir), delete=False)
            temp_asset = Path(handle.name)
            digest = hashlib.sha256()
            size = 0
            magic = b""
            try:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    if not magic:
                        magic = chunk[:4]
                    size += len(chunk)
                    if size > int(max_bytes):
                        raise PolyPizzaError("download_too_large", "GLB exceeds max_bytes")
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                handle.close()
        if magic != b"glTF":
            raise PolyPizzaError("invalid_glb", "Poly Pizza returned HTML or a non-GLB payload")
        sha256 = digest.hexdigest()
        attribution = AssetAttribution(
            source_url=model["source_url"],
            license_spdx=model["license_spdx"],
            license_text=model["license_name"] + " (" + model["license_url"] + ")",
            author=model["creator"],
            title=model["title"],
            attribution_text=model["attribution_text"],
        )
        descriptor = AssetDescriptor(
            asset_id="poly-pizza:%s" % model["id"],
            variants=[AssetFileVariant(local_path=str(target), format="glb", preferred=True, mime="model/gltf-binary")],
            attribution=attribution,
            unit_hint="meter",
            meters_per_unit=1.0,
            up_axis="y",
            tags=[str(tag) for tag in model.get("tags", [])],
            extra={
                "provider": "poly-pizza",
                "sha256": sha256,
                "size_bytes": size,
                "thumbnail_url": model.get("thumbnail_url"),
            },
        )
        descriptor.validate()
        receipt = {
            "schema_version": 1,
            "provider": "poly-pizza",
            "asset_id": descriptor.asset_id,
            "model_id": model["id"],
            "title": model["title"],
            "creator": model["creator"],
            "license_spdx": model["license_spdx"],
            "license_url": model["license_url"],
            "source_url": model["source_url"],
            "download_url": final_url,
            "attribution_text": model["attribution_text"],
            "sha256": sha256,
            "size_bytes": size,
            "local_path": str(target),
        }
        receipt_handle = tempfile.NamedTemporaryFile(prefix=".poly-pizza-", suffix=".json.part", dir=str(target_dir), delete=False, mode="w", encoding="utf-8")
        temp_receipt = Path(receipt_handle.name)
        try:
            json.dump(receipt, receipt_handle, indent=2, sort_keys=True, ensure_ascii=False)
            receipt_handle.write("\n")
            receipt_handle.flush()
            os.fsync(receipt_handle.fileno())
        finally:
            receipt_handle.close()
        os.replace(str(temp_asset), str(target))
        temp_asset = None
        os.replace(str(temp_receipt), str(receipt_path))
        temp_receipt = None
        return {
            "file": str(target),
            "receipt_file": str(receipt_path),
            "receipt": receipt,
            "asset_descriptor": descriptor.to_dict(),
        }
    finally:
        if temp_asset is not None:
            _unlink(temp_asset)
        if temp_receipt is not None:
            _unlink(temp_receipt)
