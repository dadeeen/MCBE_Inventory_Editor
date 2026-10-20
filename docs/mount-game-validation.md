# Mount creation: Minecraft acceptance validation

Validation scope: editor **v0.5.21**, Windows Store Minecraft Bedrock
**26.45** and the application's native storage backend under CPython **3.14.4**.
See also the [dependency portability assessment](dependency-portability-assessment.md).

This result covers the native backend in v0.5.21. The Minecraft client checks
of the pure-Python writer, including a horse, are described in
[the writer design](leveldb-writer.md#minecraft-client-evidence).

## Scope and result

The sample covers horse, donkey, mule, skeleton horse and camel.
Minecraft created three reference animals per type; the normal editor service
created three additional adult animals per type using `synthetic_full`.
All 30 distinct actors survived two Minecraft load/save cycles. Every editor
animal retained its identity, complete attributes and appearance variants.

Only adult references establish constant adult fields; baby reference records
contribute to codec checks only.

## Procedure

1. Work on a disposable copy of a stopped creative world and verify that the
   original remains unchanged. Use Vanilla entities without behavior overrides.
2. Summon reference animals in Minecraft, save and close the world. Create the
   editor animals through `BedrockEditorService` with normal backups, guards and
   post-write validation.
3. Compare all database values before and after editor creation, then inspect
   the actors after each of two Minecraft load/save cycles.
4. During the second cycle, command-mount one editor animal of each type.
   Check the success message, mounted view and health HUD before dismounting.

The references used Minecraft's documented named
[`summon` command](https://learn.microsoft.com/en-us/minecraft/creator/reference/content/commandsreference/examples/commands/summon?view=minecraft-bedrock-stable).
Mounting used the documented
[`ride` command](https://learn.microsoft.com/en-us/minecraft/creator/commands/commands/ride?view=minecraft-bedrock-stable)
with a selector restricted to the selected animal.

## Data checks and observed differences

Horse samples use distinct health, movement, jump, color and marking values;
other types use editor defaults. Comparisons allow only Float32 rounding.

For all 15 editor animals, checks across the pre-load, first-save and
second-save snapshots confirmed:

- The actor key, `identifier`, `UniqueID` and embedded storage key agree and
  remain unchanged. All 30 reference/editor identities are distinct.
- The actor suffix appears exactly once in the correct position-derived
  chunk index and exactly once across all `digp` entries, using aligned
  eight-byte entries rather than substring matching.
- The complete typed `Attributes` payload, `Variant`, `MarkVariant` and
  `IsBaby` match the original editor record after both saves.
- Before the first game load, all unrelated database values were unchanged
  by the editor writes. Original-world file hashes remained unchanged through
  the final validation.

During the first game save, changes were limited to `Pos`, `Rotation` and
normalization of the empty `Tags` list from element type Byte to End.
Camels additionally changed `InventoryVersion` from `1.26.33` to `1.26.45`.
No top-level fields or definitions were added or removed in that first cycle.

The typed comparison agrees on constant adult-reference fields except
`CustomNameVisible`, absent on unnamed editor animals. Variable fields such as
random attributes, identity, position and taming state are not treated as type
constants. This is an empirical sample, not a complete entity schema.

The saved state after mounting includes `Temper` changes for the horse and
donkey, tamed definitions and inventory tags for the mule, and a sitting state
for one camel. The mule's owner reference matches the local player's `UniqueID`.
Configured attributes remain unchanged.

The independent Amulet-NBT reference under Python 3.12 agrees with the project
codec on recursive types and values across all snapshots; both reproduce the
original bytes. Snapshot integrity checks also cover the Python 3.14 application
environment without the reference dependency.

## Evidence and limits

The experiment used disposable world copies. Playable saves, private snapshots,
backups and preparation reports are not distributed. The public suite uses
synthetic fixtures and individually reviewed isolated entity records under
`tests/data/`; see its fixture contract before adding reference data.

This directly validates native creation, reading, game acceptance, persistence,
basic mounting and an observed taming transition for the sampled animals.
Command mounting does not establish normal right-click mounting, saddled
steering, measured jump height/speed, breeding, every equipment/inventory
combination, all color combinations, baby creation, other dimensions or
multiplayer ownership behavior. Other Minecraft animals are outside this
five-type creation scope. Future game versions and unusual/corrupted worlds
still require separate validation.
