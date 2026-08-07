import unittest
from unittest.mock import Mock, patch

from mcbe_editor.presence import WorldPresenceTracker, normalize_session_id


class PresenceTrackerTests(unittest.TestCase):
    def test_reports_other_session_on_same_world(self):
        tracker = WorldPresenceTracker(ttl_seconds=45)
        tracker.touch("session-a", "/tmp/world", player_key="p1", player_label="Alex", dirty=False, now=100)
        data = tracker.touch("session-b", "/tmp/world", player_key="p2", player_label="Steve", dirty=False, now=101)
        self.assertEqual(data["other_sessions"], 1)
        self.assertEqual(data["same_player_sessions"], 0)
        self.assertEqual(data["other_dirty_sessions"], 0)

    def test_reports_same_player_and_dirty(self):
        tracker = WorldPresenceTracker(ttl_seconds=45)
        tracker.touch("session-a", "/tmp/world", player_key="player", player_label="Alex", dirty=True, now=100)
        data = tracker.touch("session-b", "/tmp/world", player_key="player", player_label="Alex", dirty=False, now=101)
        self.assertEqual(data["other_sessions"], 1)
        self.assertEqual(data["same_player_sessions"], 1)
        self.assertEqual(data["other_dirty_sessions"], 1)
        self.assertEqual(data["same_player_dirty_sessions"], 1)

    def test_session_moves_world_instead_of_appearing_in_both(self):
        tracker = WorldPresenceTracker(ttl_seconds=45)
        tracker.touch("session-a", "/tmp/world-a", now=100)
        tracker.touch("session-a", "/tmp/world-b", now=101)
        data = tracker.touch("session-b", "/tmp/world-a", now=102)
        self.assertEqual(data["other_sessions"], 0)

    def test_session_age_restarts_when_browser_moves_to_another_world(self):
        tracker = WorldPresenceTracker(ttl_seconds=45)
        tracker.touch("session-a", "/tmp/world-a", now=100)
        tracker.touch("session-a", "/tmp/world-b", now=110)

        data = tracker.snapshot("session-b", "/tmp/world-b", now=112)

        self.assertEqual(data["sessions"][0]["age_seconds"], 2)

    def test_expired_sessions_are_ignored(self):
        tracker = WorldPresenceTracker(ttl_seconds=10)
        tracker.touch("session-a", "/tmp/world", now=100)
        data = tracker.touch("session-b", "/tmp/world", now=111)
        self.assertEqual(data["other_sessions"], 0)

    def test_default_clock_uses_monotonic_time_for_expiry(self):
        tracker = WorldPresenceTracker(ttl_seconds=10, logger=False)

        with patch("mcbe_editor.presence._presence_now", side_effect=[100.0, 111.0]) as clock:
            tracker.touch("session-a", "/tmp/world")
            data = tracker.touch("session-b", "/tmp/world")

        self.assertEqual(data["other_sessions"], 0)
        self.assertEqual(clock.call_count, 2)

    def test_leave_removes_session(self):
        tracker = WorldPresenceTracker(ttl_seconds=45)
        tracker.touch("session-a", "/tmp/world", now=100)
        tracker.leave("session-a", now=101)
        data = tracker.touch("session-b", "/tmp/world", now=102)
        self.assertEqual(data["other_sessions"], 0)

    def test_touch_logs_new_browser_session_once(self):
        logger = Mock()
        tracker = WorldPresenceTracker(ttl_seconds=45, logger=logger)

        tracker.touch("session-a", "/tmp/world", player_key="player", player_label="Alex", dirty=True, now=100)
        tracker.touch("session-a", "/tmp/world", player_key="player", player_label="Alex", dirty=False, now=101)

        logger.info.assert_called_once_with(
            "presence connected session_id=%s world=%s player=%s dirty=%s",
            "session-a",
            "/tmp/world",
            "Alex",
            True,
        )

    def test_world_change_logs_disconnect_and_connect(self):
        logger = Mock()
        tracker = WorldPresenceTracker(ttl_seconds=45, logger=logger)

        tracker.touch("session-a", "/tmp/world-a", player_key="player-a", player_label="Alex", dirty=True, now=100)
        tracker.touch("session-a", "/tmp/world-b", player_key="player-b", player_label="Steve", dirty=False, now=110)

        logger.info.assert_any_call(
            "presence disconnected session_id=%s reason=%s world=%s player=%s dirty=%s idle_seconds=%s",
            "session-a",
            "world_change",
            "/tmp/world-a",
            "Alex",
            True,
            10,
        )
        logger.info.assert_any_call(
            "presence connected session_id=%s world=%s player=%s dirty=%s",
            "session-a",
            "/tmp/world-b",
            "Steve",
            False,
        )

    def test_leave_logs_browser_disconnect(self):
        logger = Mock()
        tracker = WorldPresenceTracker(ttl_seconds=45, logger=logger)

        tracker.touch("session-a", "/tmp/world", player_key="player", player_label="Alex", dirty=True, now=100)
        tracker.leave("session-a", now=112)

        logger.info.assert_any_call(
            "presence disconnected session_id=%s reason=%s world=%s player=%s dirty=%s idle_seconds=%s",
            "session-a",
            "leave",
            "/tmp/world",
            "Alex",
            True,
            12,
        )

    def test_expired_session_logs_timeout_disconnect(self):
        logger = Mock()
        tracker = WorldPresenceTracker(ttl_seconds=10, logger=logger)

        tracker.touch("session-a", "/tmp/world", player_key="player", player_label="Alex", dirty=True, now=100)
        tracker.touch("session-b", "/tmp/world", player_key="other", player_label="Steve", dirty=False, now=111)

        logger.info.assert_any_call(
            "presence disconnected session_id=%s reason=%s world=%s player=%s dirty=%s idle_seconds=%s",
            "session-a",
            "timeout",
            "/tmp/world",
            "Alex",
            True,
            11,
        )

    def test_cleanup_expires_session_without_new_presence_touch(self):
        logger = Mock()
        tracker = WorldPresenceTracker(ttl_seconds=10, logger=logger)

        tracker.touch("session-a", "/tmp/world", player_key="player", player_label="Alex", dirty=False, now=100)
        expired = tracker.cleanup(now=111)
        data = tracker.snapshot("session-b", "/tmp/world", now=112)

        self.assertEqual(expired, 1)
        self.assertEqual(data["other_sessions"], 0)
        logger.info.assert_any_call(
            "presence disconnected session_id=%s reason=%s world=%s player=%s dirty=%s idle_seconds=%s",
            "session-a",
            "timeout",
            "/tmp/world",
            "Alex",
            False,
            11,
        )

    def test_rejects_invalid_session_id(self):
        with self.assertRaisesRegex(ValueError, "Sitzungs-ID"):
            normalize_session_id("x")

    def test_conflict_summary_flags_dirty_same_player_peer(self):
        tracker = WorldPresenceTracker(ttl_seconds=45)
        tracker.touch("session-a", "/tmp/world", player_key="player", player_label="Alex", dirty=True, now=100)
        tracker.touch("session-b", "/tmp/world", player_key="player", player_label="Alex", dirty=False, now=101)

        data = tracker.conflict_summary(
            "session-b",
            "/tmp/world",
            player_key="player",
            same_player_only=True,
            now=102,
        )

        self.assertTrue(data["conflict"])
        self.assertEqual(data["dirty_relevant_sessions"], 1)
        self.assertEqual(data["sessions"][0]["player_label"], "Alex")

    def test_conflict_summary_ignores_other_player_when_same_player_only(self):
        tracker = WorldPresenceTracker(ttl_seconds=45)
        tracker.touch("session-a", "/tmp/world", player_key="other", player_label="Steve", dirty=True, now=100)
        tracker.touch("session-b", "/tmp/world", player_key="player", player_label="Alex", dirty=False, now=101)

        data = tracker.conflict_summary(
            "session-b",
            "/tmp/world",
            player_key="player",
            same_player_only=True,
            now=102,
        )

        self.assertFalse(data["conflict"])
        self.assertEqual(data["dirty_relevant_sessions"], 0)


if __name__ == "__main__":
    unittest.main()
