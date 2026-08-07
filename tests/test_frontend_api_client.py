from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_frontend_api_client_localizes_structured_errors_and_keeps_legacy_errors() -> None:
    source = textwrap.dedent(
        r"""
        const assert = require("assert");
        const fs = require("fs");
        const vm = require("vm");
        const catalog = JSON.parse(fs.readFileSync("static/i18n/en.json", "utf8"));
        const t = (text, params) => String(catalog[text] ?? text).replace(
            /\{(\w+)\}/g,
            (match, key) => params && key in params ? String(params[key]) : match,
        );
        const context = { window: { t } };
        vm.runInNewContext(fs.readFileSync("static/api_client.js", "utf8"), context, {
            filename: "static/api_client.js",
        });

        (async () => {
            const client = context.window.MCBEApiClient.createApiClient();
            const response = {
                ok: false,
                status: 400,
                headers: { get: () => "application/json" },
                text: async () => JSON.stringify({
                    success: false,
                    code: "invalid_slot",
                    params: { slot: 7 },
                    message_key: "Ungültiger Slot: {slot}",
                    message: "Ungültiger Slot: 7",
                    error: "Ungültiger Slot: 7",
                }),
            };
            const structured = await client.parseJsonResponse(response);
            assert.strictEqual(structured.code, "invalid_slot");
            assert.strictEqual(structured.error, "Invalid slot: 7");
            assert.strictEqual(structured.message, "Invalid slot: 7");
            assert.strictEqual(client.buildErrorMessage(structured), "Invalid slot: 7");
            assert.strictEqual(client.buildErrorMessage({ error: "Legacy failure" }), "Legacy failure");
        })().catch(error => {
            console.error(error);
            process.exitCode = 1;
        });
        """
    )
    result = subprocess.run(["node", "-e", source], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr + result.stdout
