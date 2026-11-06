import json
from pathlib import PurePosixPath

import pytest

from scripts.browser_sandbox import apparmor_profile, browser_executables


def test_profile_only_allows_namespaces_for_exact_executables():
    profile = apparmor_profile([PurePosixPath("/cache/chromium-1254/chrome-linux64/chrome")])
    assert '"/cache/chromium-1254/chrome-linux64/chrome" flags=(unconfined)' in profile
    assert profile.count("userns,") == 1
    assert "capability" not in profile
    assert "*" not in profile


@pytest.mark.parametrize("target", ["relative/chrome", "/cache/*/chrome", "/cache/[ab]/chrome", "/cache/{a,b}/chrome", '/cache/"chrome', "/cache/\nchrome"])
def test_profile_rejects_paths_that_can_expand_policy(target):
    with pytest.raises(ValueError):
        apparmor_profile([PurePosixPath(target)])


def test_browser_discovery_only_uses_installed_pinned_revisions(tmp_path):
    root, cache = tmp_path / "repo", tmp_path / "cache"
    manifest = root / "node_modules/playwright-core/browsers.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"browsers": [{"name": "chromium", "revision": "1254"}, {"name": "firefox", "revision": "1"}]}))
    expected = cache / "chromium-1254/chrome-linux64/chrome"
    for executable in (expected, cache / "chromium-1248/chrome-linux64/chrome", cache / "firefox-1/firefox/firefox"):
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"synthetic executable")
    assert browser_executables(root, cache) == [expected.resolve()]
    expected.unlink()
    with pytest.raises(ValueError, match="Install the matching"):
        browser_executables(root, cache)
