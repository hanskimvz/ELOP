"""Entry point.

    Python3.8.10\\python.exe -m app.main            GUI
    Python3.8.10\\python.exe -m app.main --cli ...  command line (see app/cli.py)
"""

import sys

from .cli import build_parser, run_cli


def main() -> int:
    args = build_parser().parse_args()
    if args.cli or args.list_ports or args.compare or args.analyze:
        return run_cli(args)

    from .gui.main_window import run_gui
    return run_gui(args)


if __name__ == "__main__":
    sys.exit(main())
