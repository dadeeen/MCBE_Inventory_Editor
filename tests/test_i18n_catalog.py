from __future__ import annotations

import ast
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "static" / "i18n" / "en.json"
PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")
JS_LITERAL_T_RE = re.compile(r'\bt\(\s*("(?:[^"\\]|\\.)*")', re.DOTALL)
TEMPLATE_LITERAL_T_RE = re.compile(r"\bt\(\s*(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')", re.DOTALL)
GERMAN_TEXT_RE = re.compile(
    r"[ÄÖÜäöüß]|\b(?:alle|als|auf|aus|bei|bitte|der|die|das|eine|einen|für|kein|keine|mit|nach|nicht|"
    r"oder|prüfen|schließen|speichern|spieler|über|und|welt|werkzeuge|wird|werden|zurück)\b",
    re.IGNORECASE,
)


class _VisibleTemplateTextParser(HTMLParser):
    _IGNORED_TAGS = {"script", "style", "code", "kbd"}
    _VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in self._VOID_TAGS:
            self.stack.append(tag)
        if any(parent in self._IGNORED_TAGS for parent in self.stack):
            return
        for name, value in attrs:
            if name in {"title", "aria-label", "placeholder", "alt"} and value:
                self._add(value)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.stack:
            index = len(self.stack) - 1 - self.stack[::-1].index(tag)
            del self.stack[index:]

    def handle_data(self, data: str) -> None:
        if not any(parent in self._IGNORED_TAGS for parent in self.stack):
            self._add(data)

    def _add(self, value: str) -> None:
        without_jinja = re.sub(r"\{[{%].*?[}%]\}", "", value, flags=re.DOTALL)
        normalized = " ".join(without_jinja.split()).strip()
        if normalized:
            self.values.append(normalized)


def _source_files(directory: Path, pattern: str) -> list[Path]:
    """Discover translatable sources recursively.

    A non-recursive glob would silently drop a future subpackage or asset folder
    out of the catalog check -- the check would still pass, just cover less.  The
    empty-result assertion closes the other half of that hole: a moved or renamed
    directory must fail loudly instead of reducing the scan to nothing.
    """

    found = sorted(path for path in directory.rglob(pattern) if "__pycache__" not in path.parts)
    assert found, f"No {pattern} sources under {directory}; the catalog check would pass vacuously."
    return found


def _load_catalog_with_unique_keys() -> dict[str, str]:
    def unique_object(pairs: list[tuple[str, str]]) -> dict[str, str]:
        result: dict[str, str] = {}
        for key, value in pairs:
            assert key not in result, f"Duplicate i18n catalog key: {key}"
            result[key] = value
        return result

    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"), object_pairs_hook=unique_object)


def _template_literal(raw: str) -> str:
    if raw.startswith('"'):
        return json.loads(raw)
    return raw[1:-1].replace("\\'", "'").replace("\\\\", "\\")


def test_source_discovery_reaches_nested_directories_and_refuses_an_empty_scan(tmp_path: Path) -> None:
    """The catalog check is only worth as much as the file list it walks.

    With a non-recursive glob a new subpackage would drop out of the check
    without any test turning red, so the discovery itself needs a guard.
    """

    (tmp_path / "nested" / "deeper").mkdir(parents=True)
    (tmp_path / "top.py").write_text("", encoding="utf-8")
    (tmp_path / "nested" / "middle.py").write_text("", encoding="utf-8")
    (tmp_path / "nested" / "deeper" / "leaf.py").write_text("", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cached.py").write_text("", encoding="utf-8")

    found = {path.name for path in _source_files(tmp_path, "*.py")}

    assert found == {"top.py", "middle.py", "leaf.py"}

    # An empty result must fail loudly instead of silently checking nothing.
    with pytest.raises(AssertionError, match="pass vacuously"):
        _source_files(tmp_path, "*.never")


def test_english_catalog_preserves_all_placeholders_and_has_unique_keys() -> None:
    catalog = _load_catalog_with_unique_keys()

    for source, translation in catalog.items():
        assert sorted(PLACEHOLDER_RE.findall(source)) == sorted(PLACEHOLDER_RE.findall(translation)), source


def test_all_direct_translation_literals_exist_in_english_catalog() -> None:
    catalog = _load_catalog_with_unique_keys()
    referenced: list[tuple[Path, int, str]] = []

    for path in _source_files(ROOT / "static", "*.js"):
        source = path.read_text(encoding="utf-8")
        for match in JS_LITERAL_T_RE.finditer(source):
            referenced.append((path, source.count("\n", 0, match.start()) + 1, json.loads(match.group(1))))

    for path in _source_files(ROOT / "templates", "*.html"):
        source = path.read_text(encoding="utf-8")
        for match in TEMPLATE_LITERAL_T_RE.finditer(source):
            referenced.append((path, source.count("\n", 0, match.start()) + 1, _template_literal(match.group(1))))

    for path in [ROOT / "main.py", *_source_files(ROOT / "mcbe_editor", "*.py")]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            function_name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if function_name == "t" and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                referenced.append((path, node.lineno, node.args[0].value))

    missing = [f"{path.relative_to(ROOT)}:{line}: {key}" for path, line, key in referenced if key not in catalog]
    assert not missing, "Missing English catalog entries:\n" + "\n".join(missing)


def test_templates_have_no_raw_translatable_visible_text() -> None:
    catalog = _load_catalog_with_unique_keys()
    raw_values: list[tuple[Path, str]] = []
    for path in _source_files(ROOT / "templates", "*.html"):
        parser = _VisibleTemplateTextParser()
        parser.feed(path.read_text(encoding="utf-8"))
        raw_values.extend((path, value) for value in parser.values)

    catalogued = [f"{path.relative_to(ROOT)}: {value}" for path, value in raw_values if value in catalog]
    german = [f"{path.relative_to(ROOT)}: {value}" for path, value in raw_values if GERMAN_TEXT_RE.search(value)]
    assert not catalogued, "Raw catalogued template text must use explicit t():\n" + "\n".join(catalogued)
    assert not german, "Raw German template text must use explicit t():\n" + "\n".join(german)
