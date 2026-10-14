import io
import json
import zipfile

import pytest

from mcbe_editor.item_data import _validated_item_components
from scripts.update_db import parse_json_item_components


@pytest.mark.parametrize("raw", [True, False, {"value": True}, {"value": False}])
def test_offhand_component_survives_update_and_database_validation(raw):
    payload = {"minecraft:item": {"description": {"identifier": "minecraft:test_item"}, "components": {"minecraft:allow_off_hand": raw}}}
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("behavior_pack/items/test_item.json", json.dumps(payload))
    with zipfile.ZipFile(io.BytesIO(data.getvalue())) as archive:
        _, _, components = parse_json_item_components(archive)
    expected = raw if isinstance(raw, bool) else raw["value"]
    assert _validated_item_components(components)["allow_off_hand"]["minecraft:test_item"] == {"value": expected}


@pytest.mark.parametrize("raw", ["false", 1, None, {}, {"value": "true"}])
def test_offhand_component_does_not_guess_invalid_values(raw):
    from scripts.update_db import _normalize_allow_off_hand_component

    with pytest.raises(RuntimeError):
        _normalize_allow_off_hand_component(raw, member="test_item.json")
