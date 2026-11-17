"""Entry point for the packaged engine (PyInstaller runs this file as a plain script,
so it must use an absolute import)."""

from culler.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
