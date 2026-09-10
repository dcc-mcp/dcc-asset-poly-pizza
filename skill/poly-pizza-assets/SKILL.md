---
name: poly-pizza-assets
description: Search and download Poly Pizza low-poly GLB models as license-safe AssetDescriptors for any DCC adapter.
license: MIT
compatibility: "dcc-mcp-core 0.19.90+, Python 3.7+"
metadata:
  dcc-mcp:
    version: v0.1.0
    dcc: python
    layer: domain
    tags:
      - asset
      - poly-pizza
      - low-poly
      - 3d-models
      - glb
      - download
    search-hint: "poly pizza low poly model asset glb cc0 cc-by search download"
    produces: [asset_descriptor]
    tools: tools.yaml
---

# Poly Pizza Assets

Use this DCC-neutral provider to discover and acquire low-poly GLB models from
Poly Pizza's published API. Set `POLY_PIZZA_API_KEY` in the gateway process.
Never request or place the token in tool arguments, prompts, logs, or results.

Call `search_poly_pizza_models`, inspect each result's license and creator, then
call `download_poly_pizza_model`. The download tool validates provenance and
GLB content, writes an integrity receipt, and returns an `asset_descriptor`.
Pass that descriptor to the chosen DCC adapter's import tool. This skill does
not import files or modify a scene.

Only CC0 and CC-BY records are accepted. Missing or unknown license metadata,
or a CC-BY record without its creator, must remain a hard failure.

