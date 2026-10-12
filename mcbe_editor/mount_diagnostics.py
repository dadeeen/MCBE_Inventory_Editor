"""User-facing explanations derived from mount placement evidence.

Diagnostics describe why a check is incomplete; they never change its verdict.
Repeated failures across the collision footprint are grouped by cause while
retaining the affected chunks and one concrete block position.
"""

from __future__ import annotations

from typing import Any

from .i18n import t
from .mount_block_probe import CHUNK_FINALIZED_DONE, is_confirmed_full_support_surface, support_surface_shape_is_state_dependent


def placement_issue(code: str, *, block_name: str = "") -> dict[str, Any]:
    if code == "chunk_data_missing":
        message = t("Für einen Teil des Standplatzes fehlen Chunk-Daten im geöffneten Spielstand.")
        hint = t("Bereich im Spiel laden, Welt speichern und schließen. Danach den aktuellen Spielstand öffnen und die Vorschau erneut prüfen.")
    elif code == "generation_incomplete":
        message = t("Die gespeicherte Chunk-Generierung ist noch nicht abgeschlossen.")
        hint = t("Bereich im Spiel laden, Welt speichern und schließen. Danach die Vorschau erneut prüfen.")
    elif code == "generation_unconfirmed":
        message = t("Der Chunk ist vorhanden, aber der Abschluss seiner Generierung ist nicht nachweisbar.")
        hint = t(
            "Welt im Spiel speichern und schließen, dann erneut prüfen. "
            "Bleibt der Hinweis bestehen, muss die Unterstützung für diesen Spielstand geprüft werden."
        )
    elif code == "additional_block_layers":
        message = t("Zusätzliche Blockschichten in diesem Bereich werden vom Editor noch nicht ausgewertet, etwa Wasser in Blöcken.")
        hint = t("Einen anderen Standplatz mit vollständig lesbaren Blockdaten wählen.")
    elif code == "unsupported_block_format":
        message = t("Das gespeicherte Blockformat wird vom Editor noch nicht unterstützt.")
        hint = t("Einen anderen Standplatz wählen oder die Unterstützung für dieses Weltformat prüfen lassen.")
    elif code == "position_out_of_range":
        message = t("Die Position liegt außerhalb des unterstützten Prüfbereichs.")
        hint = t("Spielerposition und Dimension prüfen und einen anderen Standplatz wählen.")
    elif code == "support_state_unknown":
        message = t("Ob der Bodenblock {block} trägt, hängt von einem Blockzustand ab, den der Editor nicht auswertet.", block=block_name)
        hint = t("Einen Standplatz auf einem bekannten Vollblock wählen, zum Beispiel Stein oder Erde.")
    elif code == "support_shape_unknown":
        message = t("Die Tragfähigkeit des Bodenblocks {block} ist dem Editor nicht bekannt.", block=block_name)
        hint = t("Einen Standplatz auf einem bekannten Vollblock wählen, zum Beispiel Stein oder Erde.")
    elif code == "probe_failed":
        message = t("Die Blockprüfung wurde wegen eines Lesefehlers abgebrochen.")
        hint = t("Vorschau erneut prüfen. Tritt der Fehler wieder auf, die Fehlerdetails im Editor-Protokoll prüfen lassen.")
    else:
        code = "block_data_unreadable"
        message = t("Vorhandene Blockdaten konnten nicht eindeutig gelesen werden.")
        hint = t("Vorschau erneut prüfen. Bleibt der Hinweis bestehen, müssen die betroffenen Blockdaten geprüft werden.")
    return {"code": code, "message": message, "hint": hint, "chunks": [], "block_count": 0, "sample_block": None}


def _block_issue_codes(block: dict[str, Any]) -> list[str]:
    reason = block.get("reason")
    if reason in {"subchunk_y_out_of_range", "local_coordinate_out_of_range"}:
        return ["position_out_of_range"]
    if reason == "subchunk_missing" and not block.get("chunk_generated"):
        return ["chunk_data_missing"]
    codes = []
    if not block.get("block_name") and reason != "chunk_not_finalized":
        if reason == "additional_block_layers_unchecked":
            codes.append("additional_block_layers")
        elif reason in {"unsupported_subchunk_version", "runtime_palette_unsupported", "unsupported_bits_per_block", "only_layer_zero_supported"}:
            codes.append("unsupported_block_format")
        else:
            codes.append("block_data_unreadable")
    if block.get("chunk_generated") and block.get("chunk_finalized") != CHUNK_FINALIZED_DONE:
        codes.append("generation_incomplete" if block.get("chunk_finalized") in (0, 1) else "generation_unconfirmed")
    return codes


def footprint_issues(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Explain incomplete blocks across every column and required body layer."""

    issues: dict[str, dict[str, Any]] = {}

    def add(code: str, block: dict[str, Any], role: str, *, block_name: str = "") -> None:
        if code not in issues:
            issues[code] = placement_issue(code, block_name=block_name)
        issue = issues[code]
        chunk_x, chunk_z = block.get("chunk_x"), block.get("chunk_z")
        if isinstance(chunk_x, int) and isinstance(chunk_z, int):
            chunk = {"x": chunk_x, "z": chunk_z}
            if chunk not in issue["chunks"]:
                issue["chunks"].append(chunk)
        issue["block_count"] += 1
        if issue["sample_block"] is None:
            issue["sample_block"] = {"x": block.get("block_x"), "y": block.get("block_y"), "z": block.get("block_z"), "role": role}

    for column in columns:
        if column.get("block_check") == "invalid_position" and "position_out_of_range" not in issues:
            issues["position_out_of_range"] = placement_issue("position_out_of_range")
        blocks = column.get("blocks") or {}
        for role, block in blocks.items():
            for code in _block_issue_codes(block):
                add(code, block, role)
        if column.get("center"):
            floor = (column.get("block_names") or {}).get("floor")
            if floor and not is_confirmed_full_support_surface(floor):
                code = "support_state_unknown" if support_surface_shape_is_state_dependent(floor) else "support_shape_unknown"
                add(code, blocks.get("floor") or {}, "floor", block_name=floor)
    return list(issues.values())
