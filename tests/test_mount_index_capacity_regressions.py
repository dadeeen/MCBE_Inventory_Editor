"""A workspace batch must not exceed the chunk index its validator can read."""

import pytest

from mcbe_editor import mount_api_routes, mount_write
from tests.test_workspace_save import _refusal, _synthetic_mount_workspace


def _actor_entry(index):
    return (2).to_bytes(4, "big") + index.to_bytes(4, "big")


def test_digp_capacity_allows_last_entry_and_unchanged_full_index():
    capacity = mount_write.MAX_DIGP_VALUE_BYTES // 8
    existing = b"".join(_actor_entry(index) for index in range(1, capacity))
    last = _actor_entry(capacity)

    full = mount_write.merge_digp_value(existing, last)

    assert len(full) == mount_write.MAX_DIGP_VALUE_BYTES
    assert mount_write.merge_digp_value(full, last) == full
    assert len(mount_write.split_digp_value(full)) == capacity


def test_digp_capacity_rejects_new_entry_before_returning_write_plan():
    capacity = mount_write.MAX_DIGP_VALUE_BYTES // 8
    full = b"".join(_actor_entry(index) for index in range(1, capacity + 1))

    with pytest.raises(ValueError, match="digp"):
        mount_write.merge_digp_value(full, _actor_entry(capacity + 1))


@pytest.mark.parametrize("remaining_capacity,mount_count", [(0, 1), (1, 2)])
def test_workspace_overfull_chunk_keeps_player_and_all_mounts_unwritten(tmp_path, monkeypatch, remaining_capacity, mount_count):
    fixture = _synthetic_mount_workspace(tmp_path, monkeypatch)
    capacity = mount_write.MAX_DIGP_VALUE_BYTES // 8
    existing_entries = [_actor_entry(index) for index in range(1, capacity - remaining_capacity + 1)]
    fixture.values.update({mount_write.ACTOR_PREFIX + entry: b"existing actor" for entry in existing_entries})
    digp_key = mount_write.digp_key_for_position({"x": 2, "z": 2})
    fixture.values[digp_key] = b"".join(existing_entries)
    before = dict(fixture.values)
    mounts = [
        {
            "mount_type": "minecraft:horse",
            "create_mode": "synthetic_full",
            "placement_radius": 2,
            "preferred_offset": offset,
            "allow_unchecked_placement": True,
        }
        for offset in ({"x": 2, "z": 0}, {"x": 0, "z": 2})[:mount_count]
    ]

    result, status = _refusal(
        mount_api_routes.save_workspace({**fixture.request, "stats": {"health": 19}, "mounts": mounts}, fixture.deps, fixture.player_deps)
    )

    assert status == 400
    assert result["success"] is False
    assert not result.get("write_committed")
    assert "digp" in result["error"]
    assert fixture.batches == []
    assert fixture.values == before
