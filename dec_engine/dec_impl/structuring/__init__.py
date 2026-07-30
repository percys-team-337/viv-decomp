"""Control flow structuring pass."""
from dec_engine.dec_impl.structuring.collapse import collapse_unconditional_jumps
from dec_engine.dec_impl.structuring.struct import (
    StructuringPass,
    Region,
    Loop,
    StructuredBlock,
    StructuredCFG,
)

__all__ = [
    "collapse_unconditional_jumps",
    "StructuringPass",
    "Region",
    "Loop", 
    "StructuredBlock",
    "StructuredCFG",
]
