# Dependencies

This folder bundles the Python dependencies for Python 3.12–3.14 (generated on the canonical Python 3.12 runtime):

- `runtime.in` contains the directly required runtime dependencies and must stay consistent with `pyproject.toml`.
- `docker.in` and `dev.in` extend the runtime dependencies for Docker and for development and CI, respectively.
- `bootstrap.in` pins the pip version that evaluates the build constraints before native builds.
- `nbt-reference.in` is an independent Amulet-NBT oracle for Python 3.12 only; it is not included in runtime or dev installs. CI explicitly installs and runs it.
- `build.in` pins the complete toolchain used for native source builds. Its compiled lock is installed from wheels with hashes before build isolation is disabled.
- `*.txt` are fully resolved, hash-pinned `pip-compile` outputs. Dependabot updates these files together with their matching `.in` sources.
- `*.lock` are compatibility includes that point existing install, CI, and Docker commands at the matching `.txt` file.
- `build-constraints.txt` exactly pins Cython as a fail-safe for unsupported isolated build paths; supported builds use `build.lock`.

All lockfiles and compatibility includes are generated and verified from the project root:

```bash
python scripts/compile_lockfiles.py
python scripts/compile_lockfiles.py --check
python scripts/check_lockfiles.py
```

Installation examples remain stable through the compatibility includes:

```bash
python -m pip install --require-hashes -r requirements/runtime.lock
python -m pip install --require-hashes -r requirements/bootstrap.lock
python -m pip install --only-binary=:all: --require-hashes -r requirements/build.lock
python -m pip install --no-build-isolation --require-hashes -r requirements/dev.lock
```

Windows runtime release ZIPs include CI-built LevelDB wheels for standard CPython 3.13/3.14 on x64. The setup validates their provenance and hashes before installing them by an exact local file URL; the remaining packages use the canonical runtime lock. Python 3.12 uses published wheels. A source checkout without a matching bundle first prefers an installed Python 3.12; a 3.13/3.14 source build is used only after finding Microsoft C++ Build Tools and the Windows SDK. That path installs the locked build tools and builds only Amulet-LevelDB from its hash-verified source. See [Windows wheel maintenance](../docs/development.md#windows-wheel-bundles).

NumPy and Amulet-NBT are absent from the runtime and build locks. All normal packages are still installed from wheels. Linux CI and Docker builds verify every downloaded runtime archive against the normal lock, use only the hash-locked build toolchain, and install the resulting runtime wheels without network access. The runtime package contains only the lock, compatibility, and constraint files needed for installation, the Docker build, and the audit. The `.in` source files and this maintainer documentation stay in the full Git source tree. [License sources](licenses/README.md) document the notices included with locally built Windows wheels.
