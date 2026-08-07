import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_inventory_clipboard_help_renderer_is_model_driven_and_idempotent() -> None:
    source = textwrap.dedent(
        r"""
        const assert = require("assert");
        const fs = require("fs");
        const vm = require("vm");

        class Node {
            constructor(tag) {
                this.tagName = String(tag).toUpperCase();
                this.children = [];
                this.dataset = {};
                this.parentNode = null;
                this.textContent = "";
            }
            appendChild(node) { node.parentNode = this; this.children.push(node); return node; }
            append(...nodes) { nodes.forEach(node => this.appendChild(node)); }
            walk(visitor) { this.children.forEach(node => { visitor(node); node.walk(visitor); }); }
            find(predicate) { let found = null; this.walk(node => { if (!found && predicate(node)) found = node; }); return found; }
            querySelector(selector) {
                if (selector === "kbd") return this.find(node => node.tagName === "KBD");
                if (selector === '[data-inventory-clipboard-help="true"]') {
                    return this.find(node => node.dataset.inventoryClipboardHelp === "true");
                }
                return null;
            }
            querySelectorAll(selector) {
                const matches = [];
                const tag = String(selector).toUpperCase();
                this.walk(node => { if (node.tagName === tag) matches.push(node); });
                return matches;
            }
            insertAdjacentElement(position, node) {
                assert.strictEqual(position, "afterend");
                const index = this.parentNode.children.indexOf(this);
                node.parentNode = this.parentNode;
                this.parentNode.children.splice(index + 1, 0, node);
            }
        }

        function row(shortcut) {
            const tr = new Node("tr");
            const td = new Node("td");
            const kbd = new Node("kbd");
            kbd.textContent = shortcut;
            td.appendChild(kbd);
            tr.append(td, new Node("td"));
            return tr;
        }

        const table = new Node("table");
        table.append(row("Strg+Z"), row("Strg+F"), row("Strg"), row("Rechtsklick"));
        const translations = new Map([
            ["Strg", "Ctrl"], ["Rechtsklick", "Right-click"], ["📋 Kopieren", "📋 Copy"],
            ["📄 Einfügen", "📄 Paste"], ["Slot ziehen & ablegen", "Drag & drop a slot"],
            ["Kopieren", "Copy"], ["Inventar", "Inventory"],
        ]);
        const context = { window: { t: text => translations.get(text) || String(text) } };
        const doc = {
            querySelector(selector) { assert.strictEqual(selector, "#helpOverlay .help-table"); return table; },
            createElement(tag) { return new Node(tag); },
        };
        vm.runInNewContext(fs.readFileSync("static/app_bootstrap.js", "utf8"), context);
        const help = context.window.MCBEAppBootstrap;

        assert.deepStrictEqual(Array.from(help.inventoryClipboardHelpModel().rows, item => item.id), [
            "copy-item", "paste-item", "paste-system", "copy-drag",
        ]);
        assert.strictEqual(help.installInventoryClipboardHelp(doc), true);
        const keys = table.querySelectorAll("kbd").map(node => node.textContent);
        for (const key of ["Ctrl+Z", "Ctrl+F", "Ctrl", "Right-click", "Ctrl+C", "Ctrl+Shift+V", "Ctrl+V", "Ctrl + Drag & drop a slot"]) {
            assert.ok(keys.includes(key), key);
        }
        const rowCount = table.querySelectorAll("tr").length;
        assert.strictEqual(help.installInventoryClipboardHelp(doc), false);
        assert.strictEqual(table.querySelectorAll("tr").length, rowCount);
        """
    )
    result = subprocess.run(["node", "-e", source], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr + result.stdout
