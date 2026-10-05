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

Cache manifest schema 6 contains the `items` mapping, `item_texture_data`,
`item_icon_definitions`, and `resolutions`. The atlas and item component mappings
let active resource packs redirect base sprites without copying the base images.
Each resolution record identifies the binding basis, atlas, chosen texture,
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

`mcbe_editor/resource_packs.py` reads `world_resource_packs.json` and
`world_behavior_packs.json` without writing to the world. Each registration
selects the manifest header UUID and exact version. Lists retain their stack
order, with the first entry taking priority. Pack discovery checks world-local,
server/shared, and installed resource/behavior pack directories. Installed packs
are discovery candidates; they do not activate themselves. A world-local match
has priority over a shared copy. Ambiguous matches at the same discovery level,
missing versions, invalid metadata and missing pack dependencies produce
diagnostics. An unreadable optional discovery directory does not discard matches
from completed directories. An incomplete directory is excluded as a whole,
because its unseen entries could contain an ambiguous duplicate. Empty or absent
lists select the global editor sources and Vanilla.
The Minecraft client's separate global resource-pack selection is not imported.

`mcbe_editor/icon_pack_resolution.py` resolves static inventory sprites through
behavior-pack item identifiers and `minecraft:icon` components, resource-pack
`textures/item_texture.json` keys, and the declared PNG/WebP paths. Item IDs and
filenames may differ. Item definitions in subdirectories are supported. Image
paths, atlas entries, and item definitions merge independently in priority order,
so one pack can redirect an atlas entry to another pack's image or replace only
that image. Direct replacements of known Vanilla sprite paths remain valid.
The resolver uses each item's highest-priority definition. If it omits the icon
component, a known Vanilla item can use its base binding and global image
overrides; lower item definitions do not supply the missing component. Invalid
or ambiguous atlas entries remain unresolved. The item and terrain atlases
remain separate.

Pack folders and `.mcpack`/`.zip` archives with a root manifest or one enclosing
archive folder are supported. JSON comments and UTF-8 BOMs are accepted; duplicate
keys, unsafe paths, linked files, oversized metadata, and ambiguous archive
entries are rejected. Metadata is bounded to 2 MiB per file, packs to 20,000 files,
and discovery/activation lists to 256 packs. Source identities and file metadata
are checked before publication. No archive is extracted into the world.

Explicit subpack selections overlay the pack's base files. An unspecified
device-dependent subpack is reported instead of selecting an arbitrary variant.
Variant arrays, dynamic/tinted rendering rules, custom block models, block
material previews and entity model atlases are outside the static resolver.
Existing standard icons or placeholder symbols remain available with diagnostics
for unresolved declared item icons and packs with block materials. This resolver
does not run Minecraft's renderer or evaluate Molang.

Global sources explicitly configured in the editor or `MCBE_ICON_ROOTS` remain
available below active world packs and above Vanilla. Valid pack manifests use
the same declarative resolver. Loose icon folders and archives without a manifest
retain filename-based overrides: final icons use `textures/items/<item_id>.png`.
Raw `textures/blocks` files are material fallbacks and cannot impersonate known
non-block items. Dedicated item sprites win filename collisions within a loose
source. The user's ordering between separate global sources is preserved.

## Shared indexes and read-only access

Status and source-change requests carry the selected `world_path`. The server
derives an opaque context identifier from the ordered source paths, activation,
pack types, archive prefixes and selected subpacks. World paths do not enter this
identifier. Worlds with the same sources share one index; Vanilla-only worlds
therefore reuse the same publication and image files. Separate physical copies of
a pack retain separate source identities, even if their bytes happen to match.
There is no content-deduplication service or additional image copy per world.

The identifier is included in icon and health-preview URLs. Browser request
generations and world checks discard outdated responses. Scanning another source
configuration preserves previously issued URLs across server workers. Activation
changes select the corresponding index. Pack file metadata invalidates changed
declarations and nested textures; a normal status load rebuilds only when needed.
Loose folders retain the explicit rescan action for nested changes. Vanilla uses
its manifest publication metadata without a recursive file walk on each load.
The signature also covers item catalog membership and block classification.
Each scan uses one catalog snapshot, so a concurrent catalog update cannot mix
resolution rules within an index. A later request validates against its catalog.

Persistent index files are retained until explicit source changes or Vanilla
updates invalidate them. Loading more worlds does not evict their publications.
The eight-entry bound applies only to the in-memory image lookup; eviction reloads
metadata from disk. Atomic cache-file replacement invalidates this lookup. The
cache retains paths and metadata, and image reads enforce path, archive and size
checks. Disk use grows with distinct source configurations, not world count.

Read-only requests select active sources and validate a prepared index without
building indexes, recovering caches or writing files. A missing or stale index
uses fallback symbols with a preparation hint. A worker-local index cannot bypass
that validation. World-specific selection errors are added to the response, so a
missing pack in one world cannot contaminate another world's shared Vanilla index.

Source changes and successful Vanilla updates invalidate all context indexes
before rebuilding the requesting world's index. The operation lock
covers each change and rescan. Requests without a world parameter retain the
latest-publication behavior for compatibility, including startup before world
selection. A legacy read-only cache is accepted only when its source configuration
matches. Prepared indexes must use the current scanner format.

Internal `textures/display` assets use the same path, size and archive checks
and remain separate from public item metadata.

The Vanilla icon-update action prepares the base atlas and component
mappings and rebuilds generated PNGs. If a prepared cache lacks these mappings,
additional packs receive an update hint. A rescan alone cannot reconstruct the
missing mappings or repair an already-generated incorrect PNG.

Synthetic regression fixtures cover [pack resolution](../tests/test_resource_pack_icons.py),
[shared indexes and read-only access](../tests/test_icon_context_regressions.py),
and [failure handling and catalog changes](../tests/test_icon_pack_regressions.py).

Pack format references:

- [Microsoft: manifest.json](https://learn.microsoft.com/en-us/minecraft/creator/reference/content/addonsreference/packmanifest)
- [Microsoft: custom items](https://learn.microsoft.com/en-us/minecraft/creator/documents/addcustomitems)
- [Mojang: world pack registrations](https://github.com/Mojang/bedrock-schemas/blob/main/schemas/world/world_packs.schema.json)
