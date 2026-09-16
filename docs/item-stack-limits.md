# Item stack limits

The editor distinguishes a recorded Vanilla limit from a conservative creation bound. `stack_limits` contains explicit per-item values, including confirmed 64s. Missing values mean **unverified**, never an implicit 64. `DEFAULT_MAX_STACK = 1` is only a safe creation bound, not a claim that the item is unstackable in Minecraft. Old persistent databases cannot restore the previous 64 fallback through `defaults.max_stack`.

## Sources and the September 2026 review

- Mojang's [Bedrock samples v1.26.50.4](https://github.com/Mojang/bedrock-samples/releases/tag/v1.26.50.4) supply the positive item registry, translations, and data-driven components. The min archive SHA-256 is `2bb667786f4d5bedf97a61cec4ce9613c1e2986224c9deda5fbb108c2d96b07c`.
- The existing v1.26.30.5 registry was compared by exact namespaced ID with [PrismarineJS's extracted Bedrock 1.26.30 item data](https://github.com/PrismarineJS/minecraft-data/blob/master/data/bedrock/1.26.30/items.json), SHA-256 `495695bcd745708ce742f76b581c13f1f21f6e4140a5c19ebcc933766e28dfea`. Existing explicit limits agreed; 142 ordinary-item exceptions to 64 were added. This is a reviewed bundled snapshot, not a new live network dependency or a Java-to-Bedrock mapping.
- The extraction's values for `light_block_0` through `light_block_15`, `allow`, `deny`, `border_block`, and `frosted_ice` were not accepted as confirmed ordinary inventory limits. These 20 technical/Education entries remain unverified. Legacy `wool` retains 64 for its color variants; `air` is an empty-slot sentinel.
- The 105 newly registered 26.50 IDs have no explicit maximum in the downloaded behavior definitions. They remain unverified, including cushions and the straw bed. Registry membership proves that an ID exists, not its stack size. No wiki summary or suffix guess was used to invent these values.

## Updating and validation

The updater retains reviewed engine values from the bundled snapshot, removes values supplied by previous behavior components, then applies the current release's explicit components. New source values take precedence. Both the integer and object forms of [`minecraft:max_stack_size`](https://learn.microsoft.com/en-us/minecraft/creator/reference/content/itemreference/examples/itemcomponents/minecraft_max_stack_size?view=minecraft-bedrock-stable) are supported. An explicitly present empty object has the documented default `value = 64`; an absent component provides no evidence. Invalid types, values outside the editor's signed Count range of 1–127, unknown object fields, and conflicting definitions abort the update instead of falling back.

The updater reports unresolved limits. Future engine-defined items require an additional reviewed fact before larger new stacks are enabled. A way to collect that fact is [`ItemStack.maxAmount`](https://learn.microsoft.com/en-us/minecraft/creator/scriptapi/minecraft/server/itemstack?view=minecraft-bedrock-stable) in a disposable Vanilla world for the matching Bedrock release. No game/server process or real world is automatically started or modified to obtain it. Add-ons may override Vanilla behavior; the catalog does not attest an arbitrary world's pack configuration.

## Preservation and UI

The backend accepts a recorded original amount even when it exceeds the recorded limit or the safe bound. The original must resolve through normal server-side provenance checks; a client-supplied original count is not evidence. New or changed unverified Vanilla stacks can have amount 1 only.

The frontend displays unverified limits separately from actual Max-Stack values, disables the maximum shortcut, and rejects oversized detail/bulk-fill inputs rather than silently substituting 1. Bulk count changes skip unverified stacks when the requested amount exceeds the safe bound. Existing unknown add-on records retain the separate format-range editing policy, but have no automatic Max-Stack action. Regression tests cover component parsing, database migration, aliases, boundary counts, unchanged/moved NBT, forged original amounts, and matching browser behavior.
