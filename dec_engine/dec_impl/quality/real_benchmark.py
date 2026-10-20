"""Benchmark against REAL binaries via the live Vivisect workspace.

Unlike the synthetic corpus (S7), this exercises the full Vivisect path:
load ELF → analyze → pick real functions → decompile each through
``VivisectDecompiler.from_workspace`` (symbolik lift) → score with the quality
gate.

The ``analyzePLT`` "Invalid File: None" exception is benign/internal (Vivisect
catches it and continues), so real binaries DO analyze and decompile.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


# Real ELF binaries to benchmark (first existing = corpus base).
DEFAULT_BINS = ["/usr/bin/true", "/bin/true", "/usr/bin/env",
                "/usr/bin/printf", "/usr/bin/ls", "/bin/ls"]


@dataclass
class RealBinaryResult:
    """Decompile score over a batch of real functions from one binary."""

    binary: str
    func_count: int
    decompiled: int
    passed: int
    failures: List[str] = field(default_factory=list)
    names: List[str] = field(default_factory=list)  # function names decompiled


def find_real_binaries(existing: Optional[List[str]] = None) -> List[str]:
    return [b for b in (existing or DEFAULT_BINS) if os.path.exists(b)]


def load_workspace(binary_path: str):
    """Load and analyze a real binary into a live Vivisect workspace."""
    import vivisect
    vw = vivisect.VivWorkspace()
    vw.loadFromFile(binary_path)
    try:
        vw.analyze()
    except Exception as exc:  # analyzePLT benign
        logger.debug("analyze raised (benign): %s", exc)
    return vw


def _pick_functions(vw, limit: int = 20):
    """Pick up to ``limit`` functions, sorted by size (more interesting)."""
    try:
        funcs = list(vw.getFunctions())
    except Exception:
        return []
    return sorted(funcs)[:limit]


def decompile_function(vw, fva, arch: Optional[str] = None):
    """Decompile one function from the live workspace; return (text, DecompOutput)."""
    from viv_decomp.decompiler import VivisectDecompiler
    d = VivisectDecompiler.from_workspace(vw, arch=arch)
    return d.decompile_address(fva)


def run_real_benchmark(binary_path: str, limit: int = 20,
                       arch: Optional[str] = None) -> RealBinaryResult:
    """Decompile up to ``limit`` functions from a real binary and score."""
    from dec_engine.dec_impl.quality.metrics import QualityGate, analyze_output

    gate = QualityGate()  # default (non-strict) thresholds
    vw = load_workspace(binary_path)
    # detect arch from the workspace meta
    try:
        arch = arch or vw.getMeta("Architecture")
    except Exception:
        pass
    funcs = _pick_functions(vw, limit)

    failures: List[str] = []
    names: List[str] = []
    decompiled = 0
    passed = 0

    for fva in funcs:
        try:
            out = decompile_function(vw, fva, arch=arch)
        except Exception as exc:  # pragma: no cover
            failures.append(f"{fva:x}: {type(exc).__name__}: {exc}")
            continue
        if not out or not out.success or not out.text:
            failures.append(f"{fva:x}: no output")
            continue
        decompiled += 1
        try:
            name = vw.getName(fva) or f"func_{fva:x}"
        except Exception:
            name = f"func_{fva:x}"
        names.append(name)
        q = analyze_output(out.text)
        if gate.passes(q):
            passed += 1
        else:
            failures.append(f"{fva:x} ({name}): {','.join(gate.check(q))}")

    return RealBinaryResult(
        binary=binary_path,
        func_count=len(funcs),
        decompiled=decompiled,
        passed=passed,
        failures=failures,
        names=names,
    )


def summarize_real(results: List[RealBinaryResult]) -> str:
    lines = []
    for r in results:
        lines.append(
            f"[{r.binary}] funcs={r.func_count} decompiled={r.decompiled} "
            f"passed={r.passed}/{r.decompiled}"
        )
        for f in r.failures[:5]:  # cap noise
            lines.append(f"    FAIL {f}")
        if len(r.failures) > 5:
            lines.append(f"    ... +{len(r.failures)-5} more failures")
    lines.append(f"\nTotal passed {sum(r.passed for r in results)}/"
                 f"{sum(r.decompiled for r in results)} decompiled")
    return "\n".join(lines)
