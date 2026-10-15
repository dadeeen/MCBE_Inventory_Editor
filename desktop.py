"""Windows desktop entry point; the browser and Docker keep using main.py."""

from mcbe_editor.desktop_app import main

if __name__ == "__main__":
    raise SystemExit(main())
