#!/usr/bin/env python3
"""Real-binary benchmark runner for the decompiler.

Usage:
    python tests/benchmarks/run_real_benchmark.py [--limit N] [--bin /usr/bin/foo] ...

Loads real ELF binaries, decompiles up to N functions each through the live
Vivisect workspace (symbolik lift), and reports pass/fail against the quality
gate. Exit 0 = all decompiled functions passed; 1 = a regression.
"""
import sys
import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", ".."))
sys.path.insert(0, _ROOT)

from dec_engine.dec_impl.quality.real_benchmark import (
    find_real_binaries, load_workspace, run_real_benchmark,
    summarize_real,
)


def main(argv=None):
    argv = argv or sys.argv[1:]
    limit = 20
    bins = []
    arch = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--limit":
            limit = int(argv[i + 1]); i += 2
            continue
        if a == "--bin":
            bins.append(argv[i + 1]); i += 2
            continue
        if a == "--arch":
            arch = argv[i + 1]; i += 2
            continue
        i += 1

    targets = bins or find_real_binaries()
    results = []
    for bpath in targets:
        if not os.path.exists(bpath):
            print(f"SKIP: {bpath} not found")
            continue
        results.append(run_real_benchmark(bpath, limit=limit, arch=arch))
    print(summarize_real(results))
    # exit non-zero if any decompiled function failed the gate
    total_failed = sum(len(r.failures) for r in results)
    sys.exit(0 if total_failed == 0 else 1)


if __name__ == "__main__":
    main()
