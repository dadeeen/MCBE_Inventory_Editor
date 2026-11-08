# Checks against the Bedrock engine

The tools under `scripts/engine_checks/` validate editor output against Bedrock
Dedicated Server (BDS). They use disposable worlds and are excluded from runtime
ZIPs and the application Docker image. Supply an official BDS archive locally;
the runner does not download it or accept existing worlds. Keep binaries, worlds,
reports, backups and logs in the ignored `.engine-tests/` directory.

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
selected `client` and `village` profiles enable a bridge network with IPv4-loopback
TCP and UDP publications; neither is selected by CI or `--suite all`.
Neither these server settings nor the disposable world are deployment examples.

The exact four-part version must match BDS's own startup log. The report records
server archive/executable SHA-256, immutable local image ID, API dependency,
editor commit/dirty state, probe/editor source hashes, catalog hash and case hash.
Changed probe or editor sources at completion fail the run; rerun after edits
have finished. Hashes identify inputs; they do not attest a user-supplied binary's authenticity. Obtain
the archive directly from [Mojang](https://www.minecraft.net/en-us/download/server/bedrock).

The Vanilla script-only behavior pack does not redefine items or entities. It uses the
stable `@minecraft/server` 2.9.0 API (Bedrock 26.50 or compatible newer builds),
without GameTest/Beta experiments. The item and villager suites wait for
[TickingAreaManager](https://learn.microsoft.com/en-us/minecraft/creator/scriptapi/minecraft/server/tickingareamanager?view=minecraft-bedrock-stable)
to load their chunks and actors even without a connected player. References:
[BDS scripting](https://learn.microsoft.com/en-us/minecraft/creator/documents/bedrockserver/scripting?view=minecraft-bedrock-stable),
[ItemTypes](https://learn.microsoft.com/en-us/minecraft/creator/scriptapi/minecraft/server/itemtypes?view=minecraft-bedrock-stable),
[ItemStack](https://learn.microsoft.com/en-us/minecraft/creator/scriptapi/minecraft/server/itemstack?view=minecraft-bedrock-stable).

## Verified builds

### Item and player reference

The automated reference build is **BDS 1.26.60.6** for Linux amd64. Its official
archive SHA-256 is `cbbd5414fa6a310353ed1fc76a0ba691c3fd1ea852fd04bb76764ee4c1afdb98`;
the executable SHA-256 is `ea16b541a448e07c337848d2c5f37321b706554b5216dd942f3f11e7a8ed2bad`.
The editor 0.8.4 catalog SHA-256 is
`c3d11c43d2e035c629a846872fffc98015d9f04c3062b100c2c3d618379fc192`.
The measured registry contains exactly the catalog's 1,623 addable IDs, with all
recorded stack limits and 84 durability components agreeing. The stable sample
source remains **v1.26.50.4**; engine-reviewed potion/effect facts have their own
provenance and do not change that release identity.

The extended profile passes **13,312** item cases through two engine save/reload
cycles, including **441** potion cases (49 types, three delivery types, creation,
preservation and display-field edits). It also verifies 42 enchantment identities
and maximum levels, 68,166 applicability checks, 1,648 stack-merge pairs and six
bounded item-transport cases. Its probe source SHA-256 is
`fe76e8f9f7a25652c85e74c5cd485b715a734e2734044fc75a28ed7de0e33dad`;
the editor source SHA-256 is
`908051fe2c1a7682764af13ba85d13c707d145bc00cd89473e14e76f962fe610`.

The four profiles below pass with those source and catalog hashes:

| Profile | Cases | Scope |
| --- | ---: | --- |
| `extended` | 13,312 | Item creation, preservation, metadata, variants, enchantments and bounded transport |
| `special` | 18 | Six specialized item editors, 14 second edits and 15 rejected edits |
| `service` | 48 | Production player service with two synthetic player formats, backups and revision checks |
| `addons` | 12 | Owned conformance pack with two custom item types; no Vanilla catalog overrides |

Each listed profile checks two engine save/reload cycles. Synthetic player records do
not establish real-client Inventory or Ender Chest persistence.

The optional real-client profile uses stable API 2.11.0 and requires its own
client-connected run. That API loads successfully in network-isolated BDS
1.26.60.6 and exposes `EntityComponentTypes.EnderInventory` as
`minecraft:ender_inventory` without experiments. This API-availability check and
the automated profiles do not establish actual client login,
singleplayer persistence, version migration or experimental Freezing gameplay.

### Villager reference

With **editor 0.8.8** and **BDS 1.26.61.1** for Linux amd64, the `villagers`
profile passes all 24 resident cases: 23 backed-up saves, 44 byte-preserving
no-op checks and 23 stale-revision rejections. The second edit round stages all
22 signed previews through the central workspace API and commits them in one
backed-up batch. Two engine-only warmup reloads
precede the writes; two reloads after each edit round verify names, health and supplies
through four post-edit save/reload cycles. The catalog measurement agrees on all
1,623 addable IDs, recorded stack limits and durability values. These results
apply to the following inputs:

| Input | SHA-256 |
| --- | --- |
| Official BDS archive | `b54095267d55fd401de42f71ac4daf2c1747a49515ad41810781f1f9bafde26e` |
| BDS executable | `d75212f20511eac3e3a1a45c5b57646d697a33038d5e41fa92113e1fbc14efab` |
| Editor source | `6687bfbbf6539805209d32561c2ad7afa358fbaf36beae0b8d7c471ff17bcfbe` |
| Probe source | `b38bb9626f890162cf0122f6cce2aa1761121672b1c90c6b00a2ab8291c2b48a` |
| Item catalog | `b37bdbe81a6e16d6fedf6b0db9d3827b9e2ede59f370af79edc1b525e6b38902` |
| Villager cases | `b3d2f2bc80b1c5960dd8d8f97ca56601034db723e031ce509efd617eb7c89224` |

This reference covers the explicit name, health and supply cases, including compact
native health attributes. Gameplay, client interactions, legacy schemas,
version migration and arbitrary add-ons remain outside its coverage.

## Catalog suite

- Compare every bundled addable ID with the runtime registry and try every ID in
  their union. Record `ItemStack.maxAmount`, exposed components and durability.
- Compare every recorded stack limit with the engine measurement. Contradictions
  fail. Missing catalog limits produce review candidates and a partial result.
  Values above the editor's Count range also fail.
- Compare recorded durability with `ItemDurabilityComponent.maxDurability`,
  including disappeared components. New durable items require review and produce
  a partial result; conflicting known values fail before any offline edits.
- Failed item construction leaves the limit unverified; it receives no default
  of 1 or 64. Partial coverage returns exit code 2. Catalog changes require review.

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
- All 49 potion types across all three runtime delivery types. The editor creates
  each measured numeric variant and preserves or renames engine-created references,
  with raw NBT data values checked against an independent reviewed table. On
  BDS 1.26.60.6, `freezing` and `long_freezing` persist as short-tag data values
  47 and 48. Their registration and persistence without experiments do not
  establish normal gameplay availability; the 26.60 changelog lists Freezing
  among experimental game-drop features.
- Real `isStackableWith` checks in both directions and `Container.addItem` calls
  for all item types, plus equal/different names, lore and durability. Engine-built
  references provide the comparison. Quantity conservation, stack boundaries,
  full-container remainders and unchanged sources are checked explicitly.
- Hopper transfers and dropped-item collection for a named item, an enchanted
  item and a potion. The item metadata must survive without duplication. Drop
  fixtures use [Entity.clearVelocity](https://learn.microsoft.com/en-us/minecraft/creator/scriptapi/minecraft/server/entity?view=minecraft-bedrock-stable#clearvelocity)
  immediately after spawning: uncontrolled initial motion otherwise lets items
  miss the hopper, producing intermittent fixture failures.

Coverage is limited to the listed pairs, profiles and metadata cases. Combat,
equipping, consumption, brewing and crafting are outside this suite. The editor
permits some NBT enchantment pairs that Vanilla application rules reject;
measured rejection does not restrict preserved or editable NBT.

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

The 48 item cases include mixed-metadata bow and pickaxe profiles in both
containers, a bundle at weight 63, a nested shulker/bundle/book and an
engine-signed book with Unicode, blank and long pages. The special edits pass
through the production player service. Independent typed-NBT checks verify the
contents before intermediate results are frozen, and again after each engine
save. This checks persisted contents, not opening or using the items.

Cross-container moves and deletion/recreation select the mixed-metadata profiles;
their typed NBT is checked after each operation. The real-client profile uses
the same 48 container cases plus five equipment cases, with three connections by
default. Equipment cases do not consume the container fixture's slot budget.

Cross-container moves use items with different IDs or counts. The worker checks
the exact occupied slots and typed item NBT after each move, deletion and
recreation, with five intermediate-state checks per player. Extra slots, lost
items and changed untouched metadata fail immediately, before a later operation
could hide the error. These assertions also apply to the real-client profile.

These synthetic player envelopes cover the editor's service operations.
Client login and engine player persistence require the separate real-client
profile.

## Villager health and supply suite

`--suite villagers` creates real Vanilla villagers in a disposable world. Each
resident occupies a separate enclosure without a bed, workstation or farm;
mob griefing is disabled. The fixture isolates persistence from food sharing,
breeding and farming. An untouched resident provides a control. The script pack
does not override entity definitions or construct synthetic villager NBT.

Two engine-only reloads precede editor writes. BDS can initialize fields in
freshly generated trade offers during the first reload. The observer records
that transition before any editor write and fixes the resulting `Offers`
baseline. The second reload must preserve it exactly. Every later comparison
uses the same complete baseline; trade fields are not discarded or normalized
by the observer.

After a clean engine stop, a separate offline worker calls the production
villager scan, preview and save service. The matrix contains 24 residents:
one untouched control, nine health cases, ten supply cases and four name cases. Health cases
cover setting current health, healing, fractional health, the maximum of 2048,
changing only the maximum, reducing it with the corresponding current-health
bound and a two-resident batch. Supply cases cover all ten supported Vanilla item types,
first and last slots, counts 1 and 64, replacement and explicit clearing.
Unchanged supply slots remain controls. Name cases cover assigning, renaming,
removing and restoring names, Unicode and the editor limit of 80 code points.
Stable test tags identify residents independently of their editable names;
these tags are assigned after native actor conversion during seeding. All
groups include a second edit round, with two clean engine save/reload cycles after each round.

The live Script API independently observes `nameTag`, `currentValue`,
`effectiveMax` and all eight inventory slots. A typed-NBT observer checks
persisted names, health and supplies after every editor write and engine stop, including compact health
attributes that omit `Current` or `Max`. The saved actor identity and chunk
references must remain consistent. Every editor write must preserve other
database records and unrelated actor fields byte for byte. Stable profession,
trade and equipment fields remain checked across engine reloads. Backups,
no-op saves and stale revision rejection are also part of the service checks.
The first round checks each edit through the villager service. The second round
checks signed preview staging and one atomic central workspace save, followed
by replay rejection and two native engine reloads.

Missing actors, unsupported health representations, omitted observations,
changed control data and incomplete phases fail the suite. A successful run
requires the complete planned name, health and supply matrix; skipping unsupported
health writes cannot produce a passing result. The local report records the
engine version and input hashes, and the public summary contains only
allowlisted counters and status fields.

These checks establish the selected Vanilla villagers' saved values and
engine-visible state. They do not establish trade interactions, breeding,
sharing, farming, damage gameplay, client visuals, legacy-world compatibility
or arbitrary add-on behavior. Regression tests in
`tests/test_engine_villagers.py` check the observers with deliberately corrupted
observations and NBT; those synthetic tests are not evidence of a BDS run.

## Natural village and real-client gameplay suite

`--suite village --client-port 19134 --timeout 1800` uses the existing real-client
server lifecycle with three required joins to **127.0.0.1:19134**. It creates a
fresh normal world with seed `9172026`, using naturally generated villagers,
beds and workstations around `(-232, 67, 840)`. The village coordinates and
landmarks are measured in **BDS 1.26.61.1**. The complete profile is verified with
that BDS version in Docker and Windows Bedrock client **1.26.6301.0**: three
client connections, three bread trades and food pickups, two server reloads,
three demonstrated chunk unload/reload cycles and two backed-up production saves.
The final saved state preserves edited health and supplies and the original
resident and player identities.

A separate damage check with **BDS 1.26.61.1** uses a disposable village copy:
`Entity.applyDamage(25)` kills the unchanged resident with 20 health, while the
resident edited to 40 survives with 15/40. Native hurt/death events and saved
NBT confirm the health values. This check needs no client and covers health
capacity, excluding weapon-specific damage, armor, effects and combat AI.

The script records three natural adults' identities, names and positions, then
moves them into separate glass booths with composters. The booth footprint must
be empty. The enclosures prevent farming and food sharing from changing supplies
between edits and observations; reloads retain the booths and the same actors.

After the first client joins, native job assignment can take up to two minutes.
The script selects a farmer, an injured resident and an untouched control, names
their roles, sets the initial injury and supplies the player's emeralds and
carrots. A missing farmer or unsettled control fails preparation. Villagers,
professions and trade results come from the engine.

The observer places the player beside the selected farmer; the client performs
the actions. Placement requires clear interior blocks above the booth's stone
floor. Integer block checks handle actors standing at fractional heights or on
composters without the experimental `Block.isSolid` property. A missing safe
position fails the phase.

Wait for each numbered join invitation in the console or `client-status.json`.
The initial invitation requires the natural residents and their booths to be ready.
During each of the three connections:

1. Wait for `trade_required`, buy bread once from `MCBE_village_farmer` with
   emeralds, then close the trading screen.
2. Wait for `pickup_required`. The observer selects the player's carrot slot;
   drop one carrot with **Q** in front of that farmer and wait for its pickup.
3. Wait while the observer moves away to unload the village chunks, returns and
   checks the same residents. The server then saves and disconnects the client.

After the first clean stop, the production villager scan, preview and save
service performs two backed-up edits: the injured resident receives maximum
health 40 and full healing, and the farmer's eight supply slots become four
carrots in slot 0 with the other slots empty. The second and third joins check
the edits and repeat the real gameplay actions. Reload phases never replenish
the player's resources or repair the villagers' saved health or supplies.
Both server reloads and all three chunk unload/reload observations are required;
`--client-reloads` does not shorten this profile.

The observers require all of the following:

- A trade must trigger interaction with the selected farmer, consume one emerald
  and yield six bread after the trading screen returns its input items. Saved
  `TradeExperience` must increase by the recipe's positive `traderExp`, with the
  recipe unchanged. `Offers` usage may increase by at most one; native restocking
  may reset it.
- Carrot pickup must match the freshly dropped item entity, its native
  before-pickup event and the inventory changes in saved NBT. BDS 1.26.61.1
  supplies no corresponding after-pickup event.
- Saved actor and player identities, health, supplies and backups must match the
  expected state. All eight edited slots are checked before restart. Comparison
  residents may change professions through native AI, but their saved inventories
  must match the last live observation. The farmer's carrot total, health,
  identity and profession remain exact. Offline edits preserve profession data
  byte for byte.
- The world seed must match, and `Dimension.isChunkLoaded()` must report a
  loaded, unloaded and reloaded state for residents and landmarks. The temporary
  ticking area is removed before moving away; every observed chunk must unload
  before it is recreated on return.

Missing actions, observations or disk checks and timeouts fail the suite.
`tests/test_engine_village.py` and `tests/test_engine_village_orchestration.py`
check these failure paths with corrupted observations.

This interactive profile uses stable `@minecraft/server` **2.11.0**, without
experiments, and the same loopback-only NetherNet configuration and private
runtime-data rules as `--suite client`. It is excluded from `--suite all` and
unattended CI. World data, account-bearing logs, `village-state.json` and detailed
actor observations stay in the ignored run directory; only the allowlisted
summary exposes status and counts. The runner does not automate client menus.

The profile covers the selected bread trade, dropped-food pickup and health and
supply edits. Farming, breeding, food sharing, restocking, combat, other village
biomes, legacy worlds and arbitrary add-ons remain outside its scope.

## Controlled add-on suite

`--suite addons` installs an owned conformance pack with two new namespaced items:
a stackable item with maximum 32 and a durable item with maximum 9000. No Vanilla
definition is overridden. With the editor catalog kept Vanilla, the test preserves
and decorates engine-created custom items, including damage beyond ordinary
Vanilla limits, through two engine reloads. New custom items without originals
must still be rejected. Third-party packs, pack combinations, overrides and
migrations are outside this suite.

## Real-client Inventory, Ender Chest and equipment suite

`--suite client --client-port 19134 --timeout 900` defaults to three real client
connections to **127.0.0.1:19134**, using the same account each time. The runner
always creates a fresh disposable world. The server stops after each observation,
so disconnects are expected. The console announces each ready join, detects the
connection and explains the intentional save/disconnect and offline edit. Wait
for **`Join 1/3 ready`**, then the next numbered invitation; do not change items
while connected. The same progress is atomically available in
`client-status.json`, including phase, connection number, required connections,
address and port. World preparation/catalog measurement needs no join.

The first connection seeds both actual player containers and equipment. After a clean server
stop, the offline worker discovers exactly one persisted player, checks the seed
NBT, and performs the same production-service operations described above. Two
more joins after server restarts observe the stored items without reconstructing
them. Independent disk checks follow each save, including untouched controls and
the exact occupied slot set. A timeout, missing connection or partial cycle is a
failure, never a green result.

All **53 cases share those same three joins**. The five equipment cases preserve
a helmet, decorate a chestplate (damage, Unicode name/lore and Unbreaking III),
clear leggings, create boots in an empty slot and decorate a shield in Offhand.
Writes use the production service's explicit root-equipment edit gate. The
Script API observes the actual equipped items; the independent disk observer
checks dense Armor/Offhand lists, slot order, typed fields and empty positions.
The editor must preserve other player fields, unrelated database records,
untouched equipment and an optional fifth Armor entry byte for byte. An
additional no-op must create neither writes nor a backup. This proves the tested
equipment persistence, not armor protection, shield blocking or client visuals.

For a quicker development check, add **`--client-reloads 1`**. It uses two joins:
seed, offline edit, then one real-client load/save followed by the independent
disk check. The default **`--client-reloads 2`** additionally checks the next
client load after that engine save. The shorter result explicitly records one
cycle, two required connections and the missing second reload in `not_covered`;
it is not the full three-join result. This option is accepted only with
`--suite client`. Neither mode automates the Minecraft menu or reuses old worlds.

The public summary reports the selected/finished connection count and the
roundtrip cycle count. `player_service.special_content_cases` counts the three
selected special cases; `equipment` summarizes the offline equipment edit and
no-op checks. The overall client result also requires all matching engine case
events and independent disk checks for every selected reload.

BDS also stores account-to-player index records under `player_` keys. Discovery
excludes only the observed index schema (exactly two string fields, `MsaId` and
`ServerId`); ambiguous or unreadable player-like records still fail. Index records
are preserved byte for byte alongside every other unrelated database record.

This profile requires Bedrock **26.60** or later and the stable
`@minecraft/server` **2.11.0** API, including the
[Ender Chest component](https://learn.microsoft.com/en-us/minecraft/creator/scriptapi/minecraft/server/entityenderinventorycomponent?view=minecraft-bedrock-stable).
It enables no experiments and uses no simulated player. The report records this
API/network profile. Current clients require NetherNet: local
HTTP/TCP signaling on the selected port plus UDP gameplay on that same port.
The generated `server-udp-ports` explicitly advertises the loopback mapping;
Docker publishes both protocols **only on IPv4 loopback**. See the official BDS
archive's `bedrock_server_how_to.html`, Transport and UDP port configuration.
No LAN binding, public tunnel, firewall change or online-mode server is created. The
bridge profile does not provide the automated profiles' outbound network isolation.

Player record keys, account names/XUIDs in BDS logs, backups and the generated
world stay private in the ignored run directory. Never share raw client logs or
`private-player-key.json`; only the allowlisted summary is suitable for deliberate
publication. Real-client results cover the selected dedicated-server Inventory,
Ender Chest, special-content and Armor/Offhand persistence cases, not actual
singleplayer `~local_player` saves, online authentication or UI editing flows.
Special contents are observed on disk; opening, placing, reading and using them
remain separate gameplay checks. A Windows client may require its documented local-loopback
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
  reordering and clearing patterns; the fixed ominous banner type.
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
`tests/test_engine_special.py` checks failure detection with corrupted results.
Signed-book fixtures include the engine-owned signing metadata, which the editor
preserves.

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

## Validation scope

Synthetic regressions check the offline workers, observers and orchestration.
Engine validation requires a successful BDS/client run identified by editor
revision, source hashes and profile. Reports, screenshots and logs remain local.
Reviewed catalog values have separate [source records](item-stack-limits.md).

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
$archive = '.engine-tests/downloads/bedrock-server-1.26.60.6.zip'
$digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash
.venv/Scripts/python.exe -m scripts.engine_checks --archive $archive --sha256 $digest --server-version 1.26.60.6
```

The default `--suite all` sequentially runs `extended`, `special`, `service`,
`addons` and `villagers`,
each in a separate fresh world and with its own report. A failure/partial result
in any suite stays failed/partial in the aggregate process exit code. Use
`--suite villagers` to focus on villager health and supply persistence,
`--suite special` for specialized item editors, `--suite items`
for the smaller base NBT suite or `--suite catalog` for registry
and component measurements only. `--suite client` and `--suite village` are
separate interactive opt-ins. `--timeout 300` bounds each engine phase; shutdown has a shorter
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

Run the default automated suites for each supported new Bedrock build and after
inventory or villager serialization/write changes. Compare reports, retain the exact engine archive
locally, then promote reviewed item facts with their provenance. Results are
specific to a build and profile, never proof for arbitrary worlds or versions.
The optional manually dispatched `Engine checks` workflow runs the same suite
and uploads only the allowlisted summary. It publishes no application release.

Also run the real-client inventory profile when testing actual player persistence
and the natural village profile for its selected villager gameplay actions. Mount
gameplay, singleplayer persistence and version migrations are not covered by these
suites.
Regression tests inject lost metadata, wrong counts/variants,
duplicate/missing slots and observations to verify that observers reject them.
