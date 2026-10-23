#!/usr/bin/env python3
"""Pre-generate a Vivisect .viv workspace for a binary (one-time cost).

This is the "generate once, reuse" workflow: analysis is slow, loading is
fast. Run this once per binary (optionally in the background), then the
decompiler/benchmark loads the cached .viv instantly.

Usage:
    python -m viv_decomp.vivgen BINARY [--ws-dir DIR] [--out FILE] [--timeout S]

Examples:
    python -m viv_decomp.vivgen /usr/bin/true            # -> ~/.viv/true.viv
    nohup python -m viv_decomp.vivgen /usr/bin/env &     # 11MB rust, takes ~10min
"""
from __future__ import annotations

import argparse
import os
import sys

from viv_decomp.vivcache import default_ws_dir, workspace_name_for, _run_vivbin


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary")
    parser.add_argument("--ws-dir", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)

    ws_dir = args.ws_dir or default_ws_dir()
    out = args.out or workspace_name_for(args.binary, ws_dir)
    os.makedirs(ws_dir, exist_ok=True)
    print(f"Generating {out}  (this is the slow one-time step)...")
    _run_vivbin(args.binary, out, timeout=args.timeout)
    print(f"Done: {out}  (load it with loadWorkspace; it is near-instant)")


if __name__ == "__main__":
    main()
