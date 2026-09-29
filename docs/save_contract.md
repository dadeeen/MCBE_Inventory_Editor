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

Known footprint obstructions, liquids and unsupported central floor blocks take precedence over missing neighboring columns. The unchecked-placement confirmation cannot override an obstruction already established by readable terrain data. Tamed mounts require a valid integer owner ID from the current player in both direct creation and workspace saves; a missing or opaque player ID must not produce an ownerless tamed entity.

The workspace save prepares the changed player record as well as all new `actorprefix` and merged `digp` records. After exactly one backup, `putBatch` writes the complete key set atomically. The response only counts as successful if every created mount has been validated afterwards.

## Invariants for included player sections

A missing field always means: "Do not modify this NBT section." This applies to both save endpoints.

### Inventory

- Only send `inventory` if no clean snapshot exists or the inventory section has changed.
- If included, send the complete visible container state as a list.
- A change in another section must not pull the unchanged inventory into the payload.
- Writable root equipment may require `root_equipment_editable=true`; read-only echo items must never be sent as changes.
- A root equipment entry hidden by an existing legacy Inventory equipment slot is not a missing visible item. Unrelated inventory changes must preserve that hidden root entry, even when `root_equipment_editable=true`.

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
- Form synchronization must leave opaque and unknown effect rows untouched. Stored negative durations are protected because the seconds form cannot represent them safely.
- Unchanged boolean effect controls retain their original byte values, including nonzero values other than `1`; only an actual boolean change rewrites them.

### Abilities

- Only collect UI values after an actual user change and only for non-opaque data.
- Only send `abilities` if a non-null object with actual changes exists.
- With `protectedNbt.abilities_opaque` or `playerAbilities._opaque`, never send `abilities`.
- Marker-only or unknown-only ability objects are no-ops at the backend too; they must not require creation confirmation, create an empty compound, or trigger a backup.
- The editable fields are speeds: `fly_speed` (`flySpeed`, horizontal flight, 0–1), `vertical_fly_speed` (`verticalFlySpeed`, climbing and descending, 0–20), `walk_speed` (`walkSpeed`, 0–1) and `movement_speed` (`Base` and `Current` of the `minecraft:movement` attribute, 0–1). Bedrock derives `mayfly`, `flying`, `invulnerable`, `instabuild` and the permission flags such as `build` from the game mode and the player permission level when the player loads. The editor neither shows nor writes them, and the backend ignores such keys.
- In Bedrock, `walkSpeed` only sets the reference for the field of view; `minecraft:movement` is the walking speed. A movement edit in the form also sets `walk_speed` to the same value, which keeps the field of view normal. The backend stores both independently.
- `movement_speed` never creates the attribute or the `abilities` compound. `protected_nbt.movement_speed_locked` names why it is not editable: `missing`, `modifiers` (a non-empty `Modifiers` list, for example from sprinting or an effect, makes `Current` differ from `Base`) or `value` (duplicate entries, a non-float type, a non-finite value, `Base` outside 0–1 or `Base` ≠ `Current`). The frontend omits a locked field and shows the reason; the backend rejects it.

## No-op behavior

If the payload contains no player changes and there are no mount drafts, no save endpoint may be called and no backup created. The state is marked clean and the existing no-op message is shown.

If there are no player changes but at least one mount draft, `/api/workspace/save` must still be called. A mount-only workspace save is not a no-op.

## Confirmation when creating missing tags

Confirmations happen after payload construction and before the save review view:

- A missing `Inventory` with a non-empty `inventory` requires `allow_create_inventory=true`.
- A missing `EnderChestInventory` with a non-empty `ender_chest` requires `allow_create_ender_chest=true`.
- A missing `ActiveEffects` with non-empty `effects` requires `allow_create_effects=true`.
- A missing `abilities` with `fly_speed`, `walk_speed` or `vertical_fly_speed` requires `allow_create_abilities=true`. The frontend asks for any ability key other than `_opaque`, because it always sends the complete speed set.
- Declining ends the operation before review and network request.
- Empty lists or pure marker objects do not create missing tags.

After a successful save, the frontend updates the respective `has_*_tag` and confirmation states.

If the mount post-validation fails after an already completed workspace write, the backend responds with `success=false`, `write_committed=true`, and `validation_failed=true`. Service errors after the committed `put_batch`, such as database close or backup-retention errors, retain `write_committed=true`. This is not a normally retryable error: the frontend adopts the revision and any created player tags, marks the local state as written, removes the already written mounts from the queue, and shows an error with a backup notice. It must not display normal success and must not release the save button for an unchanged retry — even if processing of optional mount details fails afterwards.

A database call that raises after its batch reached the log is a different outcome: the WAL may already be durable even though `put`/`put_batch` did not return. `WriteState` records this at the call itself, before any exception translation, from the writer's `last_write_reached_log()`; databases without that evidence count as reached. Player saves, workspace saves and direct mount creation raise `WriteOutcomeUnknownError` at this boundary. Their APIs return HTTP 500 with `write_outcome_unknown=true`, `reload_required=true`, `error_phase="write"` and the retained `backup_file`, without claiming either a confirmed commit or a rollback. The frontend blocks further writes until reload, keeps the draft and pending mounts, and does not adopt a revision or mark the state clean. Confirmation prompts must not retry such a response. A known final gate rejection (`WriteNotAttemptedError`) and failures before the first append, such as a denied log creation, size limits or sequence refusals, use the ordinary pre-write rejection contract and keep their own message, including permission hints; their backup is retained. Import and state transfer have their own verified rollback contracts.

This distinction matters for mount-only batches: they do not change the player revision, so revision checking alone cannot prevent a duplicate actor after an ambiguous result. The reload requirement protects the shipped UI; the API is not an idempotency-key protocol and third-party clients must also respect the outcome field. Regression tests exercise real durable WAL writes followed by bookkeeping failures and check the resulting API and browser behavior.

The mount write receipt reads actor and `digp` values back immediately after the atomic batch and compares them byte-exactly with the final write plan. It independently decodes the stored Float32 `Pos`, checks it against the plan, and derives the expected chunk index from those stored coordinates. Preview generation and footprint checks use the same storable coordinates, including after placement adjustments. Non-finite values, Float32 overflow, and rounded coordinates outside the supported chunk range are rejected before writing. This is a targeted write-set check; a full world diff is neither required nor part of the save path.

Equine templates are eligible only when unowned and unequipped, with no active tame, rider, leash, target, breeding, or death state in the checked fields. Nonempty or malformed `LinksTag` data and conflicting active tame/equipment definitions exclude a template. Automatic creation falls back to the synthetic writer if no eligible template exists; explicit template cloning fails before the write. Eligible templates retain unknown passive data while identity and the requested horse profile are replaced. Post-validation checks tame and owner values/types, exact definitions, absent actor links, and empty equipment against the creation contract. These checks do not establish complete in-game semantics for arbitrary unknown entity fields.

Readonly database access validates SST block CRC32C before decompression and rejects invalid uint64 varints and file handles outside the table. Stored and expanded blocks are limited to 64 MiB; MANIFEST and relevant WAL input share a 256 MiB budget per reader. These are input limits, not a guarantee of total process memory usage. Larger inputs fail explicitly. A reader keeps at most 64 table files open: tables of levels above 0 are scanned one after another when their MANIFEST key ranges are disjoint, as LevelDB guarantees, and are otherwise merged table by table. A table closed for this budget and read again must keep its size, modification time and file identity. LevelDB never rewrites a table or reuses its file number, so a table that compaction removed while the reader ran fails the read instead of mixing two world states. This is change detection, not a snapshot: a rewrite that keeps all three values goes unnoticed. The reader does not lock against concurrent external writes.

Finding a world's players reads every record. The service's bounded `PlayerDirectory` therefore retains discovered lists for at most eight worlds, keyed by the reader's parsed MANIFEST/WAL digests and the number, file identity, size and modification time of every live table. A matching fresh reader can reuse a list, with labels localized for the current request. An ordinary save to one existing recognizable player can promote the list using the writer's verified `CommittedDbChange`: its expected token is derived from the original state and committed WAL bytes, never from an unrelated later observation. External writes, recovery, restore, unknown-key edits and combined writes require discovery again. The directory is not persisted, and writers offer no ordinary reader cache token.

Known player keys are validated directly from the selected record; unfamiliar keys must also belong to the bounded discovery result. Saves always reread the selected bytes and check the revision through the locked writer. Cached metadata does not authorize writes or replace backup, server-status or concurrency checks. If post-write directory maintenance fails, a durable save remains committed. See [the writer design](leveldb-writer.md#player-list-after-saves).

SST internal keys only admit value and deletion entry types. Point lookups and iteration must agree on the newest version, including tombstones. Files in deeper levels have disjoint internal-key ranges, but versions of the same user key may span adjacent files; MANIFEST insertion order must not decide which version a point lookup returns. The locked writer's revision recheck remains necessary even after a successful readonly load.

Only the newest relevant WAL enables recovery of a truncated physical payload or a CRC-damaged physical record ending exactly at EOF. Incomplete payloads must still fit within their declared 32 KiB block. This recovery discards the entire unfinished logical batch, logs a warning, and leaves the database files untouched. An unfinished logical fragment composed of otherwise valid physical records is also ignored in MANIFEST and older WAL files, matching native recovery; it is not exposed as a partial batch. The reader does not scan past CRC-damaged blocks. Native-engine comparisons cover intact earlier writes, overwritten and deleted keys, fragmented batches, and the service's list/load paths; this is not an interactive Minecraft recovery test.

Before publication or retention cleanup, newly created backups must pass the same archive validation as restore: the installation's uncompressed-size limit (default 1 GiB) and 50,000 entries, including directories, plus the existing path checks. The Backup Manager persists the size limit separately in `data/backup_settings.json`; an explicit `MCBE_BACKUP_MAX_UNCOMPRESSED_MIB` operator override takes precedence and cannot be changed through the API. Both accept whole MiB in the range 1–1,048,576. Invalid explicit settings fail rather than silently changing the policy. Exceeding a limit aborts backup creation and any dependent write; it must not publish an unusable recovery copy or prune older backups. Temporary archives are removed on failure.

Backup creation checks the source size and member count before opening its ZIP writer. LevelDB tables (`.ldb`, `.sst`) are stored without recompression, since Bedrock already deflates their blocks; all other members are deflated, and every member keeps its ZIP CRC. Restore validates archive headers before CRC decompression and checks additional disk space for the immutable source, pre-restore backup and staging world before creating those copies. Requirements sharing a filesystem are added together. Estimates include ZIP overhead and a reserve of max(64 MiB, 5%); these are preflight estimates, not disk reservations. Mid-operation I/O errors go through the staging cleanup and rollback handling.

All backup kinds use the shared `backup_consistency.source_snapshot()` check inside the world lock. The first metadata snapshot precedes metadata collection and ZIP creation; the second follows CRC verification and must match before the temporary ZIP can be published. A final comparison after archive synchronization and publication also detects source changes during those steps. A changed or unreadable source rejects the new archive before retention and before a dependent workflow can open its mutating database or replace a world. Failed cleanup is attached to the original error. The manual API also retains its outer source checks and final server gates. These are metadata comparisons, not content hashes or atomic filesystem snapshots; a fully stopped world remains required.

Restore binds the target world to the snapshot taken before its pre-restore safety backup and compares it again immediately before the first directory rename. Extracted files are flushed and synchronized before the swap, followed by their containing directories from children to parents where supported. File synchronization failures and supported directory synchronization failures abort while the current world remains in place. Directory transaction errors preserve the journal and rollback state when the swap is unresolved. Recovery synchronizes a completed replacement rename before removing the original world directory. `tests/test_restore_durability.py` checks these failure boundaries and recoverability. An external change during extraction aborts the restore, preserving the changed world and the safety backup. Invalid ZIP-comment metadata must fall back to the existing filename/legacy classification without breaking listing or retention for other archives.

The completed temporary ZIP is `fsync`ed before either publication path. The exclusive-copy fallback also flushes and synchronizes its new target. Newly created parent-directory entries and the publication directory are synchronized where supported. Windows skips directory synchronization; POSIX only ignores explicitly unsupported operations, while permission and I/O errors propagate and block dependent writes. An existing target is never replaced or removed on a naming collision. Storage hardware and filesystems still determine the ultimate power-loss guarantees.

`WritePlan` owns an immutable copy of the binary record/batch mapping. `WriteState.execute()` tracks `PREPARED`, `ATTEMPTED`, and `COMMITTED` separately and rejects a repeated attempt. A failed database call stays `ATTEMPTED`, because an exception cannot prove that storage was untouched. Save and mount workflows retain the backup after an attempted write; import and migration keep their existing conditional rollback. A confirmed commit remains committed through validation, close, retention, and response errors.

Run the opt-in synthetic ZIP64 roundtrip with `MCBE_RUN_LARGE_BACKUP_TESTS=1 python -m pytest tests/test_backup_settings.py -k real_zip64 -q`. It writes more than 2 GiB, performs a service-level restore including its pre-restore backup, and compares SHA-256 digests. Allow at least 7 GiB of free temporary storage. The ordinary suite simulates insufficient space, separate/same filesystems and an ENOSPC extraction failure without filling a real disk.

A body-read failure, malformed or empty JSON, or a response without a boolean `success` cannot establish whether a write committed. The API client marks these responses as unreadable; the save controller treats them as connection failures, including after confirmation retries. With staged mounts it blocks further saves until reload. A valid backend rejection with `success=false` remains retryable unless it explicitly reports a committed or unconfirmed write. Incoming malformed JSON and requests exceeding the JSON decoder's nesting limit receive HTTP 400 before their operation handler runs.

The direct `/api/mount/create` path also performs its initial player checks through the readonly database adapter. It opens the mutating adapter only after the backup succeeds, so a failed backup leaves the original database files untouched.

## Revision, presence, and write gates

- `base_revision`, `session_id`, `server_guard_epoch`, and `server_guard_token` must remain present on every network attempt.
- A stale `base_revision` is rejected by the backend.
- On a presence conflict, the frontend asks the user. After consent, the same payload is re-sent with `confirm_presence_conflict=true`; on decline, the dirty state remains.
- With unknown server status, the frontend asks the user. After consent, the same payload is re-sent with `confirm_unknown_server_status=true`.
- A confirmed unknown status is not a permanent override: if the server is detected as online during a repeated or final check, the operation remains blocked.
- A server is online when it answers the RakNet unconnected ping on UDP `MCBE_SERVER_PORT`, or `GET /v1/join` with 2xx over TCP on the same port (NetherNet). Both probes run concurrently; the first online answer wins. Other HTTP answers, such as a reverse proxy's 502 while the server is down, and silent or refused ports leave the status unknown.
- The player and workspace endpoints check the write gate before service execution and again immediately before the LevelDB write.
- A changed or missing `server_guard_token` between preview/load and save blocks the operation. The backend checks it when accepting the request and again at the final LevelDB write boundary.
- Successful responses update `currentPlayerRevision` from `player_revision`, if present.

## Protected and preserved NBT data

Player resets, export-only selection and list refreshes invalidate pending player loads. A late list response must not automatically select a player after the user changed context. Each player-load overlay belongs to its request; invalidating it closes that overlay without allowing an old completion to close a newer one.

Selecting a diagnostic-only player requires the same dirty-state confirmation as other player switches. During player loading, the shared edit guard must prevent keyboard, clipboard, undo and form actions from modifying the outgoing state. The load's busy state must be released on success, failure or invalidation without releasing a newer request's guard.

Controls retain the current player's intrinsic NBT protection and the current undo/redo availability independently of a temporary load or save lock. Renderers update that intrinsic state even while blocked; releasing the lock restores the latest state and tooltip.

Save completions also recheck the player and world after presence updates and in error handlers. A context change must not apply the old operation's revision, history, backup list or reload requirement to the new view. Status messages retain a known failed post-validation or confirmed no-op even when a later presence request fails. Starting another save request after confirmation discards the previous response as evidence of that new request's outcome.

Import responses and conflict retries also retain their confirmed target while checking the current world, player, revision, import selection and unsaved edits before updating the view. The import refresh checks the original loaded context before refreshing the player list, then expects the empty player key and revision produced by that list's own reset. Only a successful, still-current list refresh may load the target player. A failed reload is reported separately from the already completed import; a changed view is not forcibly reloaded. Known import errors retain their rollback warning, backup name and severity even after a context change.

Restore responses and their reload steps remain bound to the original world and expected player context across asynchronous boundaries. Scan-path changes report server rejections and transport failures through the existing error UI instead of continuing the success refresh; failed toggle operations restore the checkbox state.

Inventory drops require a strict internal payload and the ID of the currently active drag. The source map and item, world, and player must still match. Drag end, an accepted/rejected drop, and inventory redraws invalidate the context. Plain text and payloads from earlier drags cannot modify inventory state. Normal move/copy and equipment rules remain shared with keyboard and clipboard operations.

Section copying retains the original target's missing-tag confirmation flags. Copying statistics uses the source's protection flags and `stat_fields_unreadable` metadata to skip missing, opaque and non-finite display fallbacks. Position and dimension are copied together only when both source values are readable. Skipped values retain the target's state and produce a warning; the source's protection status does not replace the target's protection status.

Import and migration rollback recheck the target through the same locked write session used to restore it. A newer external record is neither overwritten nor deleted. A target already restored to its original bytes requires no further write. These locks complement the server-status gate; they cannot detect every running Linux Bedrock server.

XP progress must satisfy `0 <= xp < 1` both before and after Float32 conversion. Root tags and synchronized attributes receive the same rounded value; an input that rounds to `1.0` is rejected.

Ability edits leave boolean ability tags, legacy aliases and the other fields of the `minecraft:movement` attribute untouched; an echoed speed keeps its stored bits and tag type. Non-finite or out-of-range ability speeds remain protected instead of being replaced with display defaults. Populated item/effect lists with non-compound elements are protected; empty inventory and ender chest lists retain their declared element type on an unchanged save, so no backup or write is needed.

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
- External source collection includes items destined for writable root equipment. Writable root equipment remains an available copy source when its player has no Inventory tag.
- Source references to the same player are only accepted if they still match the clean snapshot.
- During a repair, the clean inventory and ender chest snapshots are searched.
- A repaired source is only used on exactly one unambiguous match.
- Unknown or future hidden NBT data is preserved through section omission and backend merge.
- Unchanged display strings retain their original tags and encoded bytes, including when another field on the item changes. Lore line breaks are normalized only in newly entered or changed lines, after resolving the original item.
- Unknown Name/Lore child types remain preserved and cannot be replaced through normal text edits. Their display representations must still be JSON-safe.
- Unknown durability and authoritative nested entity-variant tag types must not be replaced through ordinary durability or bucket-variant edits. Unchanged and unrelated edits retain those fields byte-for-byte.
- Newly entered or changed display text uses literal UTF-8. A visible `␛x41` is user text, not an instruction to write byte `0x41`; existing escaped raw-byte strings retain their original codec behavior.
- Preservation digests include the wire bytes of opaque fields, including declared empty-list types, raw strings/names and floating-point bit patterns. Even a reorder inside an opaque compound invalidates a copied source. Editable display text, counts and durability values retain their existing exemptions; empty Lore with an incompatible element type and empty enchantment list types remain preservation-relevant.
- Only actually editable enchantment entries may omit their values from provenance digests. Protected out-of-range levels, unknown types and additional duplicate entries remain fully preservation-relevant.
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
