# Portable Windows desktop

The Windows x64 edition hosts the existing Flask application in a pywebview
window using the installed WebView2 Runtime. PyInstaller bundles standard CPython
3.12, dependencies and the shared frontend in an onedir package. There is one
editor implementation across desktop, browser and Docker.

## Ownership

| File | Responsibility |
| --- | --- |
| `desktop.py` | Executable entry point; no editing logic |
| `mcbe_editor/desktop_app.py` | Loopback configuration, instance lock, native pickers, close guard, window profile |
| `mcbe_editor/desktop_worker.py` | Allowlisted updater subprocesses and explicit UTF-8 output |
| `packaging/windows/desktop.spec` | Frozen modules, shared assets and dependency license metadata |
| `scripts/build_desktop.py` | Fresh staging, content checks, packaged startup check, manifest, ZIP and checksum |
| `requirements/desktop-build.*` | Separate Windows build dependencies and generated hash lock |
| `tests/test_desktop.py` | Close outcomes, worker dispatch, GUI adapter and package exclusions |

`main.create_local_server` and `LocalServer` own the shared HTTP lifecycle.
Browser startup retains its launcher and heartbeat; desktop shutdown follows
its window. Docker retains Gunicorn. GUI imports are confined to desktop
startup, and browser/Docker requirements exclude pywebview and PyInstaller.

The window uses the normal CSRF-protected HTTP API, with no custom Python API
exposed to page JavaScript. `window.MCBEDesktop.closeState()` is a read-only
contract for unsaved edits. The close callback returns before querying
JavaScript so the Windows UI thread remains available. Active writes finish
before closing; the HTTP server drains active handlers. Native pickers are
injected into the existing dialog adapter.

## Application files and persistent state

```text
MCBEInventoryEditor/
  MCBEInventoryEditor.exe
  _internal/              # Python, DLLs, packaged modules and shared UI
  RELEASE_MANIFEST.json
  README.md / README.de.md / SECURITY.md / SECURITY.de.md / LICENSE
  docs/assets/            # screenshots referenced by the README files
  data/                  # created on first start; absent from the download
```

Assets resolve relative to the bundle; writable state resolves beside the
executable. `--data-dir PATH` selects another explicit data directory. WebView
storage lives under `data/webview`. Port 5001 keeps its origin stable across
launches and leaves browser port 5000 independent. `--port N` handles a port
collision; changing the origin also changes origin-scoped window preferences.
Desktop always binds to `127.0.0.1`, even with inherited Docker configuration.
Existing read-only and server-offline write guards remain effective.

An OS file lock protects each desktop data directory. Its file may remain after
exit; Windows releases the lock when the process exits. The application does
not delete a lock file to bypass a running instance. Existing per-world locks
also protect access across different installations.

After closing the application, an update can replace the EXE, the entire
`_internal` directory and the other package files, including
`RELEASE_MANIFEST.json`, in the existing installation while retaining `data`.
Remove the old `_internal` directory before copying the new one so that versions
are not mixed. Extracting into a new directory and copying `data` instead keeps
the old application available until the new one is verified. The builder rejects
an existing output path and never merges a build into a user installation.

## Build

Use Windows x64 with standard CPython 3.12. A clean environment prevents optional
GUI frameworks from being collected accidentally. From the repository root:

```powershell
py -3.12 -m venv .tmp/desktop-build
.tmp/desktop-build/Scripts/python.exe -m pip install --require-hashes -r requirements/bootstrap.lock
.tmp/desktop-build/Scripts/python.exe -m pip install --require-hashes --only-binary=:all: -r requirements/dev.lock
.tmp/desktop-build/Scripts/python.exe -m pip install --require-hashes --only-binary=:all: --no-binary=proxy-tools --no-build-isolation -r requirements/desktop-build.lock
.tmp/desktop-build/Scripts/python.exe scripts/build_desktop.py
```

The small pure-Python `proxy-tools` dependency publishes only a source archive.
Its source hash is pinned; it is built using the already locked setuptools/wheel
environment with build isolation disabled. Other packages use wheels. No build
tool or package installation runs on the end user's machine.

Generate changes with `scripts/compile_lockfiles.py --include-desktop` on
Windows Python 3.12. Verify with `--check --include-desktop` and
`scripts/check_lockfiles.py`. Shared runtime pins are constrained by the
existing locks. CI produces a separate revision-specific artifact and includes
it alongside the runtime ZIP in tagged releases.

## Validation and maintenance

The builder starts the actual EXE from a different working directory, removes
Python from PATH, isolates world/profile/data locations and checks HTTP assets
and both updater entry points. `--diagnose REPORT.json` performs this offline
check without a window. It does not prove GUI interaction, live downloads or
Minecraft compatibility.

`--debug` enables WebView developer tools for local troubleshooting. Automated
WebView checks can additionally set `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` to
`--remote-debugging-port=9227 --remote-debugging-address=127.0.0.1` and attach
Playwright through CDP. Use an isolated data directory and synthetic worlds;
normal startup enables neither developer tools nor a debugging port.

Before publishing, supplement the automated Python/browser and packaged startup
checks with practical WebView tests: first start, Unicode folder selection,
import/export, item/icon updates, unsaved-close cancellation, closing after a save,
restart preferences and update by replacing application files. Use synthetic
worlds or disposable copies. Verify startup in a clean Windows VM without Python
to check external runtime assumptions. The CI startup probe does not perform
these native-window and clean-machine checks.

WebView2 Evergreen is an external prerequisite and updates independently. The app
does not install it silently. Offline machines need Microsoft's offline Runtime
installer prepared separately. The ZIP does not include a fixed WebView2
distribution. Builds are unsigned unless a release signing process is configured;
checksums establish file integrity, not publisher identity.

## Command-line limits

The EXE accepts `--data-dir`, `--port`, `--diagnose` and `--debug`. Its internal
worker mode dispatches only the item and icon updaters; it is not a general
Python interpreter. Commands using `.venv`, `python -m ...` or `scripts/*.py`
require the browser runtime or a source checkout with Python installed.

Interrupted-restore recovery has no desktop CLI entry point. Python-style
recovery commands generated in desktop error messages cannot be run through the
EXE. Follow the [recovery instructions](../SECURITY.md#interrupted-restores) using
a separate matching runtime installation while the desktop app is closed.

## Maintenance

Maintenance consists of the Windows build, bundled CPython security updates,
deliberate pywebview/PyInstaller lock updates and native window checks.
Inventory, NBT, backup and UI features remain shared. Separate desktop templates,
a second storage backend and desktop-specific domain logic are outside this
architecture.
