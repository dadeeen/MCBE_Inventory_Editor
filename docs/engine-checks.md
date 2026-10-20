# Checks against the Bedrock engine

The reusable tools under `scripts/engine_checks/` belong in the public source
repository. They are developer tools, excluded from the runtime release ZIP and
application Docker image. Mojang's binaries, generated playable worlds, local
reports, backups and logs belong in the ignored `.engine-tests/` directory.
Nothing under that directory should be committed. No real world is required or
accepted by the runner. The local tool does not download or redistribute BDS.

## Execution and provenance

`python -m scripts.engine_checks` runs an explicitly supplied **official Linux
Bedrock Dedicated Server** in Docker. Automated profiles have no network and no
published ports. Every profile uses dropped
Linux capabilities, a read-only container root and one writable mount containing
a fresh disposable server. A timeout bounds each phase; only its own container
is removed. Docker must already be running. Host firewall settings and existing
containers are not changed. Linux runs as the host UID/GID; Windows bind mounts
use container UID 0 with the same capability and filesystem restrictions.
Each create attempt has a unique ownership label so its container can also be
found after a lost CLI response. Cleanup failures retain the original error and
identify the owned container instead of silently disappearing.
The generated server uses offline mode and RakNet solely to start its script
runtime without network services. Some BDS builds print a RakNet transport error;
client connections are impossible with `--network none`. Only the separately
selected `client` profile enables a bridge network with IPv4-loopback TCP and UDP
publications; it is described below and is never selected by CI or `--suite all`.
Neither these server settings nor the disposable world are deployment examples.

The exact four-part version must match BDS's own startup log. The report records
server archive/executable SHA-256, immutable local image ID, API dependency,
editor commit/dirty state, probe/editor source hashes, catalog hash and case hash.
Changed probe or editor sources at completion fail the run; rerun after edits
have finished. Hashes identify inputs; they do not attest a user-supplied binary's authenticity. Obtain
the archive directly from [Mojang](https://www.minecraft.net/en-us/download/server/bedrock).

The Vanilla script-only behavior pack does not redefine items or entities. It uses the
stable `@minecraft/server` 2.9.0 API (Bedrock 26.50 or compatible newer builds),
without GameTest/Beta experiments. The item suite waits for
[TickingAreaManager](https://learn.microsoft.com/en-us/minecraft/creator/scriptapi/minecraft/server/tickingareamanager?view=minecraft-bedrock-stable)
to load its chunks and actors even without a connected player. References:
[BDS scripting](https://learn.microsoft.com/en-us/minecraft/creator/documents/bedrockserver/scripting?view=minecraft-bedrock-stable),
[ItemTypes](https://learn.microsoft.com/en-us/minecraft/creator/scriptapi/minecraft/server/itemtypes?view=minecraft-bedrock-stable),
[ItemStack](https://learn.microsoft.com/en-us/minecraft/creator/scriptapi/minecraft/server/itemstack?view=minecraft-bedrock-stable).

## Catalog suite

- Compare every bundled addable ID with the runtime registry and try every ID in
  their union. Record `ItemStack.maxAmount`, exposed components and durability.
- Compare every recorded stack limit with the engine measurement. Contradictions
  fail. Missing catalog limits produce review candidates and a partial result,
  never automatic catalog changes or a passing result. Values above the editor's
  Count range also fail.
- Compare recorded durability with `ItemDurabilityComponent.maxDurability`,
  including disappeared components. New durable items require review and produce
  a partial result; conflicting known values fail before any offline edits.
- Failed item construction remains unverified. No implicit 1 or 64 is invented.
  Partial coverage returns exit code 2, not a green result.

## Item suite

The engine creates named chest minecarts as test carriers. Each contains an
untouched control item and assigned cases: new amount-1 items for every measurable
bundled ID; preservation of existing engine-created maximal stacks; new maximum
and maximum-minus-one stacks where our recorded limit agrees; selected Unicode
names, lore and near-broken durability cases. Existing maximal stacks also cover
IDs whose measured catalog limits have not yet been promoted.

The server stops cleanly before the offline worker opens LevelDB. A small carrier
adapter uses the **production item builder, Bedrock codec, backup creation and
LevelDB write batch** through the pure-Python WAL writer. It freezes reference
bytes before passing mutable NBT to
the builder, then verifies preserved/control items byte for byte and every
unrelated database record. Two engine reload/save cycles follow. The script only
observes stored items in those phases; it never reconstructs them. Engine-visible
semantics and saved NBT are checked after each cycle. Independent disk checks
cover occupied slots, item IDs, counts, names, lore, durability and the absence of
unexpected enchantments. Canonical empty-slot records written by BDS are accepted;
extra items, missing observations and incorrectly typed values fail. Constructor
clamping is checked during seeding too. Negative cases require the production
builder to reject new amounts -1, 0, maximum + 1 and 128 for every tested ID.

The item suite alone does **not** exercise the player service, client persistence
or gameplay. The additional profiles below extend those domains independently.
Every report records its own remaining gaps.

## Extended suite

`--suite extended` includes the item suite and measures the runtime enchantment
and potion registries. Missing/unknown domains fail instead of silently shrinking
coverage. It tests:

- Every registered item against all 42 reviewed enchantments, then every pair of
  applicable enchantments in both insertion orders. Known API incompatibility
  exceptions are recorded as rejected observations; unexpected errors fail.
- Both accepted and rejected item/enchantment combinations against the production
  editor's compatibility rules. Pair observations are compared with the catalog's
  Vanilla conflict-hint groups in both orders. Ordinary books remain preservation-only,
  and enchanted books omit conflict hints; these explicit policy exceptions have
  separate counters. Conflict hints do not prohibit NBT editing.
- Representative incompatible creations, every enchantment's levels -1, 0 and
  maximum plus one, and every durable item's damage -1 and maximum plus one through
  the production item builder. Rejected operations must leave their input NBT intact.
- Every accepted item/enchantment at every legal level; accepted pairs at their
  maximum levels; and engine-created enchanted originals preserved byte for byte.
  Plain `book` permits engine enchantments but is intentionally preservation-only
  in the editor; new enchanted books use `enchanted_book`.
- Durability boundaries 0, 1, half, maximum minus one and the exact maximum for
  every durable item. This checks stored damage, not the next gameplay use.
- Eight equipment profiles with four or five enchantments together with custom
  names, multiline lore and damage. Creation, byte-for-byte preservation, editing
  existing values and clearing the editable metadata are separate cases. The
  engine creates the preserved/original states; the editor creates the changed states.
- All reviewed data values for beds, banners, goat horns, ominous bottles,
  suspicious stews and empty maps, created by both engine commands and the editor.
- All 47 potion effects across all three runtime delivery types. Engine-created
  potion references are preserved or renamed, with raw NBT data values checked
  against an independent reviewed table.
- Real `isStackableWith` checks in both directions and `Container.addItem` calls
  for all item types, plus equal/different names, lore and durability. Engine-built
  references provide the comparison. Quantity conservation, stack boundaries,
  full-container remainders and unchanged sources are checked explicitly.
- Hopper transfers and dropped-item collection for a named item, an enchanted
  item and a potion. The item metadata must survive without duplication. Drop
  fixtures use [Entity.clearVelocity](https://learn.microsoft.com/en-us/minecraft/creator/scriptapi/minecraft/server/entity?view=minecraft-bedrock-stable#clearvelocity)
  immediately after spawning: uncontrolled initial motion otherwise lets items
  miss the hopper, producing intermittent fixture failures.

This is a finite domain, **not every possible combination**. In particular,
arbitrary combinations outside the explicit pairs and equipment profiles, every enchantment-level product,
all metadata combinations, combat, equipping, consumption, brewing and crafting
are not covered. The editor intentionally permits some NBT enchantment pairs
that normal Vanilla application rules reject; measured rejection is not a new
restriction on preserved/editable NBT.

The allowlisted summary includes added/removed enchantment identifiers and changed
maximum levels in `enchantment_registry`, and rule mismatches and negative-check
counts in `editor_rules`. An unfamiliar identifier or level mismatch fails before
world edits. Measurements do not update the editor's reviewed tables automatically.
The offline worker loads the exact candidate catalog and the repository's
compatibility rules, independently of a local compatibility-file override.

## Full player-service suite

`--suite service` places engine-generated references into two explicitly synthetic
player envelopes (`~local_player` and a synthetic server player). The real
`BedrockEditorService.load_player/save_player` performs creation, editing,
cross-container moves and deletion/recreation in Inventory and
EnderChestInventory, including their last slots, names/lore, damage, enchantments
and a healing potion. It checks backed-up saves, no-op saves without writes or
backups, stale revision rejection, untouched typed player fields and every
unrelated LevelDB record. Both results are independently checked; items then
return to engine carriers for two real save/reload cycles.

The 45 item cases include mixed-metadata bow and pickaxe profiles in both
containers. Cross-container moves and deletion/recreation select these profiles;
their typed NBT is checked after each operation. The real-client profile uses
the same cases with three required connections.

Cross-container moves use items with different IDs or counts. The worker checks
the exact occupied slots and typed item NBT after each move, deletion and
recreation, with five intermediate-state checks per player. Extra slots, lost
items and changed untouched metadata fail immediately, before a later operation
could hide the error. These assertions also apply to the real-client profile.

These synthetic player envelopes cover the editor's service operations.
Client login and engine player persistence require the separate real-client
profile.

## Controlled add-on suite

`--suite addons` installs an owned conformance pack with two new namespaced items:
a stackable item with maximum 32 and a durable item with maximum 9000. No Vanilla
definition is overridden. With the editor catalog kept Vanilla, the test preserves
and decorates engine-created custom items, including damage beyond ordinary
Vanilla limits, through two engine reloads. New custom items without originals
must still be rejected. This is **not certification of arbitrary third-party
packs**, pack combinations, overrides or migrations.

## Real-client Inventory/Ender Chest suite

`--suite client --client-port 19134 --timeout 900` requires three real client
connections to **127.0.0.1:19134**, using the same account each time. The runner
always creates a fresh disposable world. The server stops after each observation,
so disconnects are expected. Wait for `client-status.json` to say
`waiting_for_client` before each join; do not change items while connected.

The first connection seeds both actual player containers. After a clean server
stop, the offline worker discovers exactly one persisted player, checks the seed
NBT, and performs the same production-service operations described above. Two
more joins after server restarts observe the stored items without reconstructing
them. Independent disk checks follow each save, including untouched controls and
the exact occupied slot set. A timeout, missing connection or partial cycle is a
failure, never a green result.

BDS also stores account-to-player index records under `player_` keys. Discovery
excludes only the observed index schema (exactly two string fields, `MsaId` and
`ServerId`); ambiguous or unreadable player-like records still fail. Index records
are preserved byte for byte alongside every other unrelated database record.

This profile explicitly enables the Beta APIs experiment and
`@minecraft/server` **2.11.0-beta**, because the
[Ender Chest component](https://learn.microsoft.com/en-us/minecraft/creator/scriptapi/minecraft/server/entityenderinventorycomponent?view=minecraft-bedrock-experimental)
is experimental. It uses no simulated player. The report records this different
API/experiment/network profile. Current clients require NetherNet: local
HTTP/TCP signaling on the selected port plus UDP gameplay on that same port.
The generated `server-udp-ports` explicitly advertises the loopback mapping;
Docker publishes both protocols **only on IPv4 loopback**. See the official BDS
archive's `bedrock_server_how_to.html`, Transport and UDP port configuration.
No LAN
binding, public tunnel, firewall change or online-mode server is created. The
bridge profile does not provide the automated profiles' outbound network isolation.

Player record keys, account names/XUIDs in BDS logs, backups and the generated
world stay private in the ignored run directory. Never share raw client logs or
`private-player-key.json`; only the allowlisted summary is suitable for deliberate
publication. Real-client results cover dedicated-server Inventory/Ender Chest
persistence, not actual singleplayer `~local_player` saves, online authentication
or UI editing flows. A Windows client may require its documented local-loopback
access; the runner does not change system networking permissions.

## Specialized item editors and manual gameplay checks

The `special` suite submits real `special_edit` payloads through the production
item builder, codec, backup and WAL path. It uses the same disposable carriers
and two engine save/reload cycles as the item suite, with an additional edit
between those cycles. The deterministic cases cover:

- Bundles with maximal stacks of 64, 16 and 1; a mixed load increasing from 63
  to 64 weight units; an inner bundle including its four-unit overhead; empty,
  filled and cleared contents, including slot 63 and a colored bundle.
- All 27 shulker slots, a colored shulker containing a bundle with a book, and
  a named, enchanted, damaged sword. The second edit moves existing children,
  changes their metadata and edits the nested book. Origins bind to stored
  slots, not an assumed list order; unknown child tags stay with their origin.
- Writable and signed books with Unicode, newlines, empty pages, a 256-character
  page and 50 pages; page reordering, editing and removal; title and author.
  The signed reference uses the documented
  [Book component](https://learn.microsoft.com/en-us/minecraft/creator/scriptapi/minecraft/server/itembookcomponent?view=minecraft-bedrock-stable)
  to sign an engine-created writable book. It does not invent a creatable
  written-book registry entry. A missing component fails the profile.
- Banner base colors and six ordered patterns, including complex motifs;
  reordering and clearing patterns.
- Rocket flight durations, seven effects spanning all five shapes, colors,
  fade colors, trail and flicker; effect removal and a firework star color change.

After the first reload, selected cases are edited and the controls remain
byte-preserved by the editor. An independent typed-NBT oracle checks the saved contents immediately
after each editor write and each clean engine stop. It checks nested counts,
IDs, metadata, occupied slots and bundle weight, as well as the specialized
fields above. Unexpected/duplicate slots, missing contents, wrong tag types and
changed values fail the run. The existing Script API observation independently
checks each outer item's identity, count, name, lore, damage and enchantments;
it does not observe the specialized contents in memory. Explicit empty slots
and omitted default-valued fields are accepted only where the oracle defines
their equivalent representation.

Separate editor rejection checks cover overstacked children, out-of-range
and duplicate slots, shulkers inside shulkers/bundles, excess bundle capacity and
nested-bundle overhead. Rejections must leave the original unchanged. These
checks validate editor guards, not engine gameplay rejection behavior. Required
stack limits must agree with both the engine measurement and the curated catalog;
missing prerequisites fail rather than silently reducing coverage.
The offline-worker boundary also requires a successful result status and the
exact planned case count; a zero process exit code alone does not pass a phase.

Disk persistence does not establish that a client opens, places or uses the
special items correctly. The profile does not exhaust every color, metadata
combination, legacy/add-on schema or actual player/Ender Chest flow with special
items.

`tests/test_special_items.py` checks the production writer's typed NBT,
preservation, bounds and nested edits with synthetic data. The frontend and
browser tests check isolated drafts, direct container-search entry, cancel,
Undo/Redo and editing gates. These checks can run without Minecraft; they cannot
prove that a client opens or uses the resulting items correctly.
`tests/test_engine_special.py` also injects corrupted results to verify that
the harness detects failures; these synthetic unit checks are not BDS evidence.

Use a **separate disposable world** for the following manual checks. Do not
modify an automated or real-client profile's world during its run: those
profiles require their exact fixture contents. Record the Bedrock client/server
version, editor revision and expected changes with the result.

1. In Minecraft, prepare a shulker and a bundle with known item counts, including
   a named or enchanted item, and keep an untouched comparison item. Include a
   bundle inside the shulker and an item in the Ender Chest. Save and fully stop
   Minecraft/the server before opening the world in the editor.
2. Find a contained item through the inventory search and edit it. Cancel once
   and confirm that no change or Undo entry remains. Repeat, accept through the
   containing editors, and check Undo/Redo before saving the intended edit.
   Record the expected counts, locations and metadata.
3. Close the editor, start the same world in Minecraft and open each container.
   Check the nested contents, take items out and put them back, and compare
   counts, names, enchantments and the untouched control. For the shulker, also
   place, open and recover it. Check that nothing unexpectedly disappears or
   duplicates.
4. Save and fully stop the game/server, reload the world in the editor, then
   repeat the client inspection after another clean save/reload. The expected
   contents must survive both game interaction and persistence.

For the other specialized editors, read all changed book pages and check the
title/author; place and recover a banner to inspect its base color and pattern
order; launch a separate test copy of an edited firework to inspect its flight
and effects, and inspect the edited star's color. Keep these observations
separate from automated pass counts. A missing real client or unperformed step
must remain an explicit coverage gap.

With **BDS 1.26.52.3** and Windows Bedrock **1.26.5203.0**, clicking into a blank
page and closing a writable book can persist that page and preceding blank
pages without typing. This behavior also occurs with Minecraft-created books.
The displayed page total alone does not establish the stored page count;
compare actual page contents and counts. The editor preserves existing blank
pages until explicitly removed, and the engine checks require the requested
page count, text and order, including blank pages.

## Verified builds

The automated and real-client profiles have been exercised with **BDS 1.26.52.3**
and the editor's development version. Each local report identifies the tested
editor revision and source hashes. Coverage is limited to the cases and operations
described above; reports, screenshots and logs remain local.
The provenance of reviewed catalog values is documented in
[item-stack-limits.md](item-stack-limits.md).

## Local use

Use the project's existing development environment and Docker with Linux amd64
containers. Build the optional developer host image once:

```powershell
docker build -t mcbe-engine-check:local scripts/engine_checks
```

Place an official Linux server ZIP in `.engine-tests/downloads/`, record its
SHA-256 and pass the actual server version (which may differ from the client
version or `bedrock-samples` release):

```powershell
$archive = '.engine-tests/downloads/bedrock-server-1.26.52.3.zip'
$digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash
.venv/Scripts/python.exe -m scripts.engine_checks --archive $archive --sha256 $digest --server-version 1.26.52.3
```

The default `--suite all` sequentially runs `extended`, `special`, `service` and `addons`,
each in a separate fresh world and with its own report. A failure/partial result
in any suite stays failed/partial in the aggregate process exit code. Use
`--suite special` to focus on specialized editor persistence, `--suite items`
for the smaller base NBT suite or `--suite catalog` for registry
and component measurements only. `--suite client` is a separate, interactive
opt-in. `--timeout 300` bounds each engine phase; shutdown has a shorter
deadline. Missing Docker/BDS is an error, never a substituted mock engine.

To review changed limits, copy the bundled item database into an ignored
directory, update only the proposed facts, then pass `--catalog PATH`. The worker
treats this snapshot as its prospective bundled database; normal application
curation would otherwise restore the old bundled values. The production loader,
item builder and validators remain unchanged, and the worker checks the exact
loaded limits against the measurement snapshot. Reports distinguish candidate
from bundled catalogs. Promote reviewed facts separately, then rerun with the
bundled catalog. The tool never modifies it automatically.

The new run directory contains detailed `run.json`, local logs, backups and the
disposable world. `summary.json` is an allowlisted artifact for deliberate sharing:
it contains no raw NBT, logs, local paths or exception messages. Keep all reports
ignored by default. Unit tests in `tests/test_engine_checks.py` exercise failure
detection and the production NBT adapter; they are not Minecraft-run evidence.
The whole output directory must be Git-ignored when it is inside the repository;
ignoring only JSON reports is insufficient. The offline worker rejects world or
database links/junctions that could redirect it outside the disposable run.
JSON status, configuration and report files are published atomically; a failed
write leaves the previous complete file intact for concurrent status readers.

Exit codes: **0** = selected suite passed, **2** = incomplete catalog coverage,
**1** = mismatch, malformed/incomplete output or execution failure. Downstream
tools must preserve failed/partial status. Limit candidates require review.

## Updates and releases

Run the default automated suites for each supported new Bedrock build and after inventory
serialization/write changes. Compare reports, retain the exact engine archive
locally, then promote reviewed item facts with their provenance. Results are
specific to a build and profile, never proof for arbitrary worlds or versions.
The optional manually dispatched `Engine checks` workflow runs the same suite
and uploads only the allowlisted summary. It publishes no application release.

Also run the real-client profile when testing actual player persistence. Mount
gameplay, singleplayer persistence and version migrations are not covered by
these suites.
Regression tests deliberately inject lost metadata, wrong counts/variants,
duplicate/missing slots and observations to verify that observers reject them.
Finite passing tests provide scoped evidence, not universal proof.
