"""Keep explicit form labels attached to real, uniquely identified controls."""

from html.parser import HTMLParser
from pathlib import Path


class _ControlReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = {}
        self.label_targets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        element_id = attrs.get("id")
        if element_id:
            assert element_id not in self.elements, f"Duplicate element ID: {element_id}"
            self.elements[element_id] = (tag, attrs.get("type"))
        if tag == "label" and attrs.get("for"):
            self.label_targets.append(attrs["for"])


def test_index_form_labels_reference_existing_controls():
    template = Path(__file__).resolve().parents[1] / "templates" / "index.html"
    parser = _ControlReferences()
    parser.feed(template.read_text(encoding="utf-8"))
    assert parser.label_targets, "No explicit form labels found; the check would be empty."
    labelable_tags = {"button", "input", "meter", "output", "progress", "select", "textarea"}
    for target in parser.label_targets:
        assert target in parser.elements, f"Label points to a missing control: {target}"
        tag, input_type = parser.elements[target]
        assert tag in labelable_tags and (tag != "input" or input_type != "hidden"), f"Label target is not a labelable control: {target}"
