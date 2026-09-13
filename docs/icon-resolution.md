# Inventory icon resolution

The Vanilla icon builder uses `mcbe_editor/icon_resolution.py` to resolve visual
identity before rendering. Item IDs, atlas keys, texture paths, and preview
geometry are different concepts. In particular, `brick` is a key in both
Vanilla atlases, with different meanings.

## Resolution contract

1. Explicit `minecraft:icon` components in base `behavior_pack/items/*.json`
   select keys in the item atlas. Current `textures.default`, historical
   `texture`, and string components are supported. Experimental pack overlays
   are not mixed into the stable base pack. Conflicting component definitions
   are unresolved instead of depending on ZIP ordering.
2. Explicit `carried_textures` select inventory materials through the terrain
   atlas. Partial carried face definitions retain the other world faces.
3. Dedicated item sprites remain valid for placeable items such as doors and
   brewing stands. The small inventory spelling bridge preserves identity;
   it never strips `_stairs` or `_slab` to obtain an ingredient.
4. Supported block previews use `blocks.json` materials for their faces.
   The block registry gates rendering; `brick_block` is explicitly a cube.
5. Published metadata is not a complete inventory renderer. The existing
   reviewed model specifications, body-only previews, atlas crops, and legacy
   compatibility resolver remain separate, recorded strategies.

The item and terrain atlas dictionaries are never flattened into a single
namespace. A declared missing texture or unknown key does not fall through to
a similarly named ingredient. Unresolved arrays are explicitly labelled
`variant_selection_required`: their order represents states/variants, not a
preference for the first available file. Existing compatibility thumbnails for
these entries remain labelled `legacy_heuristic` pending a reviewed state rule.

When the caller supplies the block classification, fallback selection also
excludes raw block materials for known non-block items. The command-line updater
always supplies this classification from the item database.

`blocks.json` alone cannot describe complex inventory geometry. For example,
the carried sensor bindings describe tendrils, the portal-frame binding an eye,
and the skull material is soul sand. The sensor/frame previews use their world
body materials; the beacon previews its core. Player and piglin heads remain
unresolved without a reviewed model. Unsupported multi-material shapes keep a
labelled legacy thumbnail instead of an arbitrary side texture.

Sources:

- [Microsoft: blocks.json](https://learn.microsoft.com/en-us/minecraft/creator/reference/content/blockreference/examples/blocksjsonfilestructure)
- [Microsoft: minecraft:icon](https://learn.microsoft.com/en-us/minecraft/creator/reference/content/itemreference/examples/itemcomponents/minecraft_icon)
- [Mojang's reference packs](https://github.com/Mojang/bedrock-samples)

Custom block components can override `blocks.json`. This Vanilla builder is not
a general evaluator for arbitrary add-on geometry, permutations, or Molang.

## Diagnostics and comparison

Cache manifest schema 6 retains the existing `items` mapping and adds
`resolutions`. Each record identifies the binding basis, atlas, chosen texture,
available declared faces, actual preview faces where applicable, representation,
and unresolved condition. `block_preview` and `model_preview` are approximations
of the game renderer. A mapped icon count is coverage, not semantic correctness.

Before changing resolution rules, build a baseline cache. Build the new cache
from the **same archive and item database**, in another directory. Include the
archive and catalog SHA-256 values in both builds' `release_info` metadata for
an exact comparison. Neither cache needs to replace the active user cache.

```sh
python scripts/compare_icon_caches.py data/icon_comparison/before data/icon_comparison/after data/icon_comparison/report
```

The command rejects differing release metadata and missing or empty PNGs listed
as mapped in either manifest. It compares both selected
sources and PNG bytes, including changes where the source path is unchanged.
It writes a JSON report and a searchable, self-contained HTML comparison. Review
changed previews, newly missing icons, unresolved bindings, and the focused
resolver/updater/renderer tests together. Byte changes do not necessarily imply
visually different pixels.

Generated PNGs and the HTML contain locally extracted Minecraft assets. Keep
all comparison outputs under ignored `data/`; do not commit or distribute them.
Public regression fixtures use synthetic textures and minimal synthetic pack
metadata, with no worlds, player NBT, or copied Minecraft images.

## Additional icon sources

The runtime source scanner accepts filename-based image overrides; it does not
run the Vanilla builder on arbitrary resource packs. Final icons should use
`textures/items/<item_id>.png`. Raw `textures/blocks` files are material
fallbacks. They cannot impersonate known non-block items. Within one source,
dedicated item sprites win filename collisions independently of directory or
archive ordering. The user's ordering between separate sources is preserved.
The scanner index version is bumped so old collision results are not reused.

Status refreshes and source changes retain the world sources from the latest
explicit scan. An explicit scan of another world, or a scan without a world,
replaces that context. When multiple workers share an index, its publication
takes precedence over a worker's older local state. Source-change handlers
capture the world metadata before invalidating the cache, under the existing
lock covering the change and rescan. Only metadata is reused this way; the scan
checks the current source signature before reusing cached icon references.

`tests/test_icon_context_regressions.py` covers this continuity using temporary
packs and separate worker states, including source changes that delete the
shared cache. It also checks byte access to internal `textures/display` assets
from directories and archives. Those assets remain absent from public icon
metadata; their existing size and archive checks still apply.

After upgrading the application, rebuild Vanilla icons through the existing
icon-update action to replace old generated PNGs. Rescanning alone cannot repair
an already-generated incorrect PNG.
