"""
Expression tree for the decompiler.
Maps from symbolik symbols (Const, Var, Mem, Call) to typed IR operands.

Uses explicit __slots__ + __setattr__ override for immutability (no dataclass
inheritance needed). All expressions are immutable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
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
    MEMORY = auto()
    SIGN_EXTEND = auto()
    ZERO_EXTEND = auto()


class Size(Enum):
    SIZE_8 = 8
    SIZE_16 = 16
    SIZE_32 = 32
    SIZE_64 = 64
    AUTO = -1


# ── Expression base class ──


class Expression(ABC):
    """Base class for all IR expressions. Immutable."""

    @property
    @abstractmethod
    def size(self) -> Size:
        ...

    def __eq__(self, other):
        if not isinstance(other, Expression):
            return NotImplemented
        return type(self) is type(other) and self._cmp(other) == 0

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return self._hash()

    @abstractmethod
    def _cmp(self, other) -> int:
        ...

    @abstractmethod
    def _hash(self) -> int:
        ...

    def __repr__(self):
        return f"<{type(self).__name__}>"


# ── Concrete expression types ──


class Const(Expression):
    """Literal constant value."""

    __slots__ = ("_value", "_size", "_signed")

    def __init__(self, value: int, size: Size = Size.AUTO, signed: bool = False):
        object.__setattr__(self, "_value", value)
        object.__setattr__(self, "_size", size)
        object.__setattr__(self, "_signed", signed)

    @property
    def size(self) -> Size:
        return self._size

    @property
    def value(self) -> int:
        return self._value

    @property
    def signed(self) -> bool:
        return self._signed

    def __setattr__(self, name, value):
        raise AttributeError(f"Cannot modify immutable Const: {name}")

    def _cmp(self, other) -> int:
        if self._value != other._value:
            return -1 if self._value < other._value else 1
        return -1 if self._signed != other._signed else 0

    def _hash(self) -> int:
        return hash((self._value, self._signed, self._size))

    def __str__(self) -> str:
        # If size is explicitly set (not AUTO), show hex
        if self._size != Size.AUTO:
            return hex(self._value)
        return str(self._value)

    def __repr__(self) -> str:
        return f"Const({self._value}, size={self._size}, signed={self._signed})"


class Var(Expression):
    """Symbolic variable (register or temporary)."""

    __slots__ = ("_name", "_size")

    def __init__(self, name: str, size: Size = Size.AUTO):
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_size", size)

    @property
    def size(self) -> Size:
        return self._size

    @property
    def name(self) -> str:
        return self._name

    def __setattr__(self, name, value):
        raise AttributeError(f"Cannot modify immutable Var: {name}")

    def _cmp(self, other) -> int:
        return -1 if self._name < other._name else (1 if self._name > other._name else 0)

    def _hash(self) -> int:
        return hash(self._name)

    def __str__(self) -> str:
        return self._name


class MemRef(Expression):
    """Memory operand: [base + offset * scale]."""

    __slots__ = ("_base", "_offset", "_scale", "_size")

    def __init__(self, base: Expression, offset: Expression, scale: int = 1, size: Size = Size.AUTO):
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "_offset", offset)
        object.__setattr__(self, "_scale", scale)
        object.__setattr__(self, "_size", size)

    @property
    def size(self) -> Size:
        return self._size

    @property
    def base(self):
        return self._base

    @property
    def offset(self):
        return self._offset

    @property
    def scale(self) -> int:
        return self._scale

    def __setattr__(self, name, value):
        raise AttributeError(f"Cannot modify immutable MemRef: {name}")

    def _cmp(self, other) -> int:
        for attr in ("_base", "_offset", "_scale"):
            mine = getattr(self, attr)
            theirs = getattr(other, attr)
            if mine != theirs:
                return -1 if mine < theirs else 1
        return 0

    def _hash(self) -> int:
        return hash((self._base, self._offset, self._scale))

    def __str__(self):
        if self._scale == 1:
            return f"[{self._base} + {self._offset}]"
        return f"[{self._base} + {self._offset} * {self._scale}]"

    def __repr__(self) -> str:
        return f"MemRef(base={self._base}, offset={self._offset}, scale={self._scale}, size={self._size})"


class BinOp(Expression):
    """Binary operation: op(left, right)."""

    __slots__ = ("_op", "_left", "_right", "_size")

    def __init__(self, op: OpType, left: Expression, right: Expression, size: Size = Size.AUTO):
        object.__setattr__(self, "_op", op)
        object.__setattr__(self, "_left", left)
        object.__setattr__(self, "_right", right)
        object.__setattr__(self, "_size", size)

    @property
    def size(self) -> Size:
        return self._size

    @property
    def op(self) -> OpType:
        return self._op

    @property
    def left(self):
        return self._left

    @property
    def right(self):
        return self._right

    def __setattr__(self, name, value):
        raise AttributeError(f"Cannot modify immutable BinOp: {name}")

    def _cmp(self, other) -> int:
        if self._op != other._op:
            return -1 if self._op.value < other._op.value else 1
        c = self._left._cmp(other._left)
        if c:
            return c
        return self._right._cmp(other._right)

    def _hash(self) -> int:
        return hash((self._op, self._left, self._right))

    def __repr__(self):
        return f"({self._left} {self._op.name} {self._right})"


class UnOp(Expression):
    """Unary operation: op(operand)."""

    __slots__ = ("_op", "_operand", "_size")

    def __init__(self, op: OpType, operand: Expression, size: Size = Size.AUTO):
        object.__setattr__(self, "_op", op)
        object.__setattr__(self, "_operand", operand)
        object.__setattr__(self, "_size", size)

    @property
    def size(self) -> Size:
        return self._size

    @property
    def op(self) -> OpType:
        return self._op

    @property
    def operand(self):
        return self._operand

    def __setattr__(self, name, value):
        raise AttributeError(f"Cannot modify immutable UnOp: {name}")

    def _cmp(self, other) -> int:
        if self._op != other._op:
            return -1 if self._op.value < other._op.value else 1
        return self._operand._cmp(other._operand)

    def _hash(self) -> int:
        return hash((self._op, self._operand))

    def __repr__(self) -> str:
        return f"~{self._operand}"


class PhiNode(Expression):
    """SSA phi-function: phi((x1, path1), (x2, path2), ...)."""

    __slots__ = ("_operands", "_size")

    def __init__(self, operands: List[Tuple[Expression, str]], size: Size = Size.AUTO):
        object.__setattr__(self, "_operands", operands)
        object.__setattr__(self, "_size", size)

    @property
    def size(self) -> Size:
        return self._size

    @property
    def operands(self):
        return self._operands

    def __setattr__(self, name, value):
        raise AttributeError(f"Cannot modify immutable PhiNode: {name}")

    def _cmp(self, other) -> int:
        if len(self._operands) != len(other._operands):
            return len(self._operands) - len(other._operands)
        for (v1, p1), (v2, p2) in zip(self._operands, other._operands):
            if v1 != v2:
                return -1 if str(v1) < str(v2) else 1
            if p1 != p2:
                return -1 if p1 < p2 else 1
        return 0

    def _hash(self) -> int:
        return hash(tuple(self._operands))

    def __repr__(self):
        pairs = ", ".join(f"({v}, {p})" for v, p in self._operands)
        return f"phi({pairs})"


class CallExpr(Expression):
    """Function call expression."""

    __slots__ = ("_callee", "_args", "_return_size", "_size")

    def __init__(self, callee: Expression, args: List[Expression], return_size: Size = Size.AUTO):
        object.__setattr__(self, "_callee", callee)
        object.__setattr__(self, "_args", args)
        object.__setattr__(self, "_return_size", return_size)
        object.__setattr__(self, "_size", return_size)

    @property
    def size(self) -> Size:
        return self._size

    @property
    def callee(self):
        return self._callee

    @property
    def args(self):
        return self._args

    def __setattr__(self, name, value):
        raise AttributeError(f"Cannot modify immutable CallExpr: {name}")

    def _cmp(self, other) -> int:
        if self._callee != other._callee:
            return self._callee._cmp(other._callee)
        return tuple(self._args).__cmp__(tuple(other._args))

    def _hash(self) -> int:
        return hash((self._callee, tuple(self._args)))


class CastOp(Expression):
    """Type cast: cast<to>(from)."""

    __slots__ = ("_from_expr", "_to_size", "_to_signed", "_from_signed", "_size")

    def __init__(self, from_expr: Expression, to_size: Size, to_signed: bool, from_signed: bool):
        object.__setattr__(self, "_from_expr", from_expr)
        object.__setattr__(self, "_to_size", to_size)
        object.__setattr__(self, "_to_signed", to_signed)
        object.__setattr__(self, "_from_signed", from_signed)
        object.__setattr__(self, "_size", to_size)

    @property
    def size(self) -> Size:
        return self._size

    @property
    def from_expr(self):
        return self._from_expr

    @property
    def to_size(self):
        return self._to_size

    @property
    def to_signed(self):
        return self._to_signed

    @property
    def from_signed(self):
        return self._from_signed

    def __setattr__(self, name, value):
        raise AttributeError(f"Cannot modify immutable CastOp: {name}")

    def _cmp(self, other) -> int:
        for attr in ("_from_expr", "_to_size", "_to_signed", "_from_signed"):
            mine = getattr(self, attr)
            theirs = getattr(other, attr)
            if mine != theirs:
                return -1 if mine < theirs else 1
        return 0

    def _hash(self) -> int:
        return hash((self._from_expr, self._to_size, self._to_signed, self._from_signed))

    def __repr__(self) -> str:
        sign = "s" if self._to_signed else "u"
        return f"cast<{self._to_size.name}_{sign}>({self._from_expr})"


# ── Builders / factories ──


def sym_to_expr(effect, target_size: Optional[Size] = None) -> Expression:
    """Convert a Vivisect symbolik symbol to expression tree.

    Bridges Vivisect's symboliks to our IR via SymbolikAdaptor.
    """
    from dec_engine.dec_impl.ir.builder import SymbolikAdaptor
    return SymbolikAdaptor.convert(effect, target_size)


def build_mem_ref(
    base: Expression,
    offset: Optional[Expression] = None,
    scale: int = 1,
    size: Size = Size.AUTO,
) -> MemRef:
    """Build a MemRef expression."""
    if offset is None:
        size = getattr(base, "size", size)
        offset = Const(value=0, size=size)
    if not isinstance(offset, Expression):
        offset = Const(value=int(offset), size=getattr(base, "size", size))
    return MemRef(base, offset, scale, size)
