# Save Contract

This document describes the current contract between frontend and backend for saving player changes and staged mount changes. Changes to `static/save_payload_logic.js`, `static/save_controller.js`, the save routes, or `EditorService.save_player()` must preserve these invariants, or the document and the regression tests must be adjusted together.

## Endpoints and selection

The frontend sends JSON via `POST` with CSRF headers from `window.MCBEApiClient`:

| State | Endpoint | Behavior |
|---|---|---|
| No staged mounts | `/api/player/save` | Saves changed player sections only. |
| At least one staged mount | `/api/workspace/save` | Saves player changes and all mount records in one shared LevelDB batch. |

`static/save_controller.js` selects the endpoint exclusively based on the current mount drafts. The workspace endpoint accepts at most 32 mounts per operation.

The Flask routes remain registered in `main.py`. Player orchestration lives in `mcbe_editor/player_api_routes.py`, workspace orchestration in `mcbe_editor/mount_api_routes.py`.

## Shared base fields

Every generated save payload starts with:

```json
{
  "world_path": "...",
  "player_key": "...",
  "session_id": "...",
  "base_revision": "...",
  "server_guard_epoch": 0,
  "server_guard_token": "...",
  "stats": {}
}
```

- `session_id` comes from the world presence session.
- `base_revision` is the revision of the loaded player and must be sent unchanged with every network save.
- `server_guard_token` is the authoritative, opaque snapshot guard returned when the player was loaded. It must be sent unchanged with every network attempt.
- `server_guard_epoch` is retained as diagnostic metadata and for compatibility with older frontends. It is not an authorization credential.
- `stats` is always present but may be empty.

Depending on the confirmation flow, the following may be added:

- `confirm_presence_conflict: true`
- `confirm_unknown_server_status: true`
- `allow_create_inventory: true`
- `allow_create_ender_chest: true`
- `allow_create_effects: true`
- `allow_create_abilities: true`
- `root_equipment_editable: true`

## Mount payload of the workspace save

With staged mounts, the controller adds `mounts` as a list. Every draft contains the selection values that are re-checked server-side:

```json
{
  "mounts": [
    {
      "mount_type": "minecraft:horse",
      "create_mode": "synthetic_full",
      "placement_radius": 6,
      "preferred_offset": {"x": 2, "z": 0},
      "horse_profile": null,
      "mount_stats": null,
      "tamed": false,
      "allow_unchecked_placement": false
    }
  ]
}
```

Absolute positions from the browser are not trusted. The backend preview path recomputes every position from the current player snapshot and the bounded offset. Unsafe positions are rejected; unchecked positions require `allow_unchecked_placement=true`. Two mounts must not use the same computed position.

The workspace save prepares the changed player record as well as all new `actorprefix` and merged `digp` records. After exactly one backup, `putBatch` writes the complete key set atomically. The response only counts as successful if every created mount has been validated afterwards.

## Invariants for included player sections

A missing field always means: "Do not modify this NBT section." This applies to both save endpoints.

### Inventory

- Only send `inventory` if no clean snapshot exists or the inventory section has changed.
- If included, send the complete visible container state as a list.
- A change in another section must not pull the unchanged inventory into the payload.
- Writable root equipment may require `root_equipment_editable=true`; read-only echo items must never be sent as changes.

### Ender chest

- Only send `ender_chest` if no clean snapshot exists or the section has changed.
- If included, send the complete visible ender chest state as a list.
- Other changes must not pull the unchanged ender chest into the payload.

### Stats

- Always send `stats`.
- Include only changed scalar keys from `health`, `xp_level`, `xp_progress`, `food_level`, and `food_saturation`.
- Treat `pos` and `dimension_id` as one player location: if either changes, include the complete current three-axis `pos` and, when it is present, valid, and editable, the current `dimension_id`.
- Never send `dimension_id` without `pos`; the backend rejects such a partial dimension switch. Missing or opaque location components are protected and must not be synthesized.
- Compare number-like values numerically and arrays index-wise numerically.
- Remove protected stat fields before sending.

### Effects

- Only synchronize UI values if the effects section is not opaque and it has been touched, already exists as a tag, or is not empty.
- Only send `effects` on an actual change.
- With `protectedNbt.active_effects_opaque`, never send `effects`.

### Abilities

- Only collect UI values after an actual user change and only for non-opaque data.
- Only send `abilities` if a non-null object with actual changes exists.
- With `protectedNbt.abilities_opaque` or `playerAbilities._opaque`, never send `abilities`.

## No-op behavior

If the payload contains no player changes and there are no mount drafts, no save endpoint may be called and no backup created. The state is marked clean and the existing no-op message is shown.

If there are no player changes but at least one mount draft, `/api/workspace/save` must still be called. A mount-only workspace save is not a no-op.

## Confirmation when creating missing tags

Confirmations happen after payload construction and before the save review view:

- A missing `Inventory` with a non-empty `inventory` requires `allow_create_inventory=true`.
- A missing `EnderChestInventory` with a non-empty `ender_chest` requires `allow_create_ender_chest=true`.
- A missing `ActiveEffects` with non-empty `effects` requires `allow_create_effects=true`.
- A missing `abilities` with at least one key other than `_opaque` requires `allow_create_abilities=true`.
- Declining ends the operation before review and network request.
- Empty lists or pure marker objects do not create missing tags.

After a successful save, the frontend updates the respective `has_*_tag` and confirmation states.

If the mount post-validation fails after an already completed workspace write, the backend responds with `success=false`, `write_committed=true`, and `validation_failed=true`. The same applies to any error occurring after the committed `put_batch` — for example while closing the database or pruning old backups: these post-write errors must no longer overwrite the write status and are likewise reported with `write_committed=true`, not as a normal 500 error. This is not a normally retryable error: the frontend adopts the revision and any created player tags, marks the local state as written, removes the already written mounts from the queue, and shows an error with a backup notice. It must not display normal success and must not release the save button for an unchanged retry — even if processing of optional mount details fails afterwards.

The mount write receipt reads actor and `digp` values back immediately after the atomic batch and compares them byte-exactly with the final write plan. In addition, the expected `digp` key is recomputed from the final mount position. This is a targeted write-set check; a full world diff is neither required nor part of the save path.

## Revision, presence, and write gates

- `base_revision`, `session_id`, `server_guard_epoch`, and `server_guard_token` must remain present on every network attempt.
- A stale `base_revision` is rejected by the backend.
- On a presence conflict, the frontend asks the user. After consent, the same payload is re-sent with `confirm_presence_conflict=true`; on decline, the dirty state remains.
- With unknown server status, the frontend asks the user. After consent, the same payload is re-sent with `confirm_unknown_server_status=true`.
- A confirmed unknown status is not a permanent override: if the server is detected as online during a repeated or final check, the operation remains blocked.
- The player and workspace endpoints check the write gate before service execution and again immediately before the LevelDB write.
- A changed or missing `server_guard_token` between preview/load and save blocks the operation. The backend checks it when accepting the request and again at the final LevelDB write boundary.
- Successful responses update `currentPlayerRevision` from `player_revision`, if present.

## Protected and preserved NBT data

Item serialization removes pure frontend metadata:

- `protected_nbt_summary`
- `preserved_nbt_summary`
- `nbt_view`
- `protected_nbt_dropped`
- `previous_name`
- `special_nbt_defaulted`
- `special_nbt_requirement`
- `root_equipment_source_tag`
- `root_equipment_source_index`

`root_equipment_read_only` is not removed wholesale: read-only root echo items are already filtered out beforehand; if the flag nevertheless reaches the backend, the stray copy is rejected there.

For items with original NBT that must be preserved, these rules continue to apply:

- External source references to another player or another world are preserved.
- Same-world external player items actually used as NBT bases are recorded by player key, container, slot, item name, and preservation digest. After the backup and database reopen, those exact sources must still match before the final write.
- Source references to the same player are only accepted if they still match the clean snapshot.
- During a repair, the clean inventory and ender chest snapshots are searched.
- A repaired source is only used on exactly one unambiguous match.
- Unknown or future hidden NBT data is preserved through section omission and backend merge.
- Opaque inventory/ender chest lists must not be replaced.

## Required regression tests

Before changes to the save behavior, at least these areas must stay green:

```bash
python -m pytest \
  tests/test_frontend_save_payload_logic.py \
  tests/test_frontend_save_controller.py \
  tests/test_workspace_save.py \
  tests/test_service.py \
  tests/test_nbt_safety.py
```

Also relevant are the structural script-order tests in `tests/test_dirty_world_indicator.py`, the unknown-server-gate tests, and the mount write tests.

Cross-player copy coverage must include a source change injected during `create_backup()`: the save is rejected before `put`/`putBatch`, the target remains unchanged, and the unused backup is removed.
