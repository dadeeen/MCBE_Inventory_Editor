from __future__ import annotations

from unittest.mock import Mock, patch

import main
import pytest

from mcbe_editor import icon_cache, update_output_i18n
from scripts import update_db, update_icons


def test_update_output_uses_forwarded_english_locale(monkeypatch):
    monkeypatch.setenv(update_output_i18n.UPDATE_LOCALE_ENV, "en")

    assert update_output_i18n.output_t("Alles aktuell, keine Änderungen.") == "Everything is current; no changes."
    assert update_output_i18n.output_t("Neu (+{count}):", count=3) == "Added (+3):"


def test_update_output_defaults_to_german_for_missing_or_unknown_locale(monkeypatch):
    monkeypatch.delenv(update_output_i18n.UPDATE_LOCALE_ENV, raising=False)
    assert update_output_i18n.output_t("Alles aktuell, keine Änderungen.") == "Alles aktuell, keine Änderungen."

    monkeypatch.setenv(update_output_i18n.UPDATE_LOCALE_ENV, "fr")
    assert update_output_i18n.output_t("Alles aktuell, keine Änderungen.") == "Alles aktuell, keine Änderungen."


def test_update_diff_is_rendered_in_forwarded_english_locale(monkeypatch, capsys):
    monkeypatch.setenv(update_output_i18n.UPDATE_LOCALE_ENV, "en")

    update_db.show_diff("ITEMS", {}, {"minecraft:future_widget": True})

    output = capsys.readouterr().out
    assert "Added (+1):" in output
    assert "Statistics: 0 -> 1 (+1 / -0 / ~0)" in output
    assert "Neu" not in output
    assert "Statistik" not in output


def test_updater_failures_use_forwarded_english_locale(monkeypatch, tmp_path):
    monkeypatch.setenv(update_output_i18n.UPDATE_LOCALE_ENV, "en")

    with pytest.raises(RuntimeError, match="Item DB JSON not found"):
        update_icons.load_item_icon_targets(tmp_path / "missing-item-db.json")

    staging = tmp_path / "staging-parent" / "staging"
    target = tmp_path / "target-parent" / "target"
    with pytest.raises(ValueError, match="same directory"):
        icon_cache.publish_icon_cache(staging, target)


def test_main_forwards_request_locale_to_both_updaters():
    db_runner = Mock(return_value=(0, "db"))
    icon_runner = Mock(return_value=(0, "icons"))

    with main.app.test_request_context(headers={"Accept-Language": "en"}), patch.object(
        main.update_script_runner,
        "run_update_db",
        db_runner,
    ), patch.object(main.update_script_runner, "run_update_icons", icon_runner):
        assert main.run_update_db(dry_run=True) == (0, "db")
        assert main.run_update_icons(use_cache=True) == (0, "icons")

    assert db_runner.call_args.kwargs["locale"] == "en"
    assert icon_runner.call_args.kwargs["locale"] == "en"
