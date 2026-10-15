"""Startup log-level lookup must not select arbitrary logging attributes."""

import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def application():
    import main

    return main


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("BASIC_FORMAT", logging.INFO),
        ("_STYLES", logging.INFO),
        ("not-a-level", logging.INFO),
        ("DEBUG", logging.DEBUG),
        ("WARN", logging.WARNING),
        ("ERROR", logging.ERROR),
    ],
)
def test_startup_uses_only_registered_log_levels(application, monkeypatch, name, expected):
    configure = Mock()
    monkeypatch.setattr(application, "APP_CONFIG", SimpleNamespace(log_level=name))
    monkeypatch.setattr(logging, "basicConfig", configure)
    # Restore the handler collection even when the app had not attached its
    # recent-log handler before this call (for example in a test process).
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", list(root.handlers))

    application._configure_logging()

    configure.assert_called_once()
    assert configure.call_args.kwargs["level"] == expected
