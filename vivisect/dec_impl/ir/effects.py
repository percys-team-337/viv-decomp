"""
IR instruction types — the fundamental "statements" that make up a decompiled function.
Equivalent to Reko's Tier 2 (Code/IL layer) but simplified for Python.
Each instruction maps directly from a Vivisect opcode.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import auto, Enum
from typing import Optional, List


class InstrClass(Enum):
    """Instruction class for control flow analysis."""

    NORMAL = auto()
    BRANCH = auto()
    JUMP = auto()
    CALL = auto()
    RETURN = auto()
    SIDE_EFFECT = auto()
    PHI = auto()  # Phi-function (SSA)
    NOOP = auto()


@dataclass
class Assignment:
    """The fundamental IR instruction: dst = src"""

    destination: Expression  # Can be Var or MemRef
    source: Expression
    class_: InstrClass = InstrClass.NORMAL
    operands: List = field(default_factory=list)
    mnemonic: str = ""  # Original assembly mnemonic
    address: int = 0  # Source address

    def __repr__(self):
        return f"{self.destination} = {self.source}"


@dataclass
class Branch:
    """Conditional or unconditional branch"""

    condition: Optional[Expression]  # None = unconditional
    true_target: "BasicBlock"
    false_target: Optional["BasicBlock"] = None  # None for unconditional
    class_: InstrClass = InstrClass.BRANCH
    address: int = 0
    mnemonic: str = ""
    jump_table_index: Optional[Expression] = None  # For switch/jump-table

    def __repr__(self):
        if self.condition is None:
            return f"jump 0x{self.true_target.addr:x}"
        return f"if ({self.condition}) jump 0x{self.true_target.addr:x}"


@dataclass
class Call:
    """Function call in IR"""

    callee: Expression
    args: List[Expression]
    return_var: Optional[Var] = None
    class_: InstrClass = InstrClass.CALL
    address: int = 0
    mnemonic: str = ""


@dataclass
class PhiInstruction:
    """Phi-function for SSA variable definition at block entry"""

    variable: Var
    operands: List[tuple[Expression, "BasicBlock"]]  # (value, predecessor_block)
    class_: InstrClass = InstrClass.PHI

    def __repr__(self):
        parts = ", ".join(
            f"{v} from BB@0x{b.addr:x}" for v, b in self.operands
        )
        return f"{self.variable.name}: phi({parts})"


@dataclass
class NoOp:
    """No-operation marker (used for gaps or alignment)"""

    address: int = 0
    size: int = 1


# Allow all IR instruction types to be used as valid instructions
from vivisect.dec_impl.ir.expression import (  # noqa: E402
    Expression,
    Var,
    MemRef,
)

Instruction = Assignment | Branch | Call | PhiInstruction | NoOp


def make_branch_condition(
    cond_expr: Expression,
    target: "BasicBlock",
) -> Branch:
    """Helper to quickly construct a conditional branch."""
    return Branch(
        condition=cond_expr,
        true_target=target,
        address=getattr(target, "addr", 0),
        mnemonic="jz",
    )
