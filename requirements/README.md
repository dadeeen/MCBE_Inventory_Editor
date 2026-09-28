# Dependencies

The editor supports Python 3.12–3.14. Shared locks are generated on Python 3.12.

- `runtime.in` contains the direct runtime dependencies and matches `pyproject.toml`.
- `docker.in` and `dev.in` extend runtime for Docker and development/CI.
- `bootstrap.in` pins pip for reproducible setup, CI and offline Docker installation.
- `leveldb-reference.in` and `nbt-reference.in` contain independent test oracles.
  They are excluded from runtime and ordinary dev installs. A required Windows
  Python 3.12 CI job installs their published wheels, audits both locks and runs
  the full suite with `--require-references`. A macOS Python 3.12 job installs
  the LevelDB reference wheel for the POSIX lock tests; there are no Linux wheels.
- `*.txt` are resolved, hash-pinned `pip-compile` outputs. `*.lock` are generated
  one-line compatibility includes. Change `.in` sources deliberately, then
  regenerate and validate; do not edit the generated files or broadly upgrade pins.

Colorama is an explicit pin because Click needs it on Windows. Keeping it
in the shared inputs makes the same hash-locked requirements installable on both
Windows and Linux without maintaining separate platform locks.

Generate and check normal locks on Python 3.12:

```bash
python scripts/compile_lockfiles.py
python scripts/compile_lockfiles.py --check
python scripts/check_lockfiles.py
```

To include the reference locks, run on Windows Python 3.12, where their pinned
binary distributions are available:

```bash
python scripts/compile_lockfiles.py --include-references
python scripts/compile_lockfiles.py --check --include-references
python scripts/check_lockfiles.py
```

Install inside the selected project virtual environment:

```bash
python -m pip install --only-binary=:all: --require-hashes -r requirements/bootstrap.lock
python -m pip install --only-binary=:all: --require-hashes -r requirements/runtime.lock
# Development, in a separate environment if desired:
python -m pip install --only-binary=:all: --require-hashes -r requirements/dev.lock
# Explicit independent references, Windows Python 3.12 only:
python -m pip install --only-binary=:all: --require-hashes -r requirements/leveldb-reference.lock -r requirements/nbt-reference.lock
python scripts/test_full.py --require-references -q
```

Normal environments contain no Amulet, NumPy or Cython. Windows setup installs
only prebuilt hash-checked wheels; no compiler, SDK or LevelDB bundle is needed.
Docker verifies downloads in a separate stage and installs runtime wheels offline.
The runtime ZIP includes only bootstrap/runtime/docker/dev lockfiles needed for
installation and auditing. Reference locks, requirement sources and maintainer
documentation stay in the full Git source tree. Setup does not remove optional
packages from existing environments; validate minimal runtime installs in fresh
environments.
