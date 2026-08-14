# Dependencies

This folder bundles the Python dependencies for Python 3.12:

- `runtime.in` contains the directly required runtime dependencies and must stay consistent with `pyproject.toml`.
- `docker.in` and `dev.in` extend the runtime dependencies for Docker and for development and CI, respectively.
- `bootstrap.in` pins the pip version that evaluates the build constraints before native builds.
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

The Windows runtime setup installs only published wheels. Linux CI and Docker builds verify every downloaded runtime archive against the normal lock, use only the hash-locked build toolchain, and install the resulting runtime wheels without network access. The runtime package contains only the lock, compatibility, and constraint files needed for installation, the Docker build, and the audit. The `.in` source files and this maintainer documentation stay in the full Git source tree.
