"""WebView2 navigation boundary for the pinned pywebview Windows host.

Only the editor's exact HTTP origin may become a document. Native events cover
links, scripts, redirects, frames and popups before foreign content is loaded.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
import webbrowser
from urllib.parse import urlsplit

LOGGER = logging.getLogger(__name__)


def _http_origin(url: str) -> tuple[str, str, int] | None:
    # Do not let urllib and the browser interpret whitespace/backslashes or
    # embedded credentials differently. No file, data, javascript or OS schemes.
    if not isinstance(url, str) or "\\" in url or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return None
        return parsed.scheme, parsed.hostname, parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None


class DesktopNavigation:
    def __init__(self, window, url: str):
        self.window = window
        self.url = url
        self.origin = _http_origin(url)
        if self.origin is None or self.origin[:2] != ("http", "127.0.0.1"):
            raise ValueError("Desktop navigation requires the bound loopback HTTP origin")
        self.ready = threading.Event()
        self.links_ready = threading.Event()
        self.installed = False
        self.error: Exception | None = None
        self._view = None
        self._link_nonce = secrets.token_urlsafe(32)

    def allows(self, url: str) -> bool:
        return _http_origin(url) == self.origin

    def install(self):
        """Run synchronously in before_show, on the WinForms UI thread.

        pywebview 6.2.1 exposes the native control but no cancellable navigation
        API. Keep that version-specific adapter here, away from editor logic.
        The host starts on about:blank and loads the app only after all hooks.
        """
        try:
            self._view = self.window.native.webview
            self._view.NavigationStarting += self.on_navigation
            self._view.CoreWebView2InitializationCompleted += self._initialized
            if self._view.CoreWebView2 is not None:
                self._install_core()
        except Exception as exc:
            self._failed(exc)

    def _initialized(self, _sender, args):
        try:
            if not args.IsSuccess:
                raise RuntimeError("WebView2 initialization failed")
            self._install_core()
        except Exception as exc:
            self._failed(exc)

    def _install_core(self):
        if self.installed:
            return
        core = self._view.CoreWebView2
        core.FrameNavigationStarting += self.on_frame_navigation
        core.WebResourceRequested += self.on_document_request
        # Replace pywebview's unrestricted popup opener; otherwise it would run
        # before our policy and could launch arbitrary URL schemes externally.
        core.NewWindowRequested -= self.window.native.browser.on_new_window_request
        core.NewWindowRequested += self.on_new_window
        self._view.WebMessageReceived -= self.window.native.browser.on_script_notify
        self._view.WebMessageReceived += self.on_web_message
        core.Settings.AreHostObjectsAllowed = False
        self.installed = True
        core.Navigate(self.url)
        self.ready.set()

    def _failed(self, error: Exception):
        self.installed = False
        self.error = error
        self.ready.set()
        LOGGER.error("Desktop navigation protection could not be installed", exc_info=error)

    def wait_ready(self, timeout: float = 10.0):
        if not self.ready.wait(timeout) or not self.installed:
            from mcbe_editor.i18n import t

            raise RuntimeError(t("Die Navigationssperre des Desktop-Fensters konnte nicht eingerichtet werden.")) from self.error

    def prepare_links(self):
        # Native gesture flags also mark host-injected scripts as user initiated.
        # Only genuine DOM anchor clicks may request the single external-link
        # action. Keep the per-window nonce in this listener's closure.
        if not self.installed or not self.allows(self.window.get_current_url()):
            return
        script = """(() => {
            if (location.origin !== ORIGIN || window.__mcbeExternalLinks) return;
            window.__mcbeExternalLinks = true;
            document.addEventListener('click', event => {
                if (!event.isTrusted || event.defaultPrevented || event.button !== 0) return;
                const link = event.target.closest?.('a[href]');
                if (!link || link.hasAttribute('download')) return;
                let url;
                try { url = new URL(link.href); } catch (_) { return; }
                if (['http:', 'https:'].includes(url.protocol) && url.origin !== location.origin
                    && !url.username && !url.password) {
                    event.preventDefault();
                    window.chrome.webview.postMessage({type: 'mcbe.external_link', nonce: NONCE, url: url.href});
                }
            }, true);
        })()""".replace("ORIGIN", json.dumps(self.url.rstrip("/"))).replace("NONCE", json.dumps(self._link_nonce))
        try:
            self.window.evaluate_js(script)
            self.links_ready.set()
        except Exception:
            # Foreign navigation remains blocked even if link preparation fails.
            LOGGER.exception("Could not prepare external desktop links")

    def _from_editor(self) -> bool:
        return self.installed and self.allows(str(self._view.CoreWebView2.Source))

    def _open_external(self, url: str):
        if _http_origin(url) is not None:
            try:
                webbrowser.open(url)
            except Exception:
                LOGGER.exception("Could not open external HTTP link")

    def on_navigation(self, _sender, args):
        url = str(args.Uri)
        if self.installed and self.allows(url):
            return
        args.Cancel = True

    def on_frame_navigation(self, _sender, args):
        if not self.installed or not self.allows(str(args.Uri)):
            args.Cancel = True

    def on_document_request(self, _sender, args):
        # WebView2 may start a network request before its navigation cancellation
        # is processed. pywebview registers the all-resource filter; stop foreign
        # document requests here as well, including iframe documents.
        if str(args.ResourceContext) == "Document" and (not self.installed or not self.allows(str(args.Request.Uri))):
            args.Response = self._view.CoreWebView2.Environment.CreateWebResourceResponse(None, 403, "Blocked navigation", "")

    def on_new_window(self, _sender, args):
        args.Handled = True
        if not args.IsUserInitiated or not self._from_editor():
            return
        url = str(args.Uri)
        if self.allows(url):
            self._view.CoreWebView2.Navigate(url)

    def on_web_message(self, sender, args):
        if not self._from_editor() or not self.allows(str(args.Source)):
            return
        try:
            message = json.loads(args.WebMessageAsJson)
        except (ValueError, TypeError):
            return
        if isinstance(message, dict):
            if (
                message.get("type") == "mcbe.external_link"
                and isinstance(message.get("nonce"), str)
                and message["nonce"].isascii()
                and secrets.compare_digest(message["nonce"], self._link_nonce)
                and isinstance(message.get("url"), str)
                and not self.allows(message["url"])
            ):
                self._open_external(message["url"])
            return
        self.window.native.browser.on_script_notify(sender, args)
