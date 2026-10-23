# Item database transactions

`scripts/update_db.py` publishes the item database, source metadata and source
history as one recoverable generation. The three independently configured paths
remain supported. `mcbe_editor/item_db_transaction.py` stores an owner-only JSON
journal beside the item database, named `.item_db.json.transaction.json`.
The journal contains the exact configured paths, byte snapshots and SHA-256
hashes of the old generation, including absent files.

Before the first destination changes, the updater writes and fsyncs a `prepared`
journal through atomic replacement. After writing all destinations, it fsyncs
their contents and persists a `committed` marker with their hashes. POSIX also
fsyncs the affected directories. Windows uses fsynced files and atomic replaces;
the contract covers process termination, without promising durability against
every filesystem or hardware power-loss behavior.

A dedicated `item-db-transaction` operation lock, rooted beside the catalog,
serializes publication and recovery across threads and processes. The outer
`item-db-update` operation lock also covers the parent runner through recovery
acknowledgement, bootstrap recovery/seeding and complete standalone CLI runs.
A concurrent startup or CLI cannot consume a worker's commit marker before its
parent classifies the result. Direct runner callers receive the same protection;
the web route's existing outer lock is reentrant in that process.

The runner passes the internal `MCBE_ITEM_DB_PARENT_LOCK` marker to its child,
bound to the canonical catalog path. Only the updater CLI accepts that marker
and skips the outer lock its waiting parent already owns; it still takes the
separate publication lock. Bootstrap always takes the outer lock. Standalone
CLI calls acquire it before recovery or input reads, preserving consistent
read/modify/write updates across CLI and web processes.

Recovery validates every recorded path against the configured destinations and
checks all snapshot hashes before writing. A `prepared` journal restores the
entire old generation byte for byte; a previously absent file is removed. A
`committed` journal verifies and preserves the new generation. Recovery removes
the journal only after successful completion and is safe to repeat after an
interruption during rollback. Invalid journals, changed committed-file hashes
and failed filesystem operations fail closed and preserve the recovery evidence.

The startup bootstrap recovers before seeding runtime files or importing the
catalog. The CLI recovers before reading its inputs. The parent runner recovers
after its worker exits or after `subprocess.run` has killed and waited for a
timed-out worker. A committed marker survives worker completion until this
acknowledgement, covering a worker killed after publication but before emitting
its summary. The API reports whether the interrupted update was committed,
rolled back, or stopped before publication; a committed update triggers the
normal in-process catalog reload even when the worker failed.

The recovery boundary covers these three catalog files. Cached downloads are
independent inputs. An unrelated process reading destination files during
publication must participate in the transaction lock to obtain a consistent
multi-file view. Filesystem failures that prevent rollback require correcting
access and restarting the application; startup refuses to consume a generation
whose recovery cannot be verified.

`tests/test_item_db_transaction.py` exercises actual worker exits at preparation,
each destination publication, and the commit marker; startup recovery, killed
timeouts, interrupted rollback, absent old targets, journal validation and
recovery waiting for an active commit use synthetic catalogs. Concurrent
bootstrap/CLI processes verify that a live parent retains its commit evidence;
real managed CLI workers check the outer-lock handoff without deadlocking.
