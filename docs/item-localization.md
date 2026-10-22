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
