import pytest

nbt = pytest.importorskip("amulet_nbt")

from mcbe_editor import root_equipment as root_equipment_module
from mcbe_editor.inventory import ENCHANTMENTS, _item_source_digest, build_inventory_nbt, nbt_to_json
from mcbe_editor.root_equipment import (
    apply_root_equipment_writes,
    filter_read_only_root_equipment_payload,
    filter_root_equipment_presence_flags,
    item_allowed_in_equipment_slot,
    merge_root_equipment_fallbacks,
    merge_root_equipment_protected_slots,
    reject_root_equipment_fallback_slot_writes,
    root_equipment_writable_slots,
    split_root_equipment_writes,
)


def item(name, count=1, slot=None):
    fields = {
        "Name": nbt.StringTag(name),
        "Count": nbt.ByteTag(count),
        "Damage": nbt.ShortTag(0),
    }
    if slot is not None:
        fields["Slot"] = nbt.ByteTag(slot)
    return nbt.CompoundTag(fields)


def empty_root_entry():
    # Platzhalter-Shape wie vom Spiel in echten Welten geschrieben.
    return nbt.CompoundTag(
        {
            "Count": nbt.ByteTag(0),
            "Damage": nbt.ShortTag(0),
            "Name": nbt.StringTag(""),
            "WasPickedUp": nbt.ByteTag(0),
        }
    )


def modern_equipped_player():
    # Nachbau des in echten Referenzwelten beobachteten modernen Shapes:
    # dichte Armor-Liste ohne Slot-Keys, Index 0 = Helm ... 3 = Stiefel,
    # Index 4 = Body-Slot, Offhand als 1er-Liste.
    return nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([item("minecraft:stone", slot=0)]),
            "Armor": nbt.ListTag(
                [
                    item("minecraft:leather_helmet"),
                    item("minecraft:leather_chestplate"),
                    item("minecraft:leather_leggings"),
                    item("minecraft:leather_boots"),
                    empty_root_entry(),
                ]
            ),
            "Offhand": nbt.ListTag([item("minecraft:shield")]),
        }
    )


def test_merges_modern_root_armor_and_offhand_as_editable_inventory_items():
    player = modern_equipped_player()
    inventory, _orig = nbt_to_json(player)

    slots = merge_root_equipment_fallbacks(inventory, player, encoded_player_key="player", world_path="/world")

    # Modernes Shape: editierbar, keine geschützten Slots.
    assert slots == []
    assert inventory[103]["name"] == "minecraft:leather_helmet"
    assert inventory[102]["name"] == "minecraft:leather_chestplate"
    assert inventory[101]["name"] == "minecraft:leather_leggings"
    assert inventory[100]["name"] == "minecraft:leather_boots"
    assert inventory[-106]["name"] == "minecraft:shield"
    for slot in (-106, 100, 101, 102, 103):
        assert "root_equipment_read_only" not in inventory[slot]
        assert inventory[slot]["source_container"] == "inventory"
        assert inventory[slot]["source_slot"] == slot
        source_tag = player["Offhand"][0] if slot == -106 else player["Armor"][{103: 0, 102: 1, 101: 2, 100: 3}[slot]]
        assert inventory[slot]["source_item_digest"] == _item_source_digest(source_tag)
    assert inventory[103]["root_equipment_source_tag"] == "Armor"
    assert inventory[103]["root_equipment_source_index"] == 0
    assert inventory[101]["source_player_key"] == "player"
    assert inventory[101]["source_world_path"] == "/world"

    assert root_equipment_writable_slots(player) == {-106, 100, 101, 102, 103}


def test_legacy_root_armor_shape_stays_read_only():
    # Abweichende Listenlänge = Legacy/Fremdtool-Shape: bleibt read-only.
    player = nbt.CompoundTag(
        {
            "Armor": nbt.ListTag(
                [
                    item("minecraft:diamond_boots"),
                    item("minecraft:diamond_leggings"),
                    item("minecraft:diamond_chestplate"),
                ]
            ),
        }
    )
    inventory, _orig = nbt_to_json(player)

    slots = merge_root_equipment_fallbacks(inventory, player)

    assert root_equipment_writable_slots(player) == set()
    assert slots == [100, 101, 102]
    assert inventory[100]["name"] == "minecraft:diamond_boots"
    assert inventory[100]["root_equipment_read_only"] is True
    assert inventory[100]["source_container"] == "armor"

    hidden = merge_root_equipment_protected_slots(
        {
            "inventory": 0,
            "ender_chest": 0,
            "inventory_protected_known": 0,
            "ender_chest_protected_known": 0,
            "inventory_protected_known_slots": [],
            "ender_chest_protected_known_slots": [],
            "inventory_opaque": False,
            "ender_chest_opaque": False,
        },
        slots,
    )
    assert hidden["inventory_protected_known_slots"] == [100, 101, 102]
    assert hidden["inventory_protected_known"] == 0


def test_merge_root_equipment_protected_slots_ignores_malformed_numeric_strings():
    hidden = merge_root_equipment_protected_slots(
        {"inventory_protected_known_slots": ["--5", "-5", "7", None]},
        [100],
    )

    assert hidden["inventory_protected_known_slots"] == [-5, 7, 100]


def test_merges_offhand_item_compound_as_read_only_fallback():
    player = nbt.CompoundTag({"OffHandItem": item("minecraft:totem_of_undying")})
    inventory, _orig = nbt_to_json(player)

    slots = merge_root_equipment_fallbacks(inventory, player)

    assert slots == [-106]
    assert inventory[-106]["name"] == "minecraft:totem_of_undying"
    assert inventory[-106]["source_container"] == "offhand"
    assert inventory[-106]["root_equipment_source_tag"] == "OffHandItem"
    assert inventory[-106]["root_equipment_read_only"] is True


def test_inventory_equipment_slot_takes_precedence_over_root_equipment():
    player = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([item("minecraft:iron_helmet", slot=103), item("minecraft:shield", slot=-106)]),
            "Armor": nbt.ListTag([item("minecraft:diamond_helmet")]),
            "OffHandItem": item("minecraft:totem_of_undying"),
        }
    )
    inventory, _orig = nbt_to_json(player)

    slots = merge_root_equipment_fallbacks(inventory, player)

    assert slots == []
    assert inventory[103]["name"] == "minecraft:iron_helmet"
    assert inventory[-106]["name"] == "minecraft:shield"
    assert "root_equipment_read_only" not in inventory[103]
    assert "root_equipment_read_only" not in inventory[-106]


def test_filters_read_only_root_equipment_from_inventory_save_payload():
    payload = [
        {"slot": 101, "name": "minecraft:diamond_leggings", "root_equipment_read_only": True},
        {"slot": -106, "name": "minecraft:shield", "source_container": "offhand"},
        {"slot": 0, "name": "minecraft:stone"},
    ]

    assert filter_read_only_root_equipment_payload(payload) == [{"slot": 0, "name": "minecraft:stone"}]
    assert filter_read_only_root_equipment_payload({"not": "a-list"}) == {"not": "a-list"}


def test_rejects_stray_root_equipment_copies_outside_root_slots():
    stray_copy = [
        {"slot": 5, "name": "minecraft:diamond_leggings", "root_equipment_read_only": True},
        {"slot": 0, "name": "minecraft:stone"},
    ]
    with pytest.raises(ValueError, match=r"Slot\(s\) 5"):
        filter_read_only_root_equipment_payload(stray_copy)

    stray_by_container = [{"slot": 7, "name": "minecraft:shield", "source_container": "offhand"}]
    with pytest.raises(ValueError, match=r"Slot\(s\) 7"):
        filter_read_only_root_equipment_payload(stray_by_container)

    stray_without_slot = [{"name": "minecraft:shield", "root_equipment_read_only": True}]
    with pytest.raises(ValueError, match=r"Slot\(s\) \?"):
        filter_read_only_root_equipment_payload(stray_without_slot)


def test_rejects_backend_writes_into_root_equipment_fallback_slots():
    player = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([item("minecraft:stone", slot=0)]),
            "Armor": nbt.ListTag([item("minecraft:diamond_leggings")]),
            "OffHandItem": item("minecraft:totem_of_undying"),
        }
    )
    inventory, _orig = nbt_to_json(player)

    with pytest.raises(ValueError, match="read-only"):
        reject_root_equipment_fallback_slot_writes(
            player,
            [
                {"slot": 101, "name": "minecraft:golden_leggings", "count": 1},
                {"slot": -106, "name": "minecraft:shield", "count": 1},
            ],
            inventory.keys(),
        )

    reject_root_equipment_fallback_slot_writes(
        player,
        [{"slot": 0, "name": "minecraft:stone", "count": 1}],
        inventory.keys(),
    )


def test_split_routes_writable_equipment_slots_to_root_lists():
    player = modern_equipped_player()
    inventory, _orig = nbt_to_json(player)
    payload = [
        {"slot": 0, "name": "minecraft:stone", "count": 1},
        {"slot": 103, "name": "minecraft:diamond_helmet", "count": 1},
        {"slot": -106, "name": "minecraft:shield", "count": 1},
    ]

    remaining, equipment = split_root_equipment_writes(player, payload, inventory.keys())

    assert [entry["slot"] for entry in remaining] == [0]
    assert sorted(entry["slot"] for entry in equipment) == [-106, 103]

    # Legacy-Shape: nichts wird abgezweigt.
    legacy = nbt.CompoundTag({"Armor": nbt.ListTag([item("minecraft:diamond_boots")])})
    remaining, equipment = split_root_equipment_writes(legacy, payload, ())
    assert len(remaining) == 3
    assert equipment == []


def test_apply_root_equipment_writes_updates_root_lists_in_place():
    player = modern_equipped_player()
    trim_marker = nbt.CompoundTag({"Material": nbt.StringTag("gold")})
    player["Armor"][0]["Trim"] = trim_marker

    apply_root_equipment_writes(
        player,
        [
            # Helm bleibt (Zusatz-NBT muss erhalten bleiben), Count/Damage editierbar.
            {"slot": 103, "name": "minecraft:leather_helmet", "count": 1, "damage": 3},
            # Schildhand: neues Item in bisher belegtem Slot.
            {"slot": -106, "name": "minecraft:totem_of_undying", "count": 1},
        ],
        ENCHANTMENTS,
        allow_clears=True,
    )

    armor = player["Armor"]
    assert len(armor) == 5
    assert armor[0]["Name"].py_data == "minecraft:leather_helmet"
    # Beschädigbare Items tragen die Abnutzung im tag-Compound (Bedrock-Konvention).
    assert armor[0]["tag"]["Damage"].py_data == 3
    assert armor[0]["Trim"]["Material"].py_data == "gold"
    assert "Slot" not in armor[0]
    # Nicht gesendete sichtbare Items wurden bewusst geleert.
    for index in (1, 2, 3):
        assert armor[index]["Name"].py_data == ""
        assert int(armor[index]["Count"].py_data) == 0
        assert "Slot" not in armor[index]
    # Body-Slot (Index 4) bleibt unangetastet.
    assert armor[4]["Name"].py_data == ""
    offhand = player["Offhand"]
    assert len(offhand) == 1
    assert offhand[0]["Name"].py_data == "minecraft:totem_of_undying"
    assert "Slot" not in offhand[0]


def test_root_equipment_write_uses_the_shared_data_variant_validation(monkeypatch):
    player = modern_equipped_player()
    player["Offhand"][0] = item("minecraft:goat_horn")
    monkeypatch.setattr(
        root_equipment_module,
        "OFFHAND_ITEM_NAMES",
        root_equipment_module.OFFHAND_ITEM_NAMES | {"goat_horn"},
    )

    with pytest.raises(ValueError, match="keine unterstützte Variante"):
        apply_root_equipment_writes(
            player,
            [{"slot": -106, "name": "minecraft:goat_horn", "count": 1, "damage": 99}],
            ENCHANTMENTS,
        )

    assert player["Offhand"][0]["Damage"].py_data == 0


def test_root_equipment_write_uses_the_shared_entity_variant_hook(monkeypatch):
    player = modern_equipped_player()
    calls = []
    monkeypatch.setattr(
        root_equipment_module,
        "_apply_entity_variant_edit",
        lambda item_compound, validated_item, base_item_tag, label: calls.append((item_compound, validated_item, base_item_tag, label)),
    )

    # Der Hook läuft nur für tatsächlich geänderte Items: ein unverändertes
    # Echo-Item wird bewusst gar nicht neu gebaut.
    apply_root_equipment_writes(
        player,
        [{"slot": -106, "name": "minecraft:shield", "count": 1, "damage": 0, "display_name": "Wächter"}],
        ENCHANTMENTS,
    )

    assert len(calls) == 1
    assert calls[0][1]["name"] == "minecraft:shield"
    assert calls[0][3] == "Ausrüstung"


def test_root_equipment_write_skips_the_variant_hook_for_an_unchanged_echo(monkeypatch):
    player = modern_equipped_player()
    before = player["Offhand"][0].copy()
    calls = []
    monkeypatch.setattr(
        root_equipment_module,
        "_apply_entity_variant_edit",
        lambda *args: calls.append(args),
    )

    apply_root_equipment_writes(
        player,
        [{"slot": -106, "name": "minecraft:shield", "count": 1, "damage": 0}],
        ENCHANTMENTS,
    )

    assert calls == []
    assert dict(player["Offhand"][0]) == dict(before)


def test_apply_root_equipment_writes_uses_verified_cross_player_source():
    player = modern_equipped_player()
    source = item("minecraft:leather_helmet")
    source["Trim"] = nbt.CompoundTag({"Material": nbt.StringTag("diamond")})
    payload = {
        "slot": 103,
        "source_slot": 103,
        "source_player_key": "player-a",
        "source_container": "inventory",
        "source_item_digest": _item_source_digest(source),
        "name": "minecraft:leather_helmet",
        "count": 1,
        "damage": 0,
        "has_protected_nbt": True,
    }

    apply_root_equipment_writes(
        player,
        [payload],
        ENCHANTMENTS,
        source_item_maps={("player-a", "inventory"): {103: source}},
        target_player_key="player-b",
    )

    assert player["Armor"][0]["Trim"]["Material"].py_data == "diamond"


def test_apply_root_equipment_writes_honors_deliberate_nbt_replacement():
    player = modern_equipped_player()
    player["Armor"][0]["Trim"] = nbt.CompoundTag({"Material": nbt.StringTag("gold")})

    apply_root_equipment_writes(
        player,
        [
            {
                "slot": 103,
                "name": "minecraft:leather_helmet",
                "count": 1,
                "damage": 0,
                "replace_original_nbt": True,
            }
        ],
        ENCHANTMENTS,
    )

    assert "Trim" not in player["Armor"][0]


def test_apply_root_equipment_writes_preserves_items_for_stale_clients():
    player = modern_equipped_player()

    # Stale Client: keine Ausrüstungs-Items im Payload, kein Editable-Flag.
    apply_root_equipment_writes(player, [], ENCHANTMENTS, allow_clears=False)

    armor = player["Armor"]
    assert armor[0]["Name"].py_data == "minecraft:leather_helmet"
    assert armor[3]["Name"].py_data == "minecraft:leather_boots"
    assert player["Offhand"][0]["Name"].py_data == "minecraft:shield"


def test_apply_root_equipment_writes_equips_into_empty_placeholder():
    player = nbt.CompoundTag(
        {
            "Armor": nbt.ListTag([empty_root_entry(), empty_root_entry(), empty_root_entry(), empty_root_entry()]),
            "Offhand": nbt.ListTag([empty_root_entry()]),
        }
    )

    apply_root_equipment_writes(
        player,
        [{"slot": 100, "name": "minecraft:diamond_boots", "count": 1}],
        ENCHANTMENTS,
        allow_clears=True,
    )

    armor = player["Armor"]
    assert armor[3]["Name"].py_data == "minecraft:diamond_boots"
    assert "Slot" not in armor[3]
    assert "WasPickedUp" in armor[3]
    for index in (0, 1, 2):
        assert armor[index]["Name"].py_data == ""


def test_presence_flags_skip_supported_modern_equipment_lists():
    from mcbe_editor.inventory import protected_player_nbt_flags

    player = modern_equipped_player()
    player["Mainhand"] = nbt.ListTag([item("minecraft:wooden_sword")])
    player["PlayerUIItems"] = nbt.ListTag([item("minecraft:stone", slot=0)])

    flags = filter_root_equipment_presence_flags(player, protected_player_nbt_flags(player))

    # Editierbare moderne Ausrüstung und der abgeleitete Mainhand-Spiegel sind
    # keine "geschützten/future" Strukturen mehr; PlayerUIItems bleibt gemeldet.
    assert "Armor" not in flags["root_item_lists_present"]
    assert "Offhand" not in flags["root_item_lists_present"]
    assert "Mainhand" not in flags["root_item_lists_present"]
    assert flags["root_item_lists_present"].get("PlayerUIItems") == 1


def test_presence_flags_keep_legacy_equipment_shapes():
    from mcbe_editor.inventory import protected_player_nbt_flags

    # Legacy: 1-Eintrag-Armor-Liste + Mainhand mit Nicht-Compound-Eintrag.
    player = nbt.CompoundTag(
        {
            "Armor": nbt.ListTag([item("minecraft:diamond_boots")]),
            "Mainhand": nbt.ListTag([nbt.StringTag("future-mainhand")]),
        }
    )

    flags = filter_root_equipment_presence_flags(player, protected_player_nbt_flags(player))

    assert flags["root_item_lists_present"].get("Armor") == 1
    assert flags["root_item_lists_present"].get("Mainhand") == 1


def test_item_allowed_in_equipment_slot_matches_wearable_items():
    # Rüstung: Slot ergibt sich aus der Item-ID.
    assert item_allowed_in_equipment_slot(103, "minecraft:diamond_helmet")
    assert item_allowed_in_equipment_slot(103, "minecraft:carved_pumpkin")
    assert item_allowed_in_equipment_slot(103, "minecraft:zombie_head")
    assert item_allowed_in_equipment_slot(103, "minecraft:skeleton_skull")
    assert item_allowed_in_equipment_slot(102, "minecraft:elytra")
    assert item_allowed_in_equipment_slot(102, "minecraft:netherite_chestplate")
    assert item_allowed_in_equipment_slot(101, "minecraft:iron_leggings")
    assert item_allowed_in_equipment_slot(100, "minecraft:golden_boots")
    assert not item_allowed_in_equipment_slot(103, "minecraft:diamond_boots")
    assert not item_allowed_in_equipment_slot(100, "minecraft:diamond_helmet")
    assert not item_allowed_in_equipment_slot(102, "minecraft:stone")

    # Schildhand: kuratierte Bedrock-Positivliste.
    for name in ("shield", "totem_of_undying", "arrow", "firework_rocket", "filled_map", "nautilus_shell"):
        assert item_allowed_in_equipment_slot(-106, f"minecraft:{name}")
    assert not item_allowed_in_equipment_slot(-106, "minecraft:diamond_sword")
    assert not item_allowed_in_equipment_slot(-106, "minecraft:torch")

    # Normale Slots bleiben unbeschränkt.
    assert item_allowed_in_equipment_slot(0, "minecraft:stone")


def test_item_allowed_in_equipment_slot_prefers_official_wearable_component(monkeypatch):
    slots = {
        "minecraft:future_hat": "slot.armor.head",
        "minecraft:future_sword": "slot.weapon.offhand",
        "minecraft:future_boots": "slot.armor.body",
    }
    monkeypatch.setattr(root_equipment_module, "item_wearable_slot", lambda name: slots.get(name))

    assert root_equipment_module.item_allowed_in_equipment_slot(103, "minecraft:future_hat")
    assert root_equipment_module.item_allowed_in_equipment_slot(-106, "minecraft:future_sword")
    # Ein offizieller Body-Slot ist nicht einer der vier editierbaren Spieler-Rüstungsslots.
    assert not root_equipment_module.item_allowed_in_equipment_slot(100, "minecraft:future_boots")
    # Die offizielle Komponente hat Vorrang vor irreführenden Namenssuffixen.
    assert not root_equipment_module.item_allowed_in_equipment_slot(100, "minecraft:future_sword")


def test_offhand_permission_survives_unrelated_official_wearable_slot(monkeypatch):
    """minecraft:wearable ist nicht das Bedrock-Prädikat für die Offhand-Erlaubnis.

    Ein Item darf laut Bedrock gleichzeitig eine Wearable-Komponente für einen
    anderen Slot besitzen und in der Schildhand erlaubt sein. Die offizielle
    Komponente darf die kuratierte Positivliste deshalb nur ergänzen.
    """

    slots = {"minecraft:totem_of_undying": "slot.weapon.mainhand"}
    monkeypatch.setattr(root_equipment_module, "item_wearable_slot", lambda name: slots.get(name))

    assert root_equipment_module.item_allowed_in_equipment_slot(-106, "minecraft:totem_of_undying")
    # Ein Mainhand-Slot bleibt trotzdem kein Spieler-Rüstungsslot.
    assert not root_equipment_module.item_allowed_in_equipment_slot(102, "minecraft:totem_of_undying")


def test_apply_root_equipment_writes_rejects_non_wearable_items():
    player = modern_equipped_player()

    with pytest.raises(ValueError, match="Helm-Slot tragbares Item"):
        apply_root_equipment_writes(
            player,
            [{"slot": 103, "name": "minecraft:stone", "count": 1}],
            ENCHANTMENTS,
            allow_clears=True,
        )

    with pytest.raises(ValueError, match="Schildhand-Slot tragbares Item"):
        apply_root_equipment_writes(
            player,
            [{"slot": -106, "name": "minecraft:diamond_sword", "count": 1}],
            ENCHANTMENTS,
            allow_clears=True,
        )

    # Nichts wurde verändert.
    assert player["Armor"][0]["Name"].py_data == "minecraft:leather_helmet"
    assert player["Offhand"][0]["Name"].py_data == "minecraft:shield"


def test_apply_root_equipment_writes_rejects_non_writable_shape():
    legacy = nbt.CompoundTag({"Armor": nbt.ListTag([item("minecraft:diamond_boots")])})
    with pytest.raises(ValueError, match="nicht bearbeitbar"):
        apply_root_equipment_writes(
            legacy,
            [{"slot": 100, "name": "minecraft:diamond_boots", "count": 1}],
            ENCHANTMENTS,
            allow_clears=True,
        )


def test_filtered_root_equipment_payload_does_not_create_inventory_duplicates():
    player = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag([item("minecraft:stone", slot=0)]),
            "Armor": nbt.ListTag([item("minecraft:diamond_leggings")]),
            "OffHandItem": item("minecraft:totem_of_undying"),
        }
    )
    inventory, _orig = nbt_to_json(player)
    merge_root_equipment_fallbacks(inventory, player)

    payload = filter_read_only_root_equipment_payload(list(inventory.values()))
    saved = build_inventory_nbt(player, payload, ENCHANTMENTS)

    saved_slots = sorted(int(entry["Slot"].py_data) for entry in saved)
    assert saved_slots == [0]
    assert saved[0]["Name"].py_data == "minecraft:stone"
