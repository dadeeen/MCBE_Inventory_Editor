import pytest
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

nbt = pytest.importorskip("amulet_nbt")

from mcbe_editor.backup import (
    MAX_BACKUP_MEMBERS,
    MAX_BACKUP_UNCOMPRESSED_MB,
    validate_zip_members,
)
from mcbe_editor.inventory import apply_player_stats
from mcbe_editor.players import MAX_EXPORT_MEMBERS, MAX_EXPORT_UNCOMPRESSED_MB, read_player_export


def _post_login_with_next(monkeypatch, next_target: str):
    from dataclasses import replace

    import main

    monkeypatch.setattr(
        main,
        "APP_CONFIG",
        replace(
            main.APP_CONFIG,
            auth_required=True,
            auth_username="admin",
            auth_password="secret",
            auth_password_hash=None,
        ),
    )
    main._RATE_LIMITS.clear()
    client = main.app.test_client()
    client.get("/login", query_string={"next": next_target})
    with client.session_transaction() as sess:
        csrf_token = sess["csrf_token"]
    return client.post(
        "/login",
        query_string={"next": next_target},
        data={"username": "admin", "password": "secret", "_csrf_token": csrf_token},
        follow_redirects=False,
    )


def test_login_allows_local_next_redirect(monkeypatch):
    response = _post_login_with_next(monkeypatch, "/versions?from=login")

    assert response.status_code == 302
    assert response.headers["Location"] == "/versions?from=login"


@pytest.mark.parametrize("next_target", ["https://evil.example", "//evil.example", "/\\evil.example", "\\evil.example"])
def test_login_rejects_unsafe_redirect_targets(monkeypatch, next_target):
    response = _post_login_with_next(monkeypatch, next_target)

    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def make_minimal_player_tag():
    return nbt.CompoundTag(
        {
            "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(64.0), nbt.DoubleTag(0.0)]),
            "Health": nbt.FloatTag(20.0),
            "PlayerGameType": nbt.IntTag(0),
        }
    )


class StatsValidationTests(unittest.TestCase):
    def test_rejects_nan_in_pos(self):
        tag = make_minimal_player_tag()
        with self.assertRaisesRegex(ValueError, "Positionswert"):
            apply_player_stats(tag, {"pos": [float("nan"), 64.0, 0.0]})

    def test_rejects_infinity_in_pos(self):
        tag = make_minimal_player_tag()
        with self.assertRaisesRegex(ValueError, "Positionswert"):
            apply_player_stats(tag, {"pos": [1.0, float("inf"), 0.0]})

    def test_rejects_negative_infinity_in_pos(self):
        tag = make_minimal_player_tag()
        with self.assertRaisesRegex(ValueError, "Positionswert"):
            apply_player_stats(tag, {"pos": [1.0, 2.0, float("-inf")]})

    def test_rejects_nan_health(self):
        tag = make_minimal_player_tag()
        with self.assertRaisesRegex(ValueError, "Health"):
            apply_player_stats(tag, {"health": float("nan")})

    def test_rejects_infinite_health(self):
        tag = make_minimal_player_tag()
        with self.assertRaisesRegex(ValueError, "Health"):
            apply_player_stats(tag, {"health": float("inf")})

    def test_rejects_negative_health(self):
        tag = make_minimal_player_tag()
        with self.assertRaisesRegex(ValueError, "Health"):
            apply_player_stats(tag, {"health": -1.0})

    def test_rejects_excessive_health(self):
        tag = make_minimal_player_tag()
        with self.assertRaisesRegex(ValueError, "Health"):
            apply_player_stats(tag, {"health": 2000.0})

    def test_accepts_valid_health(self):
        tag = make_minimal_player_tag()
        apply_player_stats(tag, {"health": 40.0})
        self.assertEqual(tag["Health"].py_data, 40.0)

    def test_rejects_gamemode_edits(self):
        for gm in (-1, 0, 1, 2, 3, 4):
            tag = make_minimal_player_tag()
            original = tag["PlayerGameType"].py_data
            with self.assertRaisesRegex(ValueError, "Spielmodus"):
                apply_player_stats(tag, {"gamemode": gm})
            self.assertEqual(tag["PlayerGameType"].py_data, original)

    def test_health_always_written_as_float(self):
        tag = make_minimal_player_tag()
        tag["Health"] = nbt.ShortTag(20)
        apply_player_stats(tag, {"health": 15})
        self.assertIsInstance(tag["Health"], nbt.FloatTag)
        self.assertEqual(tag["Health"].py_data, 15.0)

    def test_health_converts_to_float_for_non_short(self):
        tag = make_minimal_player_tag()
        tag["Health"] = nbt.FloatTag(20.0)
        apply_player_stats(tag, {"health": 15.5})
        self.assertIsInstance(tag["Health"], nbt.FloatTag)
        self.assertEqual(tag["Health"].py_data, 15.5)


class ZipLimitTests(unittest.TestCase):
    def test_validate_zip_members_rejects_duplicate_names(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as zipf:
            zipf.writestr("db/file1.dat", b"data1")
            zipf.writestr("db/file1.dat", b"data2")
        data.seek(0)
        with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(data, "r") as zipf, self.assertRaisesRegex(ValueError, "Doppelter Eintrag"):
            validate_zip_members(zipf, Path(tmp) / "restore")

    def test_validate_zip_members_implicitly_rejects_traversal(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as zipf:
            zipf.writestr("../../outside.txt", "bad")
        data.seek(0)
        with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(data, "r") as zipf, self.assertRaisesRegex(ValueError, "Unsicherer Pfad"):
            validate_zip_members(zipf, Path(tmp) / "restore")

    def test_validate_zip_members_rejects_too_many_entries(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as zipf:
            for i in range(MAX_BACKUP_MEMBERS + 1):
                zipf.writestr(f"db/file{i}.dat", b"x")
        data.seek(0)
        with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(data, "r") as zipf, self.assertRaisesRegex(ValueError, "zu viele"):
            validate_zip_members(zipf, Path(tmp) / "restore")

    def test_validate_zip_members_rejects_too_large_uncompressed(self):
        data = io.BytesIO()
        big_data = b"x" * (MAX_BACKUP_UNCOMPRESSED_MB * 1024 * 1024 + 1)
        with zipfile.ZipFile(data, "w") as zipf:
            zipf.writestr("db/big.dat", big_data)
        data.seek(0)
        with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(data, "r") as zipf, self.assertRaisesRegex(ValueError, " überschreitet"):
            validate_zip_members(zipf, Path(tmp) / "restore")

    def test_read_player_export_rejects_duplicate_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.mcbe-player.zip"
            with zipfile.ZipFile(path, "w") as zipf:
                zipf.writestr("manifest.json", json.dumps({"format": "mcbe-player-export", "version": 1}))
                zipf.writestr("preview.json", "{}")
                zipf.writestr("player.nbt", b"data")
                zipf.writestr("player.nbt", b"data2")
            with self.assertRaisesRegex(ValueError, "doppelte"):
                read_player_export(str(path))

    def test_read_player_export_rejects_too_many_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.mcbe-player.zip"
            with zipfile.ZipFile(path, "w") as zipf:
                for i in range(MAX_EXPORT_MEMBERS + 1):
                    zipf.writestr(f"file{i}.dat", b"x")
            with self.assertRaisesRegex(ValueError, "zu viele"):
                read_player_export(str(path))

    def test_read_player_export_rejects_too_large_uncompressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.mcbe-player.zip"
            big_data = b"x" * (MAX_EXPORT_UNCOMPRESSED_MB * 1024 * 1024 + 1)
            with zipfile.ZipFile(path, "w") as zipf:
                zipf.writestr("manifest.json", json.dumps({"format": "mcbe-player-export", "version": 1, "nbt": {"byte_length": len(big_data)}}))
                zipf.writestr("preview.json", "{}")
                zipf.writestr("player.nbt", big_data)
            with self.assertRaisesRegex(ValueError, " überschreitet"):
                read_player_export(str(path))


class CsrfMiddlewareTests(unittest.TestCase):
    def setUp(self):
        self.token = "test-token-123"
        self.token_patch = patch("main.CSRF_TOKEN", self.token)
        self.token_patch.start()
        from main import app

        self.app = app.test_client()
        self.app.testing = True

    def tearDown(self):
        self.token_patch.stop()

    def _mutating_endpoints(self):
        return [
            ("/api/player/save", {"world_path": "/tmp"}),
            ("/api/workspace/save", {"world_path": "/tmp", "player_key": "key", "mounts": []}),
            ("/api/player/export", {"world_path": "/tmp", "player_key": "key"}),
            ("/api/player/import", {"export_zip": "/tmp/x.zip", "world_path": "/tmp", "target_player_key": "key", "confirm_overwrite": True}),
            ("/api/restore_backup", {"world_path": "/tmp", "backup_file": "backup.zip"}),
        ]

    def test_mutating_endpoints_reject_without_csrf_token(self):
        for endpoint, body in self._mutating_endpoints():
            with self.subTest(endpoint=endpoint):
                resp = self.app.post(endpoint, json=body)
                self.assertEqual(resp.status_code, 403)
                data = resp.get_json()
                self.assertFalse(data["success"])

    def test_mutating_endpoints_reject_wrong_token(self):
        for endpoint, body in self._mutating_endpoints():
            with self.subTest(endpoint=endpoint):
                resp = self.app.post(endpoint, json=body, headers={"X-CSRF-Token": "wrong-token"})
                self.assertEqual(resp.status_code, 403)

    def test_mutating_endpoints_accept_valid_token(self):
        for endpoint, body in self._mutating_endpoints():
            with self.subTest(endpoint=endpoint):
                resp = self.app.post(endpoint, json=body, headers={"X-CSRF-Token": self.token})
                self.assertNotEqual(resp.status_code, 403)

    def test_read_post_endpoints_reject_wrong_csrf_token(self):
        endpoints = [
            "/api/heartbeat",
            "/api/players",
            "/api/player/load",
            "/api/backups",
        ]
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                resp = self.app.post(endpoint, json={"world_path": "/tmp"}, headers={"X-CSRF-Token": "wrong"})
                self.assertEqual(resp.status_code, 403)

    def test_read_post_endpoints_accept_valid_csrf_token(self):
        endpoints = [
            "/api/heartbeat",
            "/api/players",
            "/api/player/load",
            "/api/backups",
        ]
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                resp = self.app.post(endpoint, json={"world_path": "/tmp"}, headers={"X-CSRF-Token": self.token})
                self.assertNotEqual(resp.status_code, 403)

    @patch("main.CSRF_TOKEN", "test-token")
    def test_origin_check_rejects_mismatched_origin(self):
        from main import app

        client = app.test_client()
        resp = client.post(
            "/api/player/save",
            json={"world_path": "/tmp", "player_key": "key"},
            headers={"X-CSRF-Token": "test-token", "Origin": "http://evil.com"},
        )
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertIn("Origin", data.get("error", ""))

    @patch("main.CSRF_TOKEN", "test-token")
    def test_origin_check_accepts_matching_origin(self):
        from main import app

        client = app.test_client()
        resp = client.post(
            "/api/player/save",
            json={"world_path": "/tmp", "player_key": "key"},
            headers={"X-CSRF-Token": "test-token", "Origin": "http://localhost:5000", "Host": "localhost:5000"},
        )
        self.assertNotEqual(resp.status_code, 403)


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        from main import _RATE_LIMITS, app

        self.app = app.test_client()
        self.app.testing = True

        # Clean rate limit state before each test
        _RATE_LIMITS.clear()

        # Patch CSRF token so we can reach the rate limit check
        self.csrf_token = "test-csrf-rate"
        self.csrf_patch = patch("main.CSRF_TOKEN", self.csrf_token)
        self.csrf_patch.start()

    def tearDown(self):
        from main import _RATE_CONFIG, _RATE_LIMITS

        _RATE_LIMITS.clear()
        _RATE_CONFIG["mutate"] = (30, 60.0)
        _RATE_CONFIG["scan"] = (10, 60.0)
        _RATE_CONFIG["read"] = (120, 60.0)
        self.csrf_patch.stop()

    def _headers(self):
        return {"X-CSRF-Token": self.csrf_token}

    def test_rate_limit_cleanup_uses_the_bucket_group_window(self):
        import main
        from main import _RATE_CONFIG, _RATE_LIMITS

        key = ("127.0.0.1", "slow-test")
        _RATE_CONFIG["slow-test"] = (1, 300.0)
        _RATE_LIMITS[key] = [100.0]
        try:
            with patch("main._rate_limit_now", return_value=221.0):
                main._clean_rate_limits()
            self.assertIn(key, _RATE_LIMITS)

            with patch("main._rate_limit_now", return_value=701.0):
                main._clean_rate_limits()
            self.assertNotIn(key, _RATE_LIMITS)
        finally:
            _RATE_LIMITS.pop(key, None)
            _RATE_CONFIG.pop("slow-test", None)

    def test_scan_endpoint_accepts_requests_within_limit(self):
        """scan endpoint accepts requests under the limit."""
        for i in range(3):
            resp = self.app.get("/api/scan_worlds")
            self.assertEqual(resp.status_code, 200, f"Request {i} should succeed")

    def test_rate_limit_blocks_excessive_mutate_requests(self):
        from main import _RATE_CONFIG

        # Temporarily set very low limit (2 requests per 60s) for testing
        _RATE_CONFIG["mutate"] = (2, 60.0)
        headers = self._headers()

        # First two should succeed
        resp1 = self.app.post("/api/player/save", json={"world_path": "/tmp", "player_key": "key"}, headers=headers)
        self.assertNotEqual(resp1.status_code, 429, "First request should not be rate-limited")

        resp2 = self.app.post("/api/player/save", json={"world_path": "/tmp", "player_key": "key"}, headers=headers)
        self.assertNotEqual(resp2.status_code, 429, "Second request should not be rate-limited")

        # Third request should be blocked
        resp3 = self.app.post("/api/player/save", json={"world_path": "/tmp", "player_key": "key"}, headers=headers)
        self.assertEqual(resp3.status_code, 429, "Third request should be rate-limited")
        data = resp3.get_json()
        self.assertFalse(data["success"])
        self.assertIn("warten", data.get("error", ""))

    def test_rate_limit_resets_after_window(self):
        from main import _RATE_CONFIG

        _RATE_CONFIG["mutate"] = (1, 60.0)
        headers = self._headers()

        with patch("main._rate_limit_now", side_effect=[100.0, 100.0, 160.01]):
            # First request goes through.
            resp1 = self.app.post("/api/player/save", json={"world_path": "/tmp", "player_key": "key"}, headers=headers)
            self.assertNotEqual(resp1.status_code, 429)

            # A second request at the same instant is blocked.
            resp2 = self.app.post("/api/player/save", json={"world_path": "/tmp", "player_key": "key"}, headers=headers)
            self.assertEqual(resp2.status_code, 429)

            # The bucket resets deterministically after the configured window.
            resp3 = self.app.post("/api/player/save", json={"world_path": "/tmp", "player_key": "key"}, headers=headers)
            self.assertNotEqual(resp3.status_code, 429)

    def test_icon_scan_uses_scan_rate_limit(self):
        import main
        from main import _RATE_CONFIG

        _RATE_CONFIG["scan"] = (1, 60.0)
        headers = self._headers()

        with patch.object(main.icon_api_routes, "icons_scan", lambda _data, _deps: main.jsonify({"success": True})):
            resp1 = self.app.post("/api/icons/scan", json={"world_path": "/tmp"}, headers=headers)
            resp2 = self.app.post("/api/icons/scan", json={"world_path": "/tmp"}, headers=headers)

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 429)


class RemoteAddrSpoofingTests(unittest.TestCase):
    """Client-gelieferte Forwarded-Header dürfen die erkannte IP nicht steuern.

    Bei MCBE_TRUST_PROXY_HEADERS=true setzt ProxyFix (x_for=1) request.remote_addr
    aus dem vom Proxy angehängten X-Forwarded-For-Eintrag. _remote_addr darf die
    Header nicht selbst parsen, sonst wären Rate-Limits (inkl. Login-Schutz) und
    Audit-Logs über den linken, Client-kontrollierten Eintrag fälschbar.
    """

    def _trusting_config(self, main_module):
        from dataclasses import replace

        return replace(main_module.APP_CONFIG, trust_proxy_headers=True)

    def test_remote_addr_ignores_spoofed_forwarded_headers(self):
        import main

        with (
            patch.object(main, "APP_CONFIG", self._trusting_config(main)),
            main.app.test_request_context(
                "/api/config",
                headers={"X-Forwarded-For": "6.6.6.6, 198.51.100.7", "Forwarded": 'for="9.9.9.9"'},
                environ_base={"REMOTE_ADDR": "203.0.113.9"},
            ),
        ):
            self.assertEqual(main._remote_addr(), "203.0.113.9")

    def test_rate_limit_bucket_cannot_be_rotated_via_forwarded_for(self):
        import main
        from main import _RATE_CONFIG, _RATE_LIMITS

        _RATE_LIMITS.clear()
        _RATE_CONFIG["scan"] = (1, 60.0)
        try:
            with patch.object(main, "APP_CONFIG", self._trusting_config(main)):
                client = main.app.test_client()
                resp1 = client.get("/api/scan_worlds", headers={"X-Forwarded-For": "1.1.1.1"})
                resp2 = client.get("/api/scan_worlds", headers={"X-Forwarded-For": "2.2.2.2"})
            self.assertEqual(resp1.status_code, 200)
            self.assertEqual(resp2.status_code, 429)
        finally:
            _RATE_LIMITS.clear()
            _RATE_CONFIG["scan"] = (10, 60.0)


if __name__ == "__main__":
    unittest.main()
