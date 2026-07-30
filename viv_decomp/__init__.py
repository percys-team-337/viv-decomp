"""
viv-decomp: Vivisect decompiler pipeline.

Standalone decompiler engine — not a Vivisect plugin or core patch.
Graph builders are pluggable (Vivisect, Ghidra, raw stubs).

Usage:
    python -m viv_decomp /path/to/binary --address 0x401000
"""
from viv_decomp.decompiler import (
    VivisectDecompiler,
    GraphBuilder,
    VivisectGraphBuilder,
    RawGraphBuilder,
    DecompOutput,
    decompile,
)

__all__ = [
    "VivisectDecompiler",
    "GraphBuilder",
    "VivisectGraphBuilder",
    "RawGraphBuilder",
    "DecompOutput",
    "decompile",
]
__version__ = "0.1.0"
