from __future__ import annotations

from mcbe_editor import mount_api_routes, mount_placement


def test_direction_scan_prefers_unchecked_over_blocked_fallback(monkeypatch) -> None:
    candidates = [
        {"id": "blickrichtung_2", "distance": 2.0},
        {"id": "blickrichtung_3", "distance": 3.0},
        {"id": "blickrichtung_4", "distance": 4.0},
    ]
    statuses = {
        "blickrichtung_2": False,
        "blickrichtung_3": None,
        "blickrichtung_4": False,
    }

    monkeypatch.setattr(mount_placement, "_distance_candidates", lambda _candidate, _max_radius: candidates)

    def fake_vertical_probe(_db, candidate, _dimension_id, **_kwargs):
        return {
            **candidate,
            "safe_to_place": statuses[candidate["id"]],
            "warning": f"{candidate['id']} status {statuses[candidate['id']]}",
        }

    monkeypatch.setattr(mount_placement, "_try_safe_vertical_candidate", fake_vertical_probe)

    result = mount_placement._try_safe_distance_candidate(object(), {"id": "blickrichtung_6"}, 6, 0)

    assert result["id"] == "blickrichtung_3"
    assert result["safe_to_place"] is None
    assert result["radius_scan_checked_count"] == 3
    assert result["radius_scan_safe_count"] == 0
    assert result["radius_scan_unchecked_count"] == 1
    assert result["radius_scan_unsafe_count"] == 2
    assert [attempt["status"] for attempt in result["radius_scan_attempts"]] == ["unsafe", "unchecked", "unsafe"]


def test_direction_scan_reports_blocked_only_when_all_attempts_are_blocked(monkeypatch) -> None:
    candidates = [
        {"id": "rechts_2", "distance": 2.0},
        {"id": "rechts_3", "distance": 3.0},
    ]

    monkeypatch.setattr(mount_placement, "_distance_candidates", lambda _candidate, _max_radius: candidates)

    def fake_vertical_probe(_db, candidate, _dimension_id, **_kwargs):
        return {**candidate, "safe_to_place": False, "warning": "blocked"}

    monkeypatch.setattr(mount_placement, "_try_safe_vertical_candidate", fake_vertical_probe)

    result = mount_placement._try_safe_distance_candidate(object(), {"id": "rechts_6"}, 6, 0)

    assert result["id"] == "rechts_2"
    assert result["safe_to_place"] is False
    assert result["radius_scan_unchecked_count"] == 0
    assert result["radius_scan_unsafe_count"] == 2


def test_vertical_scan_prefers_unchecked_over_blocked_fallback(monkeypatch) -> None:
    probes = {
        0: {"id": "links_2", "safe_to_place": False, "warning": "blocked at y0"},
        -1: {"id": "links_2", "safe_to_place": None, "warning": "unread at y-1"},
    }

    monkeypatch.setattr(mount_placement, "VERTICAL_PLACEMENT_Y_OFFSETS", (0, -1))
    monkeypatch.setattr(mount_placement, "_candidate_with_vertical_offset", lambda candidate, y_offset: {**candidate, "vertical_adjustment": y_offset})
    monkeypatch.setattr(
        mount_placement,
        "_candidate_with_footprint_probe",
        lambda _db, candidate, dimension_id=None, **_kwargs: {**candidate, **probes[candidate["vertical_adjustment"]]},
    )

    result = mount_placement._try_safe_vertical_candidate(object(), {"id": "links_2"}, 0)

    assert result["safe_to_place"] is None
    assert result["warning"] == "unread at y-1"


def test_vertical_scan_prefers_nearest_safe_height(monkeypatch) -> None:
    def fake_footprint(_db, candidate, dimension_id=None, **_kwargs):
        del dimension_id
        offset = candidate.get("vertical_adjustment", 0)
        return {**candidate, "safe_to_place": offset in {-2, 1}, "warning": f"offset {offset}"}

    monkeypatch.setattr(
        mount_placement,
        "_candidate_with_vertical_offset",
        lambda candidate, y_offset: {**candidate, "y": 70.0 + y_offset, "vertical_adjustment": y_offset},
    )
    monkeypatch.setattr(mount_placement, "_candidate_with_footprint_probe", fake_footprint)

    result = mount_placement._try_safe_vertical_candidate(object(), {"id": "test", "y": 70.0}, 0)

    assert result["vertical_adjustment"] == 1
    assert result["y"] == 71.0


def test_vertical_scan_snaps_fractional_height_to_block_surface(monkeypatch) -> None:
    monkeypatch.setattr(
        mount_placement,
        "_candidate_with_footprint_probe",
        lambda _db, candidate, dimension_id=None, **_kwargs: {**candidate, "safe_to_place": True, "warning": "safe"},
    )

    result = mount_placement._try_safe_vertical_candidate(object(), {"id": "test", "y": 67.4}, 0)

    assert result["y"] == 67.0
    assert result["surface_snap_adjustment"] == -0.4
    assert "Vollblock-Oberfläche" in result["warning"]


def test_optional_chunk_probe_close_failure_falls_back_to_original_preview(monkeypatch) -> None:
    preview = {"candidate_positions": [{"id": "original"}]}

    class FailingCloseDb:
        def close(self):
            raise OSError("close failed")

    class Service:
        def _open_db_readonly(self, _world_path):
            return FailingCloseDb()

    class Deps:
        service = Service()

    monkeypatch.setattr(
        mount_api_routes,
        "refine_preview_placement",
        lambda _db, _preview: {"candidate_positions": [{"id": "annotated"}]},
    )

    result = mount_api_routes._annotate_preview_with_chunk_probe(Deps(), "world", preview)

    assert result == preview
