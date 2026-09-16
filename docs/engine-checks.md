# Checks against the Bedrock engine

The reusable tools under `scripts/engine_checks/` belong in the public source
repository. They are developer tools, excluded from the runtime release ZIP and
application Docker image. Mojang's binaries, generated playable worlds, local
reports, backups and logs belong in the ignored `.engine-tests/` directory.
Nothing under that directory should be committed. No real world is required or
accepted by the runner. The local tool does not download or redistribute BDS.

## Execution and provenance

`python -m scripts.engine_checks` runs an explicitly supplied **official Linux
Bedrock Dedicated Server** in Docker with no network, no published ports, dropped
Linux capabilities, a read-only container root and one writable mount containing
a fresh disposable server. A timeout bounds each phase; only its own container
is removed. Docker must already be running. Host firewall settings and existing
containers are not changed. Linux runs as the host UID/GID; Windows bind mounts
use container UID 0 with the same capability and filesystem restrictions.
The generated server uses offline mode and RakNet solely to start its script
runtime without network services. Some BDS builds print a RakNet transport error;
client connections are outside this profile and impossible with `--network none`.
Neither these server settings nor the disposable world are deployment examples.

The exact four-part version must match BDS's own startup log. The report records
server archive/executable SHA-256, immutable local image ID, API dependency,
editor commit/dirty state, probe source hash, catalog hash and case hash. Hashes
identify inputs; they do not attest a user-supplied binary's authenticity. Obtain
the archive directly from [Mojang](https://www.minecraft.net/en-us/download/server/bedrock).

The script-only behavior pack does not redefine items or entities. It uses the
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
  fail. Missing catalog limits produce review candidates, never automatic catalog
  changes. Values above the editor's Count range also fail.
- Failed item construction remains unverified. No implicit 1 or 64 is invented.
  Partial coverage returns exit code 2, not a green result.

## Item suite (default)

The engine creates named chest minecarts as test carriers. Each contains an
untouched control item and assigned cases: new amount-1 items for every measurable
bundled ID; preservation of existing engine-created maximal stacks; new maximum
and maximum-minus-one stacks where our recorded limit agrees; selected Unicode
names, lore and near-broken durability cases. Existing maximal stacks also cover
IDs whose measured catalog limits have not yet been promoted.

The server stops cleanly before the offline worker opens LevelDB. A small carrier
adapter uses the **production item builder, Bedrock codec, backup creation and
native write batch**. It verifies preserved/control items byte for byte and every
unrelated database record. Two engine reload/save cycles follow. The script only
observes stored items in those phases; it never reconstructs them. Engine-visible
semantics and saved NBT counts are checked after each cycle. Constructor clamping
is checked during seeding too. Negative cases require the production builder to
reject new amounts -1, 0, maximum + 1 and 128 for every tested ID.

This does **not** exercise the complete player service, player login, singleplayer
`~local_player`, Ender Chest storage, UI, mount creation, gameplay interactions,
arbitrary add-ons, Education-only behavior, version migration or every metadata
combination. Every report lists these gaps. Item-type maxima do not prove that
two customized stacks can merge. Unknown changes are not silently accepted.

## First verified build

On 2026-09-16, the complete item suite passed against **BDS 1.26.50.5**:
1,623 registry IDs, 6,040 item cases in 233 generated carriers, two engine
save/reload cycles, and 6,492 rejected invalid creation amounts. There were no
registry differences or unresolved limits with the reviewed candidate catalog.
The bundled catalog now contains that exact tested snapshot. The measured
values and archive/catalog hashes are documented in [item-stack-limits.md](item-stack-limits.md).
This was a local Docker run; the manual GitHub workflow has not yet been run.
The scope exclusions above still apply.

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
$archive = '.engine-tests/downloads/bedrock-server-1.26.50.5.zip'
$digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash
.venv/Scripts/python.exe -m scripts.engine_checks --archive $archive --sha256 $digest --server-version 1.26.50.5
```

`--suite catalog` measures only the registry/components. Default `items` adds NBT
persistence. `--timeout 300` bounds each engine phase; shutdown has a shorter
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

Exit codes: **0** = selected suite passed, **2** = incomplete catalog coverage,
**1** = mismatch, malformed/incomplete output or execution failure. Downstream
tools must preserve failed/partial status. Limit candidates require review.

## Updates and releases

Run the item suite for each supported new Bedrock build and after inventory
serialization/write changes. Compare reports, retain the exact engine archive
locally, then promote reviewed item facts with their provenance. Results are
specific to a build and profile, never proof for arbitrary worlds or versions.
The optional manually dispatched `Engine checks` workflow runs the same suite
and uploads only the allowlisted summary. It publishes no application release.

Further suites can cover enchantment combinations, variants, player login and
persistence, mount gameplay and migrations. Before using a suite as a release
gate, demonstrate that its observer catches deliberately injected data loss and
clamping. Finite passing tests provide scoped evidence, not universal proof.
