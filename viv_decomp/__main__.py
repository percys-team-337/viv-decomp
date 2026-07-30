"""
CLI entry point for the Vivisect decompiler pipeline.

Usage:
    python -m viv_decomp /path/to/binary [-a 0x401000 | -f function_name]
    viv-decomp /path/to/binary --ssa --types -o output.c
    viv-decomp /path/to/binary --format json --graph vivisect
"""
from __future__ import annotations

import argparse
import sys
import json
import os
import logging
from typing import Optional

# Ensure the project root is on sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from viv_decomp.decompiler import VivisectDecompiler

logger = logging.getLogger("viv-decomp")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")

    try:
        decompiler = VivisectDecompiler(
            graph_source=args.graph,
            binary_path=args.binary,
            analyze_types=args.types,
            do_ssa=args.ssa,
        )
        output = decompiler.decompile_address(args.address)
        if not output:
            print("Error: No output produced", file=sys.stderr)
            return 1
        _write_output(output.text, args.output, output.json)
        return 0
    except Exception as e:
        logger.error(f"Decompilation failed: {e}")
        return 1


def _build_parser() -> argparse.ArgumentParser:
    epilog = "Examples:\n"
    epilog += (
        "  python -m viv_decomp /lib/libc.so.6 -a 0x1234\n"
        "  python -m viv_decomp /bin/ls -f start --ssa --types\n"
        "  python -m viv_decomp /bin/ls -a 0x48000 -o output.c --format text\n"
    )
    p = argparse.ArgumentParser(
        prog="viv-decomp",
        description="Decompile functions from binaries using the Vivisect pipeline",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # positional
    p.add_argument("binary", help="Path to executable/binary file")
    # function target
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("-a", "--address", type=_parse_hex,
                     help="Function entry address (hex or decimal)")
    grp.add_argument("-f", "--function-name", dest="function",
                     help="Function name to decompile")
    # output
    p.add_argument("-o", "--output", dest="output",
                   help="Output file path (default: stdout)")
    fmts = ["text", "json", "raw"]
    p.add_argument("--format", dest="output_format", choices=fmts,
                   default="text",
                   help="Output format (default: text)")
    # pipeline options
    p.add_argument("--graph", choices=["vivisect", "ghidra", "raw"],
                   default="vivisect",
                   help="Graph source backend (default: vivisect)")
    p.add_argument("--ssa/--no-ssa", dest="ssa", default=True,
                   help="Run SSA construction pass (default: enabled)")
    p.add_argument("--types/--no-types", dest="types", default=True,
                   help="Run type inference pass (default: enabled)")
    # verbosity
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Enable verbose output")
    return p


def _parse_hex(s: str) -> int:
    """Parse decimal or 0x... string to int."""
    if s.startswith(("0x", "0X")):
        return int(s, 16)
    return int(s, 10)


def _write_output(text: str, output_file: str | None, json_data: dict | None = None):
    """Write decompiler output to stdout or file."""
    if output_file:
        with open(output_file, "w") as f:
            f.write(text)
        print(f"Written to {output_file}", file=sys.stderr)
    else:
        print(text)
    if json_data:
        print("\n" + json.dumps(json_data, indent=2), file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
