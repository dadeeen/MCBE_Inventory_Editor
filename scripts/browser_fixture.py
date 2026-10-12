"""Prepare trusted project templates for isolated browser fixtures.

This removes automatic script/style loading before a smoke script adds its
chosen assets. It is not a sanitizer for untrusted HTML.
"""

from __future__ import annotations

from html.parser import HTMLParser


class _FixtureAssetsParser(HTMLParser):
    def __init__(self, *, keep_json: bool):
        super().__init__(convert_charrefs=False)
        self.keep_json = keep_json
        self.skip_script = False
        self.output: list[str] = []

    def _append(self, text: str) -> None:
        if not self.skip_script:
            self.output.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "link":
            return
        if tag == "script":
            script_type = (dict(attrs).get("type") or "").strip().lower()
            self.skip_script = not (self.keep_json and script_type == "application/json")
        self._append(self.get_starttag_text())

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag == "script":
            self.skip_script = False

    def handle_endtag(self, tag: str) -> None:
        if self.skip_script:
            if tag == "script":
                self.skip_script = False
            return
        if tag != "link":
            self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self._append(data)

    def handle_entityref(self, name: str) -> None:
        self._append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self._append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self._append(f"<!{decl}>")


def without_automatic_assets(source: str, *, keep_json: bool = False) -> str:
    parser = _FixtureAssetsParser(keep_json=keep_json)
    parser.feed(source)
    parser.close()
    return "".join(parser.output)
