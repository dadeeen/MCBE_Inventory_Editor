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

These pairs appear only in the technical log as a flat list of expected name differences in the active UI language. They are absent from the change details and the list of unresolved findings. Classification requires the exact reviewed ID, both catalog names and both source names. Changed or missing labels return to the ordinary comparison; the IDs are not exempt from validation.

## Terminology alignment

The following old names identify the correct object, but the bundled catalog follows the Bedrock source terminology for consistency with in-game search:

- German armor: the four chainmail pieces use Kettenhemd-Stiefel, Kettenhemd-Harnisch, Kettenhemd-Helm and Kettenhemd-Beinschutz. Diamond, gold, iron and netherite torso/leg pieces use Harnisch and Beinschutz instead of Brustplatte and Beinschienen.
- German miscellaneous: Redstone-Komparator → Komparator; Gebratenes Rindfleisch → Steak; Wirrpilzrute → Wirrpilz auf einem Stock.
- English blocks: coal, diamond, emerald, gold, iron, lapis, netherite and redstone use Mojang's “Block of …” wording instead of “… Block” (lapis: Block of Lapis Lazuli).
- English miscellaneous: Redstone Comparator → Comparator; Cooked Beef → Steak; Ender Eye → Eye of Ender; Poplar Standing Sign → Poplar Sign; Redstone → Redstone Dust.

## Shared migration policy

`mcbe_editor/item_name_policy.py` contains the known obsolete pairs, including their English-only fallback form. Replacement names come from the bundled catalog; the policy does not duplicate a second replacement dictionary. Both runtime loading and the updater use the same helper. A replacement requires an exact match of both inherited language values and a complete reviewed replacement. Custom names, including a custom value in just one language, remain unchanged.

The updater applies these repairs before and after resolving localization fallbacks, so a formerly English-only entry can receive both the German name and the corrected English name in one update. Generic fallback translation requires the existing English label to match the source; equal names in both languages alone do not identify an untranslated item. Repeating the update does not repeat the migration. The dry run previews it without writing the persistent database. These catalog repairs do not change an item's custom display name, lore or saved NBT.

## Effects and enchantments

`mcbe_editor/numeric_catalog_policy.py` reconciles reviewed numeric identities for both the updater and runtime loading. Recognized names and identifier aliases migrate obsolete numeric positions; custom names at an existing reviewed ID remain intact. Conflicting names or migration destinations block only the affected section. The updater skips that section; runtime loading preserves the persistent file and records the conflicting IDs without invoking whole-file corruption recovery. Unknown entries outside the reviewed IDs remain intact.

An affected section has no editable runtime identities until its conflict is resolved. Existing effect and enchantment NBT uses the same lossless protection as unknown entries; unrelated edits preserve it verbatim. The remaining catalog sections stay available. Item-DB status and player-load warnings identify the blocked section and IDs. Reloading a repaired catalog restores its editable identities without retaining a stale block.

Effect descriptions use the reviewed German and English texts in the bundled catalog. Enchantment maximum levels use the reviewed Vanilla values; custom enchantment descriptions remain intact. Tests require the bundled enchantment IDs and levels to agree with `enchantment_max_levels.json`, and exercise updater output through the runtime loader. An omitted optional enchantment description and an empty description are equivalent.

Freezing uses the editorial German translation “Gefrieren” and the English name “Freezing”, with explicit experimental labels. BDS 1.26.60.6 engine-created references establish effect ID 38 and potion data values 47 (`freezing`) and 48 (`long_freezing`). The bundled base catalog uses Bedrock samples v1.26.50.4; the reviewed effect survives updates from that older registry. The v1.26.60.5 registry includes the effect without corresponding German or English language-file labels, so the updater retains the reviewed names and records their fallback origin. These labels do not claim an official German translation. The potion variants use the existing base-icon fallback when no matching Vanilla texture key is available.

## Missing source labels

Source integrity and display-name coverage are separate checks. A valid language
file can omit one name or an entire category without invalidating the registry.
For each validated identity and locale, the updater prefers the official label,
then an exact reviewed catalog name, an unambiguously matched existing name,
the other language, and finally the technical identifier. Item names can also
use the Microsoft Learn item list as an explicitly recorded fallback source.
This does not count as coverage in Mojang's language files. Reconciliation still
preserves custom names. Labels never establish numeric IDs or maximum levels.
Direct and safely derived variant labels are resolved independently per locale:
a German-only or English-only source label remains official in that language,
while only the missing language receives a fallback. Ambiguous labels cannot
establish an item identity or authorize replacing a custom name.
Matching a label across different localization keys requires a current source
name associated with the same item identity. Existing and curated fallback names
cannot establish that association or count as official coverage.
Unresolved source templates are unavailable names, independently in each locale.
Resolution and coverage use the same rule for items, effects and enchantments;
a usable name in the other language remains available. Custom display names are
preserved without applying the source-template filter to them.
Untranslated future item IDs remain in the addable registry and receive runtime
display fallbacks; they do not require invented entries in the persisted name
catalog.
Name resolution and coverage use the same validated registry identities, so a
known variant-key translation also applies before an item reaches the Learn
listing. An identity or serialization alias alone does not create a display name.

`update_quality` in source metadata records each section's source release,
attempted release, official DE/EN coverage and fallback sources. A fallback does
not count as an official translation. The setup dialog and Item DB tools expose
these hints after reloads and restarts. A successful comparison with fallback
names can be current; repeating a download is not a remedy for absent upstream
translations.

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
