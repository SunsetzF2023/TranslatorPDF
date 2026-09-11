#!/usr/bin/env python3
"""Entry point: `python app.py` opens the desktop UI, `python app.py file.pdf` runs the CLI."""

import sys


def main() -> int:
    if len(sys.argv) > 1:
        from pdfbt.cli import main as cli_main

        return cli_main(sys.argv[1:])
    from pdfbt.gui import main as gui_main

    gui_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
