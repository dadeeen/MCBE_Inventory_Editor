from __future__ import annotations

import textwrap

from tests.node_runner import run_node


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
    run_node(source)


def test_frontend_error_context_frames_only_reasons_without_a_specific_message() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/api_client.js", "utf8"), context, {
                filename: "static/api_client.js",
            });
            const client = context.window.MCBEApiClient;
            const inSave = data => client.errorMessageInContext(data, reason => `Fehler beim Speichern: ${reason}`);
            const specific = {
                success: false,
                message_key: "Fehler beim Speichern des Spielers: {error}",
                params: { error: "Datenbank gesperrt" },
                message: "Fehler beim Speichern des Spielers: Datenbank gesperrt",
                error: "Fehler beim Speichern des Spielers: Datenbank gesperrt",
                details: "Welt ist geöffnet",
            };
            const generic = {
                success: false,
                message_key: "Interner Serverfehler",
                message: "Interner Serverfehler",
                error: "Interner Serverfehler",
            };

            assert.strictEqual(client.hasBackendErrorMessage(specific), true);
            assert.strictEqual(inSave(specific), "Fehler beim Speichern des Spielers: Datenbank gesperrt");
            assert.strictEqual(inSave({ success: false, message: "Welt ist schreibgeschützt." }), "Welt ist schreibgeschützt.");

            for (const key of ["Interner Serverfehler", "Seite nicht gefunden.", "Unbekannter Fehler"]) {
                assert.strictEqual(client.hasBackendErrorMessage({ message_key: key, message: key }), false, key);
            }
            assert.strictEqual(inSave(generic), "Fehler beim Speichern: Interner Serverfehler");
            assert.strictEqual(inSave({ success: false, error: "kaputt" }), "Fehler beim Speichern: kaputt");
            assert.strictEqual(
                inSave({ success: false, response_unreadable: true, message: "x", error: "HTTP 502: Leere Serverantwort" }),
                "Fehler beim Speichern: HTTP 502: Leere Serverantwort",
            );
            assert.strictEqual(
                inSave({ success: false, error_message_missing: true, message: "HTTP 500: Anfrage fehlgeschlagen", error: "HTTP 500: Anfrage fehlgeschlagen" }),
                "Fehler beim Speichern: HTTP 500: Anfrage fehlgeschlagen",
            );
            assert.strictEqual(inSave({ success: false }), "Fehler beim Speichern: Unbekannter Fehler");
            assert.strictEqual(inSave(null), "Fehler beim Speichern: Unbekannter Fehler");

            // buildErrorMessage keeps details of a specific message and puts a
            // technical reason behind the caller's context.
            assert.strictEqual(
                client.buildErrorMessage(specific, "Spieler konnte nicht geladen werden."),
                "Fehler beim Speichern des Spielers: Datenbank gesperrt — Welt ist geöffnet",
            );
            assert.strictEqual(
                client.buildErrorMessage(generic, "Spieler konnte nicht geladen werden."),
                "Spieler konnte nicht geladen werden. (Interner Serverfehler)",
            );
            assert.strictEqual(client.buildErrorMessage(generic), "Interner Serverfehler");
            assert.strictEqual(client.buildErrorMessage({ error: "Ordner fehlt" }, "Ordner fehlt"), "Ordner fehlt");
            assert.strictEqual(client.buildErrorMessage({}, "Welt konnte nicht geladen werden."), "Welt konnte nicht geladen werden.");
            assert.strictEqual(client.buildErrorMessage(undefined), "Unbekannter Fehler");
            """
        )
    )


def test_frontend_api_client_marks_unreadable_and_messageless_error_answers() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/api_client.js", "utf8"), context, {
                filename: "static/api_client.js",
            });
            const client = context.window.MCBEApiClient.createApiClient();
            const answer = (status, body, type = "application/json") => client.parseJsonResponse({
                ok: status >= 200 && status < 300,
                status,
                headers: { get: () => type },
                text: async () => body,
            });

            (async () => {
                const html = await answer(502, "<html><body>Bad Gateway from proxy</body></html>", "text/html");
                assert.strictEqual(html.response_unreadable, true);
                assert.strictEqual(html.error, "HTTP 502: Serverantwort ist kein JSON");
                assert.strictEqual(client.hasBackendErrorMessage(html), false);

                const empty = await answer(504, "", "text/plain");
                assert.strictEqual(empty.error, "HTTP 504: Leere Serverantwort");
                assert.strictEqual(client.hasBackendErrorMessage(empty), false);

                const text = await answer(503, "Service Unavailable", "text/plain");
                assert.strictEqual(text.error, "Service Unavailable");
                assert.strictEqual(client.hasBackendErrorMessage(text), false);

                const messageless = await answer(500, "{}");
                assert.strictEqual(messageless.error_message_missing, true);
                assert.strictEqual(messageless.error, "HTTP 500: Anfrage fehlgeschlagen");
                assert.strictEqual(client.hasBackendErrorMessage(messageless), false);

                const structured = await answer(409, JSON.stringify({
                    success: false,
                    message_key: "Server läuft noch.",
                    message: "Server läuft noch.",
                    error: "Server läuft noch.",
                }));
                assert.strictEqual(structured.error_message_missing, undefined);
                assert.strictEqual(client.hasBackendErrorMessage(structured), true);
                assert.strictEqual(
                    client.errorMessageInContext(structured, reason => `Fehler: ${reason}`),
                    "Server läuft noch.",
                );
            })().catch(error => {
                console.error(error);
                process.exitCode = 1;
            });
            """
        )
    )
