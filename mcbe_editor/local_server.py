"""Waitress lifecycle for the local CLI and its heartbeat shutdown thread."""

import socket
from threading import Event
from time import monotonic

from waitress import create_server, wasyncore
from waitress.channel import HTTPChannel
from waitress.task import ThreadedTaskDispatcher

SHUTDOWN_FLUSH_TIMEOUT = 5.0


class LocalServer:
    def __init__(self, app, host: str, port: int):
        self._sockets = {}
        self._stop = Event()
        self._dispatcher = ThreadedTaskDispatcher()
        listener = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET)
        try:
            # Windows SO_REUSEADDR permits two listeners on the same port.
            option = getattr(socket, "SO_EXCLUSIVEADDRUSE", socket.SO_REUSEADDR)
            listener.setsockopt(socket.SOL_SOCKET, option, 1)
            listener.bind((host, port))
            self._server = create_server(
                app,
                sockets=[listener],
                map=self._sockets,
                _dispatcher=self._dispatcher,
                # ProxyFix and MCBE_TRUST_PROXY_HEADERS own the app's trust policy.
                clear_untrusted_proxy_headers=False,
                # Waitress counts transfer framing and rejects >= its limit.
                # Allow bounded framing overhead; Flask enforces decoded size.
                max_request_body_size=app.config["MAX_CONTENT_LENGTH"] + 64 * 1024,
            )
            self._dispatcher.set_thread_count(4)
        except BaseException:
            self._dispatcher.shutdown()
            wasyncore.close_all(self._sockets)
            listener.close()
            raise

    def shutdown(self) -> None:
        """Request shutdown from another thread without touching its sockets."""
        self._stop.set()

    def _poll(self) -> None:
        wasyncore.loop(timeout=0.1, count=1, map=self._sockets)

    def serve_forever(self) -> None:
        try:
            while not self._stop.is_set():
                self._poll()
        finally:
            try:
                # Stop admitting connections and dispatching queued work. Keep I/O
                # running until active handlers finish, including large responses.
                self._server.accepting = False
                self._dispatcher.set_thread_count(0)
                deadline = monotonic() + SHUTDOWN_FLUSH_TIMEOUT
                while True:
                    with self._dispatcher.lock:
                        running = bool(self._dispatcher.threads)
                    if not running:
                        break
                    self._poll()
                    if monotonic() >= deadline:
                        # A worker can wait on a full response buffer forever if
                        # its client stops reading. Closing that channel wakes
                        # the worker; handlers doing application work still finish.
                        for channel in list(self._server.active_channels.values()):
                            if channel.total_outbufs_len > channel.adj.outbuf_high_watermark:
                                channel.handle_close()
                self._dispatcher.shutdown()
                # Handlers may finish before their last response bytes are sent.
                # Bound this final flush so an idle client cannot hold us open.
                deadline = monotonic() + SHUTDOWN_FLUSH_TIMEOUT
                while monotonic() < deadline and any(
                    isinstance(channel, HTTPChannel) and channel.total_outbufs_len for channel in list(self._sockets.values())
                ):
                    self._poll()
            finally:
                wasyncore.close_all(self._sockets)
