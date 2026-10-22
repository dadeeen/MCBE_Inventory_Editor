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
| `mcbe_editor/desktop_locale.py` | Windows display-language fallback and last editor language for native messages |
| `mcbe_editor/desktop_window.py` | Remembered window size and maximization, fitted to the current monitor |
| `mcbe_editor/desktop_navigation.py` | Exact-origin navigation policy and native WebView2 event adapter |
| `mcbe_editor/desktop_worker.py` | Allowlisted updater subprocesses and explicit UTF-8 output |
| `packaging/windows/desktop.spec` | Frozen modules, shared assets and dependency license metadata |
| `scripts/build_desktop.py` | Fresh staging, content checks, packaged window/recovery checks, manifest, ZIP and checksum |
| `requirements/desktop-build.*` | Separate Windows build dependencies and generated hash lock |
| `tests/test_desktop.py` | Close outcomes, worker dispatch, GUI adapter and package exclusions |
| `tests/test_desktop_navigation.py` | Navigation, popup and frame policy, initialization failure |

`main.create_local_server` and `LocalServer` own the shared HTTP lifecycle.
Browser startup retains its launcher and waits for an explicit console stop.
Heartbeat shutdown is an optional legacy browser mode, disabled by default;
suspended background tabs cannot reliably prove that editing has ended. The
frontend sends heartbeats only when that mechanism is enabled. Desktop always
disables it and follows its window. Docker retains Gunicorn. GUI imports are confined to desktop
startup, and browser/Docker requirements exclude pywebview and PyInstaller.

Editing uses the normal CSRF-protected HTTP API. No generic Python API is exposed
to page JavaScript. `window.MCBEDesktop.closeState()` is a read-only
contract for unsaved edits. The close callback returns before querying
JavaScript so the Windows UI thread remains available. Active writes finish
before closing; the HTTP server drains active handlers. The close-state query
has a bounded wait and at most one pending renderer call; unknown state requires
confirmation. World writes are never interrupted by that timeout. Native pickers
are injected into the existing dialog adapter.

## Navigation boundary

The host starts on a blank document, installs native WebView2 navigation handlers
and then loads the editor. Only `http://127.0.0.1:<bound-port>` may become a top-level
or frame document. Scheme, hostname and port are compared as parsed components;
credentials and ambiguous URLs are rejected. A clicked external HTTP(S) link opens
in the standard browser. Script navigation, foreign redirects/frames, unsolicited
popups and non-HTTP schemes cannot leave the editor or launch an external handler.
Local popups requested by a user stay in the existing window. Foreign document
requests also receive a local rejection before network access.

`desktop_navigation.py` adapts the native control exposed by pywebview 6.2.1,
including replacement of its unrestricted popup handler. Binding failure aborts
startup. The close guard checks the document origin before and after evaluating
frontend state. Native gesture flags are insufficient to distinguish host-injected
scripts from clicks. A trusted DOM anchor click instead sends one narrowly scoped
external-link message with a per-window nonce. The host validates the message
origin, nonce and HTTP(S) URL; arbitrary popups cannot launch external handlers.
Other pywebview messages also require the editor origin. No host objects or
editing functions are exposed through this bridge. This follows Microsoft's [WebView2 origin and
navigation guidance](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/security).
Retest the adapter against the real WebView whenever pywebview changes.

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

The host disables proxy-header trust and restricts HTTP Host headers to loopback
names. It waits for a bounded, proxy-free health response before opening the
window. If the backend fails, a dialog offers to keep the window open for noting
unsaved changes. `desktop.log` rotates at about 2 MB with three older files;
logs and the WebView profile remain private runtime data.

Native messages use the editor language and retain it in `data/desktop-language.txt`
for startup errors. Without a saved language they use the Windows display language,
with English as the fallback. Windows supplies its own standard dialog button labels.

Window size and maximization are saved on close in `data/desktop-window.json`.
Startup adjusts the normal size for the monitor's DPI and available work area;
missing or invalid settings use the automatic initial size. Window positions and
minimization are not restored.

An OS file lock protects each desktop data directory. Its file may remain after
exit; Windows releases the lock when the process exits. The application does
not delete a lock file to bypass a running instance. To share per-world locks,
different installations must use the same `MCBE_BACKUP_ROOT` (or, when unset,
`MCBE_DATA_ROOT`) and the same normalized world path.

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

The EXE embeds `packaging/windows/app.ico` (16–256 px, including common DPI sizes).
Its source image is `app-icon.png` in the same directory; changing the icon requires
replacing these static assets and rebuilding, with no runtime image dependency.

Generate changes with `scripts/compile_lockfiles.py --include-desktop` on
Windows Python 3.12. Verify with `--check --include-desktop` and
`scripts/check_lockfiles.py`. Shared runtime pins are constrained by the
existing locks. CI produces a separate revision-specific artifact and includes
it alongside the runtime ZIP in tagged releases.

## Validation and maintenance

The builder starts the actual EXE from a different working directory, removes
Python from PATH, isolates world/profile/data locations and checks HTTP assets
and both updater entry points. It uses `--diagnose REPORT.json --with-window`
to load the native WebView, query the frontend close state and close through the
normal guard. `--diagnose REPORT.json` alone checks startup without a window.
The packaged recovery check creates a synthetic interrupted-restore journal,
verifies that missing confirmation and read-only mode leave it unchanged, and
then verifies a confirmed recovery. No real world is used.

Windows CI also runs `python -m tests.test_desktop_navigation --native` in the
desktop build environment. Two synthetic loopback servers exercise script
navigation, redirects, frames, popups, real link clicks, file/data URLs and
allowed local navigation and Blob exports in WebView2. Browser launches are intercepted and
checked, and foreign document requests must never reach the second server.

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
to check external runtime assumptions. The automated probes do not establish
these broader GUI workflows, clean-machine behavior, live updater downloads or
Minecraft compatibility.

WebView2 Evergreen is an external prerequisite and updates independently. The app
does not install it silently. Offline machines need Microsoft's offline Runtime
installer prepared separately. The ZIP does not include a fixed WebView2
distribution. Builds are unsigned unless a release signing process is configured;
checksums establish file integrity, not publisher identity.

Maintenance covers the Windows build, bundled CPython security updates,
deliberate pywebview/PyInstaller lock updates and native window checks.
Inventory, NBT, backup and UI features stay shared; separate desktop templates,
storage backends and domain logic are outside this architecture.

## Command-line limits

The EXE accepts `--data-dir`, `--port`, `--diagnose`, `--with-window`, `--debug`,
`--recover` and `--recovery-report`. Its internal
worker mode dispatches only the item and icon updaters; it is not a general
Python interpreter. Commands using `.venv`, `python -m ...` or `scripts/*.py`
require the browser runtime or a source checkout with Python installed.

`--recover` runs the shared restore-recovery CLI without Flask or WebView2.
Close the desktop app first; its data-directory instance lock also protects
recovery. Everything after `--recover` is passed to that CLI, so put desktop
options before it. For example, from the installation's PowerShell directory:

```powershell
.\MCBEInventoryEditor.exe --data-dir "C:/Editor/data" --recover "C:/WORLDS" --confirm-server-stopped
```

Use that confirmation only after stopping the server and reviewing the reported
paths. Without it the command inspects pending recovery without changing the
world. Read-only mode and detected online servers still block writes. Error
messages generate a PowerShell command with the active executable and data root;
spaces, apostrophes and Unicode paths are quoted. Help and results go to
`restore-recovery.txt` under that data root, with a result dialog for windowed
launches. `--recovery-report PATH`, placed before `--recover`, selects a different
report and suppresses that dialog for automation. See the [recovery
instructions](../SECURITY.md#interrupted-restores) for browser and Docker commands.
