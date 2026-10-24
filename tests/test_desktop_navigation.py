import json
import tempfile
import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcbe_editor.desktop_navigation import DesktopNavigation
from tests.node_runner import run_node

URL = "http://127.0.0.1:5001/"


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, callback):
        self.handlers.append(callback)
        return self

    def __isub__(self, callback):
        self.handlers.remove(callback)
        return self

    def emit(self, args):
        for callback in self.handlers:
            callback(None, args)


def native_window():
    popup = Mock()
    script_notify = Mock()
    core = SimpleNamespace(
        Source=URL,
        Settings=SimpleNamespace(AreHostObjectsAllowed=True),
        Navigate=Mock(),
        FrameNavigationStarting=Event(),
        WebResourceRequested=Event(),
        Environment=SimpleNamespace(CreateWebResourceResponse=Mock(return_value="blocked response")),
        NewWindowRequested=Event(),
    )
    core.NewWindowRequested += popup
    view = SimpleNamespace(CoreWebView2=core, NavigationStarting=Event(), CoreWebView2InitializationCompleted=Event(), WebMessageReceived=Event())
    view.WebMessageReceived += script_notify
    window = SimpleNamespace(native=SimpleNamespace(webview=view, browser=SimpleNamespace(on_new_window_request=popup, on_script_notify=script_notify)))
    return window, core, view, popup


@pytest.mark.parametrize(
    "url,allowed",
    [
        (URL, True),
        (URL + "login?next=%2F#login", True),
        ("http://127.0.0.1:5001", True),
        ("http://localhost:5001/", False),
        ("http://127.0.0.1:5002/", False),
        ("https://127.0.0.1:5001/", False),
        ("http://127.0.0.1:5001.external.invalid/", False),
        ("http://127.0.0.1:5001@external.invalid/", False),
        ("http://user@127.0.0.1:5001/", False),
        ("http://127.0.0.1:5001\\@external.invalid/", False),
        ("http://127.0.0.1:bad/", False),
        ("http://127.0.0.1:65536/", False),
        ("\nhttp://127.0.0.1:5001/", False),
        ("file:///C:/Windows/win.ini", False),
        ("data:text/html,example", False),
        ("javascript:alert(1)", False),
        ("about:blank", False),
        (None, False),
    ],
)
def test_only_exact_editor_origin_is_a_document(url, allowed):
    assert DesktopNavigation(Mock(), URL).allows(url) is allowed


@pytest.mark.parametrize("initialized", [False, True])
def test_native_hooks_precede_app_navigation_and_replace_unrestricted_popup(initialized):
    window, core, view, popup = native_window()
    if not initialized:
        view.CoreWebView2 = None
    policy = DesktopNavigation(window, URL)
    policy.install()
    if not initialized:
        core.Navigate.assert_not_called()
        # No documents may be loaded before all core hooks are ready.
        early = SimpleNamespace(Uri=URL, IsUserInitiated=False, IsRedirected=False, Cancel=False)
        view.NavigationStarting.emit(early)
        assert early.Cancel
        view.CoreWebView2 = core
        view.CoreWebView2InitializationCompleted.emit(SimpleNamespace(IsSuccess=True))
    policy.wait_ready(0)
    core.Navigate.assert_called_once_with(URL)
    assert core.Settings.AreHostObjectsAllowed is False
    assert popup not in core.NewWindowRequested.handlers
    assert policy.on_new_window in core.NewWindowRequested.handlers
    assert policy.on_frame_navigation in core.FrameNavigationStarting.handlers


@pytest.mark.parametrize(
    "target,user,redirect,source,external",
    [
        ("https://example.invalid/help", True, False, URL, False),
        ("http://example.invalid/help", True, False, URL, False),
        ("https://example.invalid/help", False, False, URL, False),
        ("https://example.invalid/help", True, True, URL, False),
        ("https://example.invalid/help", True, False, "about:blank", False),
        ("file:///C:/Windows/win.ini", True, False, URL, False),
        ("ms-settings:privacy", True, False, URL, False),
        ("javascript:alert(1)", True, False, URL, False),
        ("data:text/html,hello", True, False, URL, False),
        ("https://user:password@example.invalid/", True, False, URL, False),
    ],
)
def test_foreign_navigation_never_replaces_editor_or_launches_a_browser(monkeypatch, target, user, redirect, source, external):
    opened = Mock()
    monkeypatch.setattr("mcbe_editor.desktop_navigation.webbrowser.open", opened)
    window, core, view, _ = native_window()
    policy = DesktopNavigation(window, URL)
    policy.install()
    core.Source = source
    args = SimpleNamespace(Uri=target, IsUserInitiated=user, IsRedirected=redirect, Cancel=False)
    view.NavigationStarting.emit(args)
    assert args.Cancel
    assert opened.call_args_list == ([((target,), {})] if external else [])


@pytest.mark.parametrize("target,allowed", [(URL + "versions", True), ("https://example.invalid/", False), ("data:text/html,x", False)])
def test_frame_policy_never_opens_external_browser(monkeypatch, target, allowed):
    opened = Mock()
    monkeypatch.setattr("mcbe_editor.desktop_navigation.webbrowser.open", opened)
    window, core, _, _ = native_window()
    policy = DesktopNavigation(window, URL)
    policy.install()
    args = SimpleNamespace(Uri=target, Cancel=False)
    core.FrameNavigationStarting.emit(args)
    assert args.Cancel is not allowed
    opened.assert_not_called()


@pytest.mark.parametrize("target,blocked", [(URL + "versions", False), ("https://example.invalid/", True)])
def test_foreign_document_requests_are_answered_without_network_access(target, blocked):
    window, core, _, _ = native_window()
    policy = DesktopNavigation(window, URL)
    policy.install()
    args = SimpleNamespace(ResourceContext="Document", Request=SimpleNamespace(Uri=target), Response=None)
    core.WebResourceRequested.emit(args)
    assert args.Response == ("blocked response" if blocked else None)


@pytest.mark.parametrize("user", [False, True])
@pytest.mark.parametrize("target", [URL + "versions", "https://example.invalid/", "ms-settings:privacy"])
def test_popups_are_handled_without_unrestricted_launcher(monkeypatch, user, target):
    opened = Mock()
    monkeypatch.setattr("mcbe_editor.desktop_navigation.webbrowser.open", opened)
    window, core, _, popup = native_window()
    policy = DesktopNavigation(window, URL)
    policy.install()
    core.Navigate.reset_mock()
    args = SimpleNamespace(Uri=target, IsUserInitiated=user, Handled=False)
    core.NewWindowRequested.emit(args)
    assert args.Handled
    popup.assert_not_called()
    assert core.Navigate.called is (user and target.startswith(URL))
    opened.assert_not_called()


@pytest.mark.parametrize(
    "source,nonce,url,expected",
    [
        (URL, True, "https://example.invalid/", True),
        (URL, False, "https://example.invalid/", False),
        (URL, "nicht-ascii-ö", "https://example.invalid/", False),
        ("http://127.0.0.1:5002/", True, "https://example.invalid/", False),
        (URL, True, "ms-settings:privacy", False),
        (URL, True, "file:///C:/test.txt", False),
        (URL, True, URL, False),
    ],
)
def test_external_link_message_requires_origin_nonce_and_http_url(monkeypatch, source, nonce, url, expected):
    import json

    opened = Mock()
    monkeypatch.setattr("mcbe_editor.desktop_navigation.webbrowser.open", opened)
    window, _, view, _ = native_window()
    policy = DesktopNavigation(window, URL)
    policy.install()
    args = SimpleNamespace(
        Source=source,
        WebMessageAsJson=json.dumps(
            {
                "type": "mcbe.external_link",
                "nonce": policy._link_nonce if nonce is True else nonce,
                "url": url,
            }
        ),
    )
    view.WebMessageReceived.emit(args)
    assert opened.called is expected
    window.native.browser.on_script_notify.assert_not_called()


def test_missing_native_api_fails_closed_before_app_is_loaded():
    window, core, view, _ = native_window()
    core.NewWindowRequested.handlers.clear()  # incompatible pywebview adapter
    policy = DesktopNavigation(window, URL)
    policy.install()
    with pytest.raises(RuntimeError, match="Navigationssperre|navigation protection"):
        policy.wait_ready(0)
    core.Navigate.assert_not_called()
    args = SimpleNamespace(Uri=URL, IsUserInitiated=False, IsRedirected=False, Cancel=False)
    view.NavigationStarting.emit(args)
    assert args.Cancel


def test_external_link_listener_accepts_only_trusted_primary_and_middle_clicks():
    window, _, _, _ = native_window()
    window.get_current_url = Mock(return_value=URL)
    window.evaluate_js = Mock()
    policy = DesktopNavigation(window, URL)
    policy.installed = True
    policy.prepare_links()
    script = window.evaluate_js.call_args.args[0]
    run_node(
        r"""
        const assert = require('node:assert/strict');
        const vm = require('node:vm');
        const handlers = {}, messages = [];
        const context = {
            URL, location: {origin: 'http://127.0.0.1:5001'},
            window: {chrome: {webview: {postMessage: value => messages.push(value)}}},
            document: {
                documentElement: {lang: 'en'},
                addEventListener: (type, fn) => { assert.equal(handlers[type], undefined); handlers[type] = fn; },
            },
        };
        const script = LINK_SCRIPT;
        assert.equal(vm.runInNewContext(script, context), 'en');
        assert.equal(vm.runInNewContext(script, context), 'en'); // No duplicate launchers.
        for (const sample of [
            {type:'click', button:0, allowed:true},
            {type:'auxclick', button:1, allowed:true},
            {type:'auxclick', button:2},
            {type:'click', button:1},
            {type:'auxclick', button:0},
            {type:'auxclick', button:1, isTrusted:false},
            {type:'click', button:0, isTrusted:false},
            {type:'auxclick', button:1, defaultPrevented:true},
            {type:'auxclick', button:1, download:true},
            {type:'auxclick', button:1, href:'http://127.0.0.1:5001/local'},
            {type:'auxclick', button:1, href:'https://user:password@example.invalid/'},
            {type:'auxclick', button:1, href:'file:///C:/synthetic.txt'},
        ]) {
            messages.length = 0;
            let prevented = false;
            const anchor = {href:sample.href || 'https://example.invalid/help', hasAttribute: () => !!sample.download};
            const event = {isTrusted:true, defaultPrevented:false, ...sample,
                target:{closest: () => anchor}, preventDefault: () => {prevented = true;}};
            handlers[sample.type](event);
            assert.equal(messages.length, sample.allowed ? 1 : 0, JSON.stringify(sample));
            assert.equal(prevented, !!sample.allowed);
        }
        """.replace("LINK_SCRIPT", json.dumps(script))
    )


@pytest.mark.parametrize("selected", ["de", "en", "fr", None])
def test_native_language_follows_only_supported_editor_document_languages(selected):
    window, _, _, _ = native_window()
    window.get_current_url = Mock(return_value=URL)
    window.evaluate_js = Mock(return_value=selected)
    remember = Mock()
    policy = DesktopNavigation(window, URL, on_locale=remember)
    policy.installed = True
    policy.prepare_links()
    if selected in ("de", "en"):
        remember.assert_called_once_with(selected)
    else:
        remember.assert_not_called()


@pytest.mark.parametrize("urls", [["https://example.invalid/"], [URL, "https://example.invalid/"]])
def test_native_language_ignores_a_foreign_document(urls):
    window, _, _, _ = native_window()
    window.get_current_url = Mock(side_effect=urls)
    window.evaluate_js = Mock(return_value="en")
    remember = Mock()
    policy = DesktopNavigation(window, URL, on_locale=remember)
    policy.installed = True
    policy.prepare_links()
    remember.assert_not_called()


@contextmanager
def native_profile_directory():
    temporary = tempfile.TemporaryDirectory(prefix="mcbe-navigation-")
    try:
        yield temporary.name
    finally:
        # WebView2 can release its profile locks after the window has closed.
        deadline = time.monotonic() + 5
        while True:
            try:
                temporary.cleanup()
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)


@pytest.mark.parametrize("probe_fails", [False, True])
def test_native_profile_cleanup_retries_locks_without_hiding_probe_failures(monkeypatch, probe_fails):
    temporary = SimpleNamespace(name="synthetic-profile", cleanup=Mock(side_effect=[PermissionError("locked"), None]))
    monkeypatch.setattr(tempfile, "TemporaryDirectory", Mock(return_value=temporary))
    sleep = Mock()
    monkeypatch.setattr(time, "sleep", sleep)

    def exercise():
        with native_profile_directory() as path:
            assert path == temporary.name
            if probe_fails:
                raise AssertionError("navigation failed")

    if probe_fails:
        with pytest.raises(AssertionError, match="navigation failed"):
            exercise()
    else:
        exercise()
    assert temporary.cleanup.call_count == 2
    sleep.assert_called_once()


@pytest.mark.parametrize("error", [PermissionError("still locked"), OSError("cleanup failed")])
def test_native_profile_cleanup_propagates_persistent_errors(monkeypatch, error):
    temporary = SimpleNamespace(name="synthetic-profile", cleanup=Mock(side_effect=error))
    monkeypatch.setattr(tempfile, "TemporaryDirectory", Mock(return_value=temporary))
    monkeypatch.setattr(time, "monotonic", Mock(side_effect=[0, 1, 5]))
    sleep = Mock()
    monkeypatch.setattr(time, "sleep", sleep)
    with pytest.raises(type(error), match=str(error)), native_profile_directory():
        pass
    assert temporary.cleanup.call_count == (2 if isinstance(error, PermissionError) else 1)
    assert sleep.call_count == (1 if isinstance(error, PermissionError) else 0)


def run_native_navigation_probe():
    """Windows integration check; only synthetic pages on two loopback servers."""
    import json
    import threading
    import webbrowser
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path
    from unittest.mock import patch

    import webview

    foreign_hits = []
    observed = []
    opened = []
    failures = []
    delivered = threading.Event()

    class Foreign(BaseHTTPRequestHandler):
        def do_GET(self):
            foreign_hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"foreign document")

        def log_message(self, *args):
            pass

    foreign = ThreadingHTTPServer(("127.0.0.1", 0), Foreign)
    foreign_url = f"http://127.0.0.1:{foreign.server_port}/foreign"

    class Local(Foreign):
        def do_GET(self):
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", foreign_url)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                (
                    '<h1 id="editor">Synthetic editor</h1>'
                    f'<p><a id="link" href="{foreign_url}">External link</a></p>'
                    f'<p><a id="popup" target="_blank" href="{foreign_url}">External popup</a></p>'
                ).encode()
            )

    local = ThreadingHTTPServer(("127.0.0.1", 0), Local)
    url = f"http://127.0.0.1:{local.server_port}/"
    servers = (local, foreign)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()

    window = webview.create_window("MCBE navigation check", "about:blank")
    policy = DesktopNavigation(window, url)
    window.events.before_show += policy.install
    window.events.loaded += policy.prepare_links

    def exercise():
        from System import Action

        def on_ui(callback):
            result = []
            window.native.Invoke(Action(lambda: result.append(callback())))
            return result[0]

        def navigation(_sender, args):
            if not policy.allows(str(args.Uri)):
                observed.append(("navigation", bool(args.Cancel)))
                delivered.set()

        def frame(_sender, args):
            if str(args.Uri) == foreign_url:
                observed.append(("frame", bool(args.Cancel)))
                delivered.set()

        def popup(_sender, args):
            if str(args.Uri) == foreign_url:
                observed.append(("popup", bool(args.Handled)))
                delivered.set()

        def subscribe():
            core = window.native.webview.CoreWebView2
            core.NavigationStarting += navigation
            core.FrameNavigationStarting += frame
            core.NewWindowRequested += popup
            window.native.webview.WebMessageReceived += link
            return core

        def link(_sender, args):
            message = json.loads(args.WebMessageAsJson)
            if isinstance(message, dict) and message.get("type") == "mcbe.external_link":
                observed.append(("link", True))
                delivered.set()

        def script(expression):
            # Explicitly model script execution, independently of real click input.
            payload = json.dumps({"expression": expression, "userGesture": False, "returnByValue": True})
            task = on_ui(lambda: core.CallDevToolsProtocolMethodAsync("Runtime.evaluate", payload))
            result = json.loads(task.GetAwaiter().GetResult())
            assert "exceptionDetails" not in result, result
            return result.get("result", {}).get("value")

        def click(element_id, button="left"):
            script("document.addEventListener('click', e => { window.__probeClick = {trusted: e.isTrusted, target: e.target.id}; }, {once:true, capture:true})")
            point = script(
                "(() => { const r = document.getElementById(" + json.dumps(element_id) + ").getBoundingClientRect();"
                "return {x:r.x+r.width/2, y:r.y+r.height/2}; })()"
            )
            for event_type in ("mousePressed", "mouseReleased"):
                payload = json.dumps({**point, "type": event_type, "button": button, "clickCount": 1})
                task = on_ui(lambda payload=payload: core.CallDevToolsProtocolMethodAsync("Input.dispatchMouseEvent", payload))
                task.GetAwaiter().GetResult()

        try:
            policy.wait_ready()
            assert window.events.loaded.wait(20), "native page did not load"
            assert policy.links_ready.wait(10), "external link routing was not installed"
            core = on_ui(subscribe)
            assert script("document.getElementById('editor')?.textContent") == "Synthetic editor"
            attempts = (
                ("script", lambda: script("location.assign(" + json.dumps(foreign_url) + ")"), False),
                ("redirect", lambda: script("location.assign('/redirect')"), False),
                (
                    "frame",
                    lambda: script("(() => { const f = document.createElement('iframe'); f.src=" + json.dumps(foreign_url) + "; document.body.append(f); })()"),
                    False,
                ),
                ("unsolicited popup", lambda: script("window.open(" + json.dumps(foreign_url) + "); null"), False),
                ("clicked link", lambda: click("link"), True),
                ("clicked popup", lambda: click("popup"), True),
                ("middle-clicked link", lambda: click("link", "middle"), True),
                ("middle-clicked popup", lambda: click("popup", "middle"), True),
                ("file navigation", lambda: window.load_url("file:///C:/MCBE-synthetic-navigation-probe.txt"), False),
                ("data navigation", lambda: window.load_url("data:text/html,foreign"), False),
            )
            for label, attempt, external in attempts:
                delivered.clear()
                observed.clear()
                opened.clear()
                attempt()
                assert delivered.wait(10), (label, script("({click:window.__probeClick, links:window.__mcbeExternalLinks, href:location.href})"))
                assert observed and all(blocked for _, blocked in observed), (label, observed)
                assert opened == ([foreign_url] if external else []), (label, opened)
                # pywebview.load_url caches its requested URL even when cancelled.
                # Verify the native/document origin, not that request metadata.
                assert on_ui(lambda: str(core.Source)) == url, (label, on_ui(lambda: str(core.Source)))
                assert script("location.href") == url, label
                assert script("document.getElementById('editor')?.textContent") == "Synthetic editor"
                assert foreign_hits == [], (label, foreign_hits)
                print(f"Native navigation passed: {label}", flush=True)
            # A normal in-origin document must still be reachable.
            local_loaded = threading.Event()

            def local_complete(sender, args):
                if args.IsSuccess and str(sender.Source) == url + "local-page":
                    local_loaded.set()

            def watch_local():
                core.NavigationCompleted += local_complete

            on_ui(watch_local)
            policy.links_ready.clear()
            window.load_url(url + "local-page")
            assert local_loaded.wait(10)
            assert script("location.href") == url + "local-page"
            assert policy.links_ready.wait(10)
            print("Native navigation passed: same-origin document", flush=True)
            downloaded = threading.Event()

            def capture_download(_sender, args):
                args.Cancel = True  # No files or save dialog in the synthetic probe.
                downloaded.set()

            def watch_download():
                core.DownloadStarting -= window.native.browser.on_download_starting
                core.DownloadStarting += capture_download

            on_ui(watch_download)
            script("""(() => {
                const a = document.createElement('a');
                a.href = URL.createObjectURL(new Blob(['synthetic export'], {type:'application/octet-stream'}));
                a.download = 'synthetic-export.txt'; document.body.append(a); a.click(); a.remove();
            })()""")
            assert downloaded.wait(10), "navigation policy blocked a local Blob download"
            assert script("location.href") == url + "local-page"
            print("Native navigation passed: local Blob download", flush=True)
        except Exception as exc:
            failures.append(exc)
        finally:
            window.destroy()

    try:
        with native_profile_directory() as temporary, patch.object(webbrowser, "open", side_effect=opened.append):
            webview.start(exercise, gui="edgechromium", storage_path=str(Path(temporary) / "webview"))
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=5)
    if failures:
        raise AssertionError("Native navigation probe failed") from failures[0]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Exercise desktop navigation in real Windows WebView2")
    parser.add_argument("--native", action="store_true", required=True)
    parser.parse_args()
    run_native_navigation_probe()
