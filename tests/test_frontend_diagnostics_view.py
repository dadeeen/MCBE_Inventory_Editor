import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_node(source: str) -> None:
    result = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_frontend_diagnostics_view_status_chip_html_escapes_text() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const diagnosticsCode = fs.readFileSync("static/diagnostics_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(diagnosticsCode, context, { filename: "static/diagnostics_view.js" });

            const view = context.window.MCBEDiagnosticsView;
            const ok = view.statusChipHtml("Modus", "local", ["local"]);
            assert.ok(ok.includes("diagnostic-chip ok"));
            assert.ok(ok.includes("<span>Modus</span>"));
            assert.ok(ok.includes("<strong>local</strong>"));

            const warn = view.statusChipHtml("Status", "unknown");
            assert.ok(warn.includes("diagnostic-chip warn"));

            const escaped = view.statusChipHtml("<Label>", "Wert & mehr", []);
            assert.ok(escaped.includes("&lt;Label&gt;"));
            assert.ok(escaped.includes("Wert &amp; mehr"));
            assert.ok(!escaped.includes("<Label>"));
            """
        )
    )


def test_frontend_diagnostics_view_status_message_html_escapes_text_and_level() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const diagnosticsCode = fs.readFileSync("static/diagnostics_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(diagnosticsCode, context, { filename: "static/diagnostics_view.js" });

            const view = context.window.MCBEDiagnosticsView;
            assert.strictEqual(
                view.statusMessageHtml("Logs werden geladen..."),
                '<div class="no-backups">Logs werden geladen...</div>',
            );
            assert.strictEqual(
                view.statusMessageHtml("<Fehler & mehr>", { level: "error" }),
                '<div class="no-backups error">&lt;Fehler &amp; mehr&gt;</div>',
            );
            """
        )
    )


def test_frontend_diagnostics_view_runtime_diagnostics_html_formats_and_escapes_details() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const diagnosticsCode = fs.readFileSync("static/diagnostics_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(diagnosticsCode, context, { filename: "static/diagnostics_view.js" });

            const view = context.window.MCBEDiagnosticsView;
            assert.strictEqual(
                view.runtimeDiagnosticsHtml({ success: false }),
                '<div class="no-backups error">Diagnose konnte nicht geladen werden.</div>',
            );

            const html = view.runtimeDiagnosticsHtml({
                success: true,
                mode: "local",
                worlds_root: {
                    status: "ok",
                    message: "<root ok>",
                    contains_world_hint: true,
                },
                write_gate_setup: {
                    status: "configured",
                    local_world_access_warning: true,
                },
                write_gate: {
                    reason: "Nur Test & Schutz",
                    server_status: { status: "offline" },
                },
                data_root: {
                    path: "C:\\Data & Root",
                    writable: true,
                },
                distribution: {
                    kind: "source",
                    project_version: "1.2.3",
                },
            }, { worldsRoot: "C:\\Worlds <Root>" });

            assert.ok(html.includes("diagnostic-grid"));
            assert.ok(html.includes("diagnostic-chip ok"));
            assert.ok(html.includes("<strong>gefunden</strong>"));
            assert.ok(html.includes("C:\\Worlds &lt;Root&gt;"));
            assert.ok(html.includes("&lt;root ok&gt;"));
            assert.ok(html.includes("Nur Test &amp; Schutz"));
            assert.ok(html.includes("diagnostic-warning"));
            assert.ok(html.includes("C:\\Data &amp; Root"));
            assert.ok(!html.includes("<root ok>"));
            """
        )
    )


def test_frontend_diagnostics_view_recent_logs_html_formats_and_escapes_rows() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const diagnosticsCode = fs.readFileSync("static/diagnostics_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(diagnosticsCode, context, { filename: "static/diagnostics_view.js" });

            const view = context.window.MCBEDiagnosticsView;
            assert.strictEqual(
                view.recentLogsHtml([]),
                '<div class="no-backups">Keine Logs im aktuellen Serverprozess.</div>',
            );

            const html = view.recentLogsHtml([
                {
                    level: "INFO",
                    logger: "werkzeug",
                    message: 'GET /api/heartbeat "ok"',
                    ts: "2026-06-28T10:20:30+0200",
                },
                {
                    level: "ERROR",
                    logger: "mcbe_editor.main",
                    message: "<boom & fail>",
                    traceback: "Trace <line>",
                    ts: "bad-date",
                },
            ]);

            assert.ok(html.startsWith('<div class="log-list">'));
            assert.ok(html.includes("1 automatische HTTP-Status-/Heartbeat-Zeile(n) enthalten."));
            assert.ok(html.includes('class="log-row error app"'));
            assert.ok(html.includes('&lt;boom &amp; fail&gt;'));
            assert.ok(html.includes('<pre class="log-trace">Trace &lt;line&gt;</pre>'));
            assert.ok(html.includes('class="log-row info http-noise"'));
            assert.ok(html.includes("HTTP automatisch"));
            assert.ok(!html.includes("<boom & fail>"));
            """
        )
    )


def test_frontend_diagnostics_view_audit_events_html_formats_and_escapes_rows() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const diagnosticsCode = fs.readFileSync("static/diagnostics_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(diagnosticsCode, context, { filename: "static/diagnostics_view.js" });

            const view = context.window.MCBEDiagnosticsView;
            assert.strictEqual(
                view.auditEventsHtml([], { enabled: false }),
                '<div class="no-backups">Audit-Log ist deaktiviert.</div>',
            );
            assert.strictEqual(
                view.auditEventsHtml([], { enabled: true }),
                '<div class="no-backups">Noch keine Audit-Ereignisse vorhanden.</div>',
            );
            assert.ok(
                view.auditEventsHtml([], { enabled: true, healthy: false })
                    .includes("Audit-Log kann derzeit nicht geschrieben werden."),
            );
            assert.ok(
                view.auditEventsHtml([], { enabled: false, healthy: false })
                    .includes("Audit-Log kann derzeit nicht geschrieben werden."),
            );

            const html = view.auditEventsHtml([
                {
                    action: "world.load",
                    outcome: "OK",
                    ts: "2026-06-29T08:10:11+0200",
                    username: "Steve <Admin>",
                    remote: "127.0.0.1",
                    world: { name: "Welt & Test" },
                    player: { preview: "Alex" },
                    details: { path: "C:\\World <One>" },
                },
                {
                    action: "<save>",
                    outcome: "ERROR",
                    ts: "bad-date",
                    error: "Fehler & mehr",
                },
            ], { enabled: true, healthy: false });

            assert.ok(html.includes("Audit-Log kann derzeit nicht geschrieben werden."));
            assert.ok(html.includes('class="audit-row error"'));
            assert.ok(html.includes("&lt;save&gt;"));
            assert.ok(html.includes("Fehler Fehler &amp; mehr"));
            assert.ok(html.includes('class="audit-row ok"'));
            assert.ok(html.includes("Benutzer Steve &lt;Admin&gt;"));
            assert.ok(html.includes("Welt Welt &amp; Test"));
            assert.ok(html.includes("C:\\\\World &lt;One&gt;"));
            assert.ok(!html.includes("Steve <Admin>"));
            assert.ok(!html.includes("<save>"));
            """
        )
    )
