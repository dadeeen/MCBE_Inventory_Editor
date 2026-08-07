# Experimental Mount Creation

This document records the durable engineering contract for creating persistent Minecraft Bedrock mounts directly in a stopped world's LevelDB. It is not a user guide or a progress log.

The feature is experimental. Test it on expendable world copies before using it on important data.

## Supported scope

The synthetic writer supports:

- horse (`minecraft:horse`);
- donkey (`minecraft:donkey`);
- mule (`minecraft:mule`);
- skeleton horse (`minecraft:skeleton_horse`);
- camel (`minecraft:camel`).

Creation is limited to the Overworld. A known non-zero `dimension_id` is rejected. If the dimension is absent from player NBT, the UI warns that the loaded Overworld context is being assumed.

The normal UI uses `synthetic_full`. Compatibility and comparison modes may remain in the backend, but they are not separate user workflows.

Type-specific definitions, attributes, equipment lists, and editable ranges are centralized in `MOUNT_WRITE_SPECS` and enforced by the writer:

- horses support bounded health, movement, jump strength, color, markings, and taming progress;
- donkeys and mules support bounded health, bounded taming progress, and an optional tamed state; taming progress is offered only for the wild variant, because taming removes the tag;
- skeleton horses support bounded jump strength;
- camels use their own attribute and component structure.

Generated values must remain within the observed bounds and pass the same post-write validation as explicit values.

Values the game rolls per specimen are rolled, not fixed. Taming progress (`Temper`) is one of them: 41 scanned horse, donkey and mule records spread over 0 to 98, so a constant would mark every created animal as editor-made. Horses take it from the horse profile — random mode draws it from the same seeded generator as the other profile values, so one seed still reproduces one exact record, and custom mode exposes it as a bounded field. Donkeys and mules roll it from the same generator that already rolls their health, and expose the same bounded field on their wild variant. Skeleton horses and camels carry no `Temper` at all, and taming removes it — the tamed variants therefore offer no field, and a submitted value is dropped rather than written.

## Persistence invariants

A persistent entity requires coordinated LevelDB records:

1. an `actorprefix` key with an eight-byte actor suffix;
2. Bedrock little-endian actor NBT;
3. a `digp` chunk index containing the same suffix;
4. a matching `StorageKey` inside `internalComponents`.

The actor suffix consists of a big-endian group and local ID. `UniqueID`, the actor key, `digp`, and `StorageKey` must all represent the same identity. StorageKey conversion must use the reversible Bedrock UTF-8 escape codec; a Latin-1-to-UTF-8 conversion changes bytes above `0x7f` and is invalid.

Synthetic records use persistent entity flags and a collision-safe actor ID that does not already exist in the world. Unknown existing `digp` bytes must be preserved.

## Placement contract

The preview checks four directional lines around the player. With rotation, these are forward, right, left, and behind; without rotation, the fixed cardinal directions are used. This is not a full-area scan.

Every candidate keeps at least `MIN_PLACEMENT_RADIUS` blocks of horizontal distance from the player, and stays within the chosen search radius apart from the half-block-per-axis slack that whole-block rounding implies.

Offsets are whole blocks, so a diagonal cannot hit an arbitrary distance exactly. Nearest rounding keeps a candidate closest to the requested distance, but it shortens diagonals, and at the inner end that breaks the floor: a 45° direction at distance 2 rounds to `(1, 1)`, which is 1.41 blocks. Only in that case are the components rounded away from zero instead. Overshooting is then unavoidable — no whole-block diagonal lies between 1.41 and 2.83 blocks — so it is confined to the one step where the alternative would place the mount too close. Pushing every diagonal outward instead would trade the broken floor for a broken radius.

The browser sends only a bounded offset. At preview and save time, the backend:

- reads the current player position from NBT;
- derives the absolute mount position itself;
- decodes the relevant Bedrock subchunks;
- evaluates the mount-specific footprint;
- rejects duplicate computed positions.

Client-supplied absolute coordinates are never authoritative.

The conservative footprint check requires:

- load-bearing, non-liquid ground at the center;
- passable body space in every checked column;
- enough vertical clearance for the mount type;
- no known unsafe partial surface.

Air variants and a small allowlist of non-solid vegetation and overlays are passable. Liquids, slabs, stairs, fences, carpets, leaves, farmland, and other collision-sensitive blocks are not accepted as proven-safe placement without exact collision information.

Two different reasons for "not confirmed" are kept apart, because they warrant different verdicts:

- the ID alone establishes an unusable top surface (slab, stairs, wall, fence, carpet, farmland, mud, soul sand, anvil, chest, hopper) — a failed check, so `unsafe`;
- the shape hinges on a block state this probe does not decode (snow layer, piston, sticky piston) — missing data, so `unchecked`, which the user may confirm.

Neither ever counts as confirmed support. At a footprint edge the two are still treated differently: a known-unusable surface rejects the placement there as well, while a state-dependent one counts as tolerated overhang as long as the center carries.

Results have three classes:

| Class | Meaning | Save behavior |
|---|---|---|
| `safe` | Required terrain data is known and the footprint passes | Allowed |
| `unchecked` | Data is missing or cannot be decoded unambiguously | Requires explicit confirmation and a save-time re-check |
| `unsafe` | Support, clearance, or liquid checks fail | Rejected server-side |

The block probe currently supports paletted subchunks v8 and v9.

Block indexes are read in Bedrock's fixed XZY order, `(x << 8) | (z << 4) | y`. That order is a property of the format, not something to infer per world: alternative orderings exist in the module for diagnostics only and must never take part in a placement verdict. Selecting whichever ordering produces the most placeable-looking result resolves every ambiguous read towards `safe`, which is the opposite of the guarantee below.

When the queried subchunk record is absent, chunk presence is established from the chunk version record (`0x2C`, or `0x76` in worlds older than 1.16.100) or the biome record (`0x2B`, or `0x2D` before 1.18). Presence alone does not prove that terrain generation is complete: the `FinalizedState` record (`0x36`) must contain `2` before the probe may return `safe`. State `0`, state `1`, an absent record, or an unreadable value keeps the position `unchecked`, even when all queried blocks are already readable, because later population may still change them. Only inside such a finalized chunk does a missing subchunk record mean air — Bedrock stores nothing for an all-air subchunk. Without a stored subchunk, version, or biome record the chunk is treated as ungenerated and likewise stays `unchecked`.

Chunk keys never fall back across dimensions. A Nether or End key carries the dimension component, and the bare key is the Overworld chunk at the same coordinates, so falling back to it would answer a missing chunk with another dimension's terrain. A non-Overworld probe has no fallback and reports an absent record as ungenerated. Create and save reject a non-Overworld context outright; the preview stays readable and reports `unchecked`.

Ambiguous palette-count interpretations are resolved conservatively; an uncertain result must not be promoted to `safe`.

## Atomic write and failure behavior

`Stage mount` changes only the browser workspace. The confirmed workspace save:

1. re-checks presence, player revision, server guard, and placement;
2. creates exactly one world backup;
3. prepares the player record and all mount `actorprefix` and `digp` values;
4. writes the complete set with one LevelDB `putBatch`;
5. reads every affected record back and validates it.

At minimum, validation must confirm:

- exact read-back of the written actor and `digp` values;
- actor identity consistency across key, `UniqueID`, and `StorageKey`;
- correct `digp` chunk derived from the final position;
- preservation of the previous `digp` value;
- parseable NBT and the requested identifier;
- expected definitions, attributes, and equipment tag types.

A failure before the batch is a normal rejected save and must leave the world unchanged.

A failure after the batch has committed is different. The response uses `success=false`, `write_committed=true`, and `validation_failed=true`. The frontend must adopt the returned revision, remove already written drafts, show the backup notice, and prevent an unchanged retry. Repeating a committed operation could create duplicate entities.

## Safety gates

Mount creation uses the same write boundary as player saves:

- loaded-player revision and opaque server guard;
- presence-conflict handling;
- configured Bedrock server reachability check;
- explicit confirmation for unknown server status;
- final server check immediately before `putBatch`;
- backup before the write;
- post-write validation.

A confirmation for unknown status never overrides a later `online` result. `MCBE_READ_ONLY=true` rejects mount creation.

## Known limits

- Only the Overworld is supported.
- Placement is a conservative approximation, not Minecraft collision physics.
- The scan follows four directional lines rather than covering a full area.
- Add-ons, future Bedrock formats, unusual terrain, and ambiguous subchunks may remain `unchecked`.
- Compatibility across all Bedrock versions and repeated Minecraft load/save cycles cannot be guaranteed.
- Tamed donkey and mule ownership uses the world-internal player actor identity; it does not transfer external account identity or pet ownership from another player.
- Manual in-game load tests are still pending for synthetically created tamed donkeys and mules.
- Not all non-default horse colors and markings have been visually confirmed in game. The reference fixture currently pins the definitions mapping for colors 3, 5 and 6 and markings 1 to 4 against real Minecraft records; the remaining combinations rest on the lookup tables alone.

Open product work belongs in the issue tracker. Historical experiments and one-off world observations belong in private diagnostics, not in this contract.

## Verification

Relevant automated coverage:

```bash
python -m pytest \
  tests/test_mounts.py \
  tests/test_mount_write.py \
  tests/test_mount_write_horse_profile.py \
  tests/test_mount_create_horse_profile_route.py \
  tests/test_workspace_save.py
```

Manual verification for a relevant Bedrock change should use a stopped world copy:

1. record the preview and selected placement;
2. save and retain the validation result and backup;
3. load, save, and close the world in Minecraft;
4. verify that the entity remains visible and indexed;
5. repeat after a second Minecraft load/save cycle when persistence behavior changed.

Success requires stable actor identity and index records, normal simulation in Minecraft, and consistent rejection of unsafe placement by both UI and backend.
