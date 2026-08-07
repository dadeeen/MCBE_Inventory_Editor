#!/usr/bin/env python3
"""Generate a Werkzeug password hash for MCBE_AUTH_PASSWORD_HASH."""

from __future__ import annotations

import argparse
import getpass
import sys

from werkzeug.security import generate_password_hash


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a password hash for MCBE_AUTH_PASSWORD_HASH.")
    parser.add_argument("password", nargs="?", help="Password to hash. If omitted, an interactive hidden prompt is used.")
    args = parser.parse_args()

    password = args.password
    if password is None:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Repeat password: ")
        if password != confirm:
            print("Passwords do not match.", file=sys.stderr)
            return 1
    if not password:
        print("Password must not be empty.", file=sys.stderr)
        return 1

    print(generate_password_hash(password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
