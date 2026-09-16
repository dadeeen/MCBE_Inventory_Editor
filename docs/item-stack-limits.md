# Item stack limits

The editor distinguishes a recorded Vanilla limit from a conservative creation bound. `stack_limits` contains explicit per-item values, including confirmed 64s. Missing values mean **unverified**, never an implicit 64. `DEFAULT_MAX_STACK = 1` is only a safe creation bound, not a claim that the item is unstackable in Minecraft. Old persistent databases cannot restore the previous 64 fallback through `defaults.max_stack`.

## Sources and the September 2026 review

- Mojang's [Bedrock samples v1.26.50.4](https://github.com/Mojang/bedrock-samples/releases/tag/v1.26.50.4) supply the positive item registry, translations, and data-driven components. The min archive SHA-256 is `2bb667786f4d5bedf97a61cec4ce9613c1e2986224c9deda5fbb108c2d96b07c`.
- The existing v1.26.30.5 registry was compared by exact namespaced ID with [PrismarineJS's extracted Bedrock 1.26.30 item data](https://github.com/PrismarineJS/minecraft-data/blob/master/data/bedrock/1.26.30/items.json), SHA-256 `495695bcd745708ce742f76b581c13f1f21f6e4140a5c19ebcc933766e28dfea`. Existing explicit limits agreed; 142 ordinary-item exceptions to 64 were added. This is a reviewed bundled snapshot, not a new live network dependency or a Java-to-Bedrock mapping.
- A subsequent run against **official BDS 1.26.50.5**, using the [engine checks](engine-checks.md), measured all **1,623 registered item IDs** and completed two save/reload cycles for **6,040 item cases**. It corrected three older extracted values: `armor_stand` (16), `cake` (1), and `lodestone_compass` (1) each have a measured maximum of **64** in this build.
- This run closed the 125 remaining gaps: 105 new 26.50 IDs plus `light_block_0` through `light_block_15`, `allow`, `deny`, `border_block`, and `frosted_ice`. Cushions, the straw bed and the two poplar signs have maximum 16; the two poplar boats have maximum 1; the other 104 entries have maximum 64. The technical entries were measured as inventory items in this BDS profile; Education gameplay and UI availability are separate questions. Legacy `wool` retains 64 for its color variants; `air` is an empty-slot sentinel.
- The official Linux BDS archive SHA-256 was `a0e86d66162e039c43e5609ad45b3459df26592763c5577cf276ef04b7047b05`. The reviewed values were promoted to the sorted bundled catalog and checked again. Its raw catalog snapshot SHA-256 was `b22042dd97264f847051e8a3dd29539d563318ae7e75a33c9b6cd95043ca87b5` (line-ending sensitive). All current registry limits are now recorded; future registry additions still require evidence. Registry membership alone never proves a stack size.

## Updating and validation

The extended engine review also found three durability discrepancies:
`fishing_rod` 64 → **384**, `carrot_on_a_stick` 25 → **26**, and
`chainmail_helmet` 195 → **165**. These are engine durability units, not a count
of successful gameplay uses. The catalog checker now compares every recorded
durability as well as stack size, and the updater retains reviewed bundled
durability values when refreshing an older persistent database. Current explicit
Mojang components still take precedence. The extended suite tests 0, 1, half and
maximum-minus-one damage through engine reloads; it does not simulate every way
an item can lose durability.

All 1,623 stack limits and all 84 durability components subsequently matched
**BDS 1.26.51.1**. The [expanded engine run](engine-checks.md) completed 13,037
item cases with two reloads, including the corrected durability boundaries.
Its archive SHA-256 is `ad91d3b824e51ea50b5bb601c295cbd8f543a29b14315c2ad89ff27311e2d860`;
the raw catalog snapshot SHA-256 is
`f7cdb1d9da1348e856920f7b66539339e3c7792c15b769b5267179f518003ad9`
(line-ending sensitive).

The updater retains reviewed engine values from the bundled snapshot, removes values supplied by previous behavior components, then applies the current release's explicit components. New source values take precedence. Both the integer and object forms of [`minecraft:max_stack_size`](https://learn.microsoft.com/en-us/minecraft/creator/reference/content/itemreference/examples/itemcomponents/minecraft_max_stack_size?view=minecraft-bedrock-stable) are supported. An explicitly present empty object has the documented default `value = 64`; an absent component provides no evidence. Invalid types, values outside the editor's signed Count range of 1–127, unknown object fields, and conflicting definitions abort the update instead of falling back.

The updater reports unresolved limits. Future engine-defined items require an additional reviewed fact before larger new stacks are enabled. A way to collect that fact is [`ItemStack.maxAmount`](https://learn.microsoft.com/en-us/minecraft/creator/scriptapi/minecraft/server/itemstack?view=minecraft-bedrock-stable) in a disposable Vanilla world for the matching Bedrock release. No game/server process or real world is automatically started or modified to obtain it. Add-ons may override Vanilla behavior; the catalog does not attest an arbitrary world's pack configuration.

## Preservation and UI

The optional [engine checks](engine-checks.md) can now collect version-bound
`ItemStack.maxAmount` observations and exercise item NBT persistence. Their
reports keep missing facts and disagreements explicit; candidate limits are
not automatically applied to the bundled catalog.

The backend accepts a recorded original amount even when it exceeds the recorded limit or the safe bound. The original must resolve through normal server-side provenance checks; a client-supplied original count is not evidence. New or changed unverified Vanilla stacks can have amount 1 only.

The frontend displays unverified limits separately from actual Max-Stack values, disables the maximum shortcut, and rejects oversized detail/bulk-fill inputs rather than silently substituting 1. Bulk count changes skip unverified stacks when the requested amount exceeds the safe bound. Existing unknown add-on records retain the separate format-range editing policy, but have no automatic Max-Stack action. Regression tests cover component parsing, database migration, aliases, boundary counts, unchanged/moved NBT, forged original amounts, and matching browser behavior.
