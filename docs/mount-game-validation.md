# Mount creation: Minecraft acceptance validation

Acceptance experiment on **2026-09-13**, with Windows Store Minecraft Bedrock
**26.45** and the application's native storage backend under CPython **3.14.4**.
This extends the [dependency portability assessment](dependency-portability-assessment.md).

## Scope and result

All five mount types currently supported for synthetic creation were exercised.
Minecraft created three reference animals per type; the normal editor service
created three additional adult animals per type using `synthetic_full`.
All 30 distinct actors survived two Minecraft load/save cycles. Every editor
animal retained its identity, complete attributes and appearance variants.

| Type | Minecraft references | Adult references used for constant-field comparison | Editor animals retained | Successful command mounting |
| --- | ---: | ---: | ---: | ---: |
| Horse | 3 | 2 | 3/3 | 1 |
| Donkey | 3 | 3 | 3/3 | 1 |
| Mule | 3 | 2 | 3/3 | 1 |
| Skeleton horse | 3 | 2 | 3/3 | 1 |
| Camel | 3 | 2 | 3/3 | 1 |

The reference summons also produced four babies. Their records were included
in codec validation, but only adult references were used to establish constant
adult fields. The editor animals were all adults.

## Procedure

1. Hash every file of a local, nonexperimental creative world with cheats
   enabled, then create a separate world copy. Original-world databases are
   never opened for writing during this test.
2. Add a local behavior pack containing command functions only, with no entity
   definitions or behavior overrides. Build two rows of five enclosed pens on
   a raised platform to distinguish the test population from existing animals.
3. In Minecraft, summon three named reference animals of each type, then use
   Save & Quit. Names such as `REF_horse_1` identify the reference records.
   The 60-command preparation function completed successfully in the game.
4. Preserve the reference-only copy. With the world closed, call
   `create_horse_mount_with_service` through `BedrockEditorService` under
   Python 3.14, once per editor animal. Use the real native LevelDB backend,
   normal backups and post-write validation. Do not mock or bypass guards.
5. Compare every database key/value before and after editor creation. Only
   new actor records and their affected `digp` indexes may differ. Preserve
   the database before Minecraft loads the editor animals.
6. Open the copy in Minecraft, inspect the editor row and allow simulation,
   then Save & Quit. Preserve and inspect this first saved state before
   interacting with the animals.
7. Reopen the same world. Use a spatially restricted `/ride` command to mount
   one editor animal of each type, verifying the success message, mounted
   perspective and animal health HUD. Dismount with the configured game key.
   Save & Quit again, then preserve and validate the second saved state.

The references used Minecraft's documented named
[`summon` command](https://learn.microsoft.com/en-us/minecraft/creator/reference/content/commandsreference/examples/commands/summon?view=minecraft-bedrock-stable).
Mounting used the documented
[`ride` command](https://learn.microsoft.com/en-us/minecraft/creator/commands/commands/ride?view=minecraft-bedrock-stable),
for example `/ride @s start_riding @e[type=minecraft:horse,x=246,y=86,z=392,r=5,c=1] teleport_rider`.
These coordinates identify a pen in this particular test copy.

## Data checks and observed differences

The three editor horses used health values 24/25/26, movement values
0.20/0.21/0.22, jump strengths 0.60/0.65/0.70, and color/mark values 0/1/2.
These configured values were checked directly, allowing only float32 rounding.
Other types used their normal editor defaults.

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

The adult reference comparison recursively retained NBT types and list element
types. Across each type's adult references, respectively 56/58/58/59/63
top-level fields had identical typed values. The editor animals matched every
one of those fields except the intentionally absent `CustomNameVisible`:
reference animals were named, editor animals were unnamed. Fields that varied
between references were reported separately, not claimed to match. Depending
on type, these include random attributes, color/mark definitions, `Temper`,
`canPickupItems`, identity/storage references, position, rotation and sitting
state. This comparison is an empirical sample, not a complete entity schema.

The second save additionally recorded gameplay transitions: the ridden horse
and donkey changed `Temper`; the ridden mule became tamed, acquired the local
player's world-internal owner reference, tamed definitions and inventory tags;
one camel entered its sitting state. The mule's heart particles were visible
during mounting. Its saved owner was checked against the local player's
`UniqueID`. These transitions did not change the configured attributes.

An independent Amulet-NBT oracle in the separate Python 3.12 reference
environment parsed all 30 records from all three snapshots: **90 record
checks**. Recursive types/values matched the new codec, and both serializers
reproduced every original record byte for byte. The same snapshot integrity
checks also run in the clean Python 3.14 application environment without the
oracle dependency.

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
still require separate validation. No numerical failure probability or
near-certainty claim follows from this finite experiment.
