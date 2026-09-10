# DCC-MCP Poly Pizza Assets

Cross-DCC skill for searching and downloading low-poly models through Poly
Pizza's published API. It acquires a validated GLB and returns a portable
`AssetDescriptor`; it never modifies a DCC scene.

## Install

Runtime execution requires `dcc-mcp-core` 0.19.90 or newer and a free Poly
Pizza API key from <https://poly.pizza/settings/api>.

```bash
dcc-mcp-cli marketplace add dcc-mcp/dcc-asset-poly-pizza
dcc-mcp-cli marketplace install dcc-asset-poly-pizza
```

Set the credential in the process that runs the DCC-MCP gateway. The token is
read only from the environment and is never accepted as a tool argument or
returned in results.

```powershell
$env:POLY_PIZZA_API_KEY = "your-api-key"
```

```bash
export POLY_PIZZA_API_KEY="your-api-key"
```

## Agent workflow

```bash
dcc-mcp-cli search --query "Poly Pizza low-poly model" --dcc-type blender
dcc-mcp-cli describe <tool-slug>
dcc-mcp-cli call <tool-slug> --json '{"query":"wooden crate","limit":5}'
```

1. Call `search_poly_pizza_models` and choose an asset by ID and license.
2. Call `download_poly_pizza_model` with the ID and an output directory.
3. Pass the returned `asset_descriptor` to the target DCC's native import
   skill. The provider stays independent of Blender, Maya, Houdini, Unreal,
   Unity, and other adapters.

## License and provenance

The repository code is MIT licensed. Downloaded models keep their individual
Poly Pizza license. This skill accepts only recognized CC0 or CC-BY records,
and fails closed when license provenance is missing or ambiguous. CC-BY assets
must include a creator. Every successful download returns and writes:

- source model URL, creator, title, SPDX license, and attribution text;
- final HTTPS download URL, byte size, and SHA-256 digest;
- an atomic `.receipt.json` sidecar and a validated `AssetDescriptor`.

Users remain responsible for following the license attached to each model.
See [Poly Pizza's terms](https://poly.pizza/docs/tos).

## Safety boundaries

- Uses only the published API; no HTML scraping or browser fallback.
- Sends the API key only to `api.poly.pizza`, never to the asset CDN.
- Allows only HTTPS Poly Pizza download hosts and bounded GLB payloads.
- Rejects HTML challenges, missing glTF magic bytes, unsafe IDs, redirects to
  unrelated hosts, and existing files unless `overwrite=true`.

## Tools

- `search_poly_pizza_models`
- `get_poly_pizza_model`
- `download_poly_pizza_model`

