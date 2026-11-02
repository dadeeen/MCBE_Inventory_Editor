# Item names and source comparisons

The catalog uses German and English item names from the [Mojang Bedrock samples v1.26.50.4](https://github.com/Mojang/bedrock-samples/releases/tag/v1.26.50.4), with deliberate distinctions for legacy IDs and default data values. Light levels, undyed containers, potion strength/duration and horn sounds retain identifying additions. Potion labels use item terminology rather than the sometimes different effect names. A direct `.name` comparison is a diagnostic, not an instruction to replace every different label.

## Incorrect inherited labels

These inherited pairs describe a tooltip, status message, color or individual pattern rather than the item represented by the catalog entry:

| Item ID (without `minecraft:`) | Inherited German / English | Catalog German / English |
| --- | --- | --- |
| `banner_pattern` | Gemauertes Feld / Field Masoned | Bannermuster / Banner Pattern |
| `fireworks` | Flugdauer: / Flight Duration: | Feuerwerksrakete / Firework Rocket |
| `fireworkscharge` | Schwarz / Black | Feuerwerksstern / Firework Star |
| `netherreactor` | Aktiv! / Active! | Netherreaktorkern / Nether Reactor Core |
| `respawn_anchor` | Wiederbeleben-Punkt festgelegt / Respawn point set | Seelenanker / Respawn Anchor |
| `smithing_template` | Gilt für: / Applies to: | Schmiedevorlage / Smithing Template |

## Intentional differences

| Item ID | Catalog name | Reason |
| --- | --- | --- |
| `minecraft:bed` | Weißes Bett / White Bed | Data value 0 selects the white bed. The source's base name is Bett / Bed; the catalog's variant-aware browser exposes the other colors separately. |
| `minecraft:yellow_flower` | Löwenzahn / Dandelion | This legacy ID has one flower variant. The specific name is more useful than the source's generic Blume / Flower. |
| `minecraft:stonecutter` | Steinsäge (alt, ohne Funktion) / Stonecutter (Legacy, No Function) | The suffix distinguishes the nonfunctional legacy block from `minecraft:stonecutter_block`. |
| `minecraft:light_block_0` … `minecraft:light_block_15` | Lichtblock N / Light Block N | Mojang's shared Hell / Light label does not distinguish light levels. |
| `minecraft:undyed_shulker_box` | Shulker-Kiste (ungefärbt) / Undyed Shulker Box | The addition distinguishes the undyed container from colored variants. |
| `minecraft:petrified_oak_slab` | Versteinerte Eichenstufe / Petrified Oak Slab | The editorial German name preserves the legacy distinction; Mojang's block label is the less specific Holzstufe / Wooden Slab. |

These pairs appear only in the technical log as a flat list of expected name differences in the active UI language. They are absent from the change details and the list of unresolved findings. Classification requires the exact reviewed ID, both catalog names and both source names. Changed or missing labels return to the ordinary comparison; the IDs are not exempt from validation.

## Terminology alignment

The following old names identify the correct object, but the bundled catalog follows the Bedrock source terminology for consistency with in-game search:

- German armor: the four chainmail pieces use Kettenhemd-Stiefel, Kettenhemd-Harnisch, Kettenhemd-Helm and Kettenhemd-Beinschutz. Diamond, gold, iron and netherite torso/leg pieces use Harnisch and Beinschutz instead of Brustplatte and Beinschienen.
- German miscellaneous: Redstone-Komparator → Komparator; Gebratenes Rindfleisch → Steak; Wirrpilzrute → Wirrpilz auf einem Stock.
- English blocks: coal, diamond, emerald, gold, iron, lapis, netherite and redstone use Mojang's “Block of …” wording instead of “… Block” (lapis: Block of Lapis Lazuli).
- English miscellaneous: Redstone Comparator → Comparator; Cooked Beef → Steak; Ender Eye → Eye of Ender; Poplar Standing Sign → Poplar Sign; Redstone → Redstone Dust.

## Shared migration policy

`mcbe_editor/item_name_policy.py` contains the known obsolete pairs, including their English-only fallback form and pairs with a reviewed German name and an inherited English label. Both the runtime and updater take replacement names from the bundled catalog. Both inherited values must match a known pair, except that a literal item ID represents a missing value. Changing one half prevents that historical pair migration. Later translations are compared independently for each language.

The updater applies these repairs before and after resolving localization fallbacks, so a formerly English-only entry can receive both the German name and the corrected English name in one update. Generic fallback translation requires the existing English label to match the source; equal names in both languages alone do not identify an untranslated item. Repeating the update does not repeat the migration. The dry run previews it without writing the persistent database. These catalog repairs do not change an item's custom display name, lore or saved NBT.

## Effects and enchantments

`mcbe_editor/numeric_catalog_policy.py` reconciles reviewed numeric identities for both the updater and runtime loading. Recognized names and identifier aliases migrate obsolete numeric positions; custom names at an existing reviewed ID remain intact. Conflicting names or migration destinations block only the affected section. The updater skips that section; runtime loading preserves the persistent file and records the conflicting IDs without invoking whole-file corruption recovery. Unknown entries outside the reviewed IDs remain intact.

An affected section has no editable runtime identities until its conflict is resolved. Existing effect and enchantment NBT uses the same lossless protection as unknown entries; unrelated edits preserve it verbatim. The remaining catalog sections stay available. Item-DB status and player-load warnings identify the blocked section and IDs. Reloading a repaired catalog restores its editable identities without retaining a stale block.

Effect descriptions use the reviewed German and English texts in the bundled catalog. Enchantment maximum levels use the reviewed Vanilla values; custom enchantment descriptions remain intact. Tests require the bundled enchantment IDs and levels to agree with `enchantment_max_levels.json`, and exercise updater output through the runtime loader. An omitted optional enchantment description and an empty description are equivalent.

Freezing uses the editorial German translation “Gefrieren” and the English name “Freezing”, with explicit experimental labels. BDS 1.26.60.6 engine-created references establish effect ID 38 and potion data values 47 (`freezing`) and 48 (`long_freezing`). The bundled base catalog uses Bedrock samples v1.26.50.4; the reviewed effect survives updates from that older registry. The v1.26.60.5 registry includes the effect without corresponding German or English language-file labels, so the updater retains the reviewed names and records their fallback origin. These labels do not claim an official German translation. The potion variants use the existing base-icon fallback when no matching Vanilla texture key is available.

## Missing source labels

The updater resolves each language separately. A usable Mojang translation takes
priority. Missing labels can come from a source composition, the bundled catalog,
a saved name, a Microsoft Learn identifier, the other language or the item ID.

`mcbe_editor/item_localization.py` follows each item's `serialization_id` and preserves
the distinction between item keys, block keys and variant suffixes. A matching block
reference can supply a name unless the block represents a different object, as with
wheat and beetroot crops. Multiple references must agree in the same language.
Direct references take precedence over matches on an English display name. Conflicting
matches and unresolved localization templates leave that translation open.

IDs known only from Microsoft Learn can use their own `item.<id>.name`. Suffixless
keys require a registry identity or a recognized legacy key. Disc names combine the
record label with the subtitle from that disc's registry reference in the same
language. Potion categories keep their catalog names. The positive item registry
determines which items the editor can add, including items that lack a translation.

### Existing installations

`confirmed_item_labels` records the last automatic name per language. An unchanged
value can receive a later official translation. A local edit keeps its exact spelling,
even if German and English are identical. A missing translation keeps its last known
name. If that name was copied from the other language, the record identifies which
language borrowed it. Skipping the item section preserves these records.

For older catalogs, the previous coverage report can identify a title derived from a
Learn identifier. Other copied names can be recovered when the verification receipt
matches both the catalog and the report. In a catalog with a positive item registry,
equal names alone do not establish that either was copied.

### Name sources

The German and English reference fixtures record inherited names, replacements and
their sources. Bedrock samples v1.26.60.5 supplies *Stein-Doppelstufe* and
*Prismarin-Doppelstufe*. The remaining German replacements in that fixture are
editorial. English labels such as *Heat Block* and *Super Fertilizer* come from
Mojang's documentation. Legacy slab and torch names retain their type or colors
when a source gives only a group name. [German fixtures](../tests/fixtures/reviewed_german_item_names.json) · [English fixtures](../tests/fixtures/reviewed_english_item_names.json) · [Chemistry Lab Journal](https://education.minecraft.net/content/dam/education-edition/software-downloads/Chemistry-Lab-Journal.pdf) · [Bedrock torch names](https://www.minecraft.net/en-us/article/minecraft-1-21-30-bedrock-changelog)

Community terminology informs editorial names such as *Knicklicht*. The German
Frostbite spawn egg keeps the creature's source name because the German Wiki labels
its translation provisional. [Minecraft Wiki terminology](https://de.minecraft.wiki/w/Minecraft_Wiki:Inhalt) · [Erfrorener](https://de.minecraft.wiki/w/Erfrorener)

Of the 78 item IDs in the source fixture for v1.26.60.5, 49 have exact source labels,
22 have disc compositions, three are potion categories and four lack item labels.
The two effects `fatal_poison` and `freezing` are counted separately. [Source fixture](../tests/fixtures/item_localization_reference.json)

### Update results

The `update_quality` metadata records each section's source release, attempted
release, official coverage and fallback origins for German and English. The
`retained` list identifies displayed names that differ from an available official
translation. The `documented` reason identifies wording from Mojang documentation.

Setup and the update tool show a short status. **Show details** lists name origins
and the causes of failures. Unresolved translations and ambiguous mappings produce
warnings. Reviewed and custom names are informational. A partial update requires a
successful section with changed data or source information. A saved failure message
alone does not qualify. The source comparison uses the normalized Learn listing and
validated enchantment comparison, ignoring fetch times and unrelated page markup.

Missing, unreadable, empty or structurally unusable shared language files prevent
publication. Invalid per-section registries or uncertain numeric identities
retain that whole section while independently valid sections can update. The
same rule covers structurally invalid item definitions and invalid values in
consumed components. Optional absent components remain distinct from malformed
present values; valid source removals can remove obsolete component facts. The
consumed, normalized components of repeated item IDs must agree, including
presence or absence. Conflicting definitions cannot overwrite each other. The
result names the retained sections and their causes. Its persisted quality keeps
their previous provenance and the unsuccessful attempted release, without
claiming a complete verification.
