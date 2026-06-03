"""
Expression tree for the decompiler.
Maps from symbolik symbols (Const, Var, Mem, Call) to typed IR operands.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, List, Tuple


class OpType(Enum):
    # Arithmetic
    ADD = auto()
    SUB = auto()
    MUL = auto()
    DIV = auto()
    MOD = auto()
    # Bitwise
    AND = auto()
    OR = auto()
    XOR = auto()
    NOT = auto()
    SHL = auto()
    SHR = auto()
    SAR = auto()
    # Comparison
    EQ = auto()
    NE = auto()
    LT = auto()
    GT = auto()
    LE = auto()
    GE = auto()
    # Type
    CAST = auto()
    # Memory / pointer
    LOAD = auto()
    STORE = auto()
    PTR_ADD = auto()
    PTR_SUB = auto()
    # Control
    CALL = auto()
    PHI = auto()
    MEMORY = auto()  # placeholder to prevent GC
    SIGN_EXTEND = auto()
    ZERO_EXTEND = auto()


class Size(Enum):
    SIZE_8 = 8
    SIZE_16 = 16
    SIZE_32 = 32
    SIZE_64 = 64
    # Auto-infer
    AUTO = -1


@dataclass(frozen=True)
class Expression(ABC):
    size: Size
    _hash: int = field(init=False, repr=False)

    def __post_init__(self):
        object.__setattr__(
            self, "_hash", hash((type(self).__name__, self.size, self._inner_hash()))
        )

    @abstractmethod
    def _inner_hash(self) -> int:
        ...

    @abstractmethod
    def _inner_cmp(self, other) -> int:
        ...

    def __eq__(self, other):
        return type(self) is type(other) and self._inner_cmp(other) == 0

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return self._hash


@dataclass(frozen=True)
class Const(Expression):
    value: int
    signed: bool = False
    size: Size = Size.AUTO

    def _inner_hash(self):
        return hash((self.value, self.signed))

    def _inner_cmp(self, other):
        if self.value != other.value:
            return -1 if self.value < other.value else 1
        return -1 if self.signed != other.signed else 0


@dataclass(frozen=True)
class Var(Expression):
    """A symbolic variable (register or temporary)."""

    name: str  # e.g. "eax", "$t0", "arg1"
    size: Size = Size.AUTO

    def _inner_hash(self):
        return hash(self.name)

    def _inner_cmp(self, other):
        return -1 if self.name < other.name else (1 if self.name > other.name else 0)


@dataclass(frozen=True)
class MemRef(Expression):
    """Memory load/store operand: [base + offset * scale]"""

    base: Expression
    offset: Expression
    scale: int = 1
    size: Size = Size.AUTO

    def _inner_hash(self):
        return hash((self.base, self.offset, self.scale))

    def _inner_cmp(self, other):
        for attr in ("base", "offset", "scale"):
            mine = getattr(self, attr)
            theirs = getattr(other, attr)
            if mine != theirs:
                return -1 if mine < theirs else 1
        return 0


@dataclass(frozen=True)
class BinOp(Expression):
    """Binary operation: op(left, right)"""

    op: OpType
    left: Expression
    right: Expression
    size: Size = Size.AUTO

    def _inner_hash(self):
        return hash((self.op, self.left, self.right))

    def _inner_cmp(self, other):
        if self.op != other.op:
            return -1 if self.op.value < other.op.value else 1
        if self.left != other.left:
            return self.left._inner_cmp(other.left)
        return self.right._inner_cmp(other.right)

    def __repr__(self):
        return f"({self.left} {self.op.name} {self.right})"


@dataclass(frozen=True)
class UnOp(Expression):
    """Unary operation: op(operand)"""

    op: OpType
    operand: Expression
    size: Size = Size.AUTO

    def _inner_hash(self):
        return hash((self.op, self.operand))

    def _inner_cmp(self, other):
        if self.op != other.op:
            return -1 if self.op.value < other.op.value else 1
        return self.operand._inner_cmp(other.operand)


@dataclass(frozen=True)
class PhiNode(Expression):
    """SSA phi-function: phi((x1, path1), (x2, path2), ...)"""

    operands: List[Tuple[Expression, str]]  # (value, predecessor_label)
    size: Size = Size.AUTO

    def _inner_hash(self):
        return hash(tuple(self.operands))

    def _inner_cmp(self, other):
        if len(self.operands) != len(other.operands):
            return len(self.operands) - len(other.operands)
        for (v1, p1), (v2, p2) in zip(self.operands, other.operands):
            if v1 != v2:
                return -1 if str(v1) < str(v2) else 1
            if p1 != p2:
                return -1 if p1 < p2 else 1
        return 0

    def __repr__(self):
        pairs = ", ".join(f"({v}, {p})" for v, p in self.operands)
        return f"phi({pairs})"


@dataclass(frozen=True)
class CallExpr(Expression):
    """Function call in IR"""

    callee: Expression
    args: List[Expression]
    return_size: Size = Size.AUTO

    def _inner_hash(self):
        return hash((self.callee, tuple(self.args)))

    def _inner_cmp(self, other):
        if self.callee != other.callee:
            return self.callee._inner_cmp(other.callee)
        return tuple(self.args).__cmp__(tuple(other.args))


@dataclass(frozen=True)
class CastOp(Expression):
    """Type cast: cast<to>(from)"""

    from_expr: Expression
    to_size: Size
    to_signed: bool
    from_signed: bool

    def _inner_hash(self):
        return hash((self.from_expr, self.to_size, self.to_signed, self.from_signed))

    def _inner_cmp(self, other):
        for attr in ("from_expr", "to_size", "to_signed", "from_signed"):
            mine = getattr(self, attr)
            theirs = getattr(other, attr)
            if mine != theirs:
                return -1 if mine < theirs else 1
        return 0


# Builders / factories
def sym_to_expr(effect, target_size: Optional[Size] = None) -> Expression:
    """Convert a symbolik symbol to expression tree.
    This is the bridge from Vivisect's symboliks to our IR.
    """
    from vivisect.dec_impl.ir.symbolik_adapter import SymbolikAdaptor

    return SymbolikAdaptor.convert(effect, target_size)


def build_mem_ref(
    base: Expression,
    offset: Optional[Expression] = None,
    scale: int = 1,
    size: Size = Size.AUTO,
) -> MemRef:
    if offset is None:
        size = getattr(base, "size", size)
        offset = Const(0, size=size)
    if not isinstance(offset, Expression):
        offset = Const(offset, size=getattr(base, "size", size))
    return MemRef(base, offset, scale, size)
