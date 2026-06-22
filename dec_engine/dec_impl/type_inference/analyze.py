"""
Type inference engine for the decompiler.

Maps from Reko's TypeAnalyzer to Vivisect's analysis infrastructure.
Uses constraint lattice propagation and pattern-based struct/signature inference.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Set, Tuple
from dec_engine.dec_impl.ir.expression import (
    Expression,
    Var,
    MemRef,
    BinOp,
    UnOp,
    Const,
    CallExpr,
    CastOp,
    Size,
)


class DataType:
    """Typed IR type. Corresponds to Reko's DataType hierarchy."""

    def __init__(self, name: str, size: Size, signed: bool = False):
        self.name = name  # e.g. "int", "char", "void", "struct_Foo", "pointer"
        self.size = size  # Size enum
        self.signed = signed

    def __eq__(self, other):
        if not isinstance(other, DataType):
            return False
        return self.name == other.name and self.size == other.size

    def __repr__(self):
        prefix = "signed " if self.signed else "unsigned "
        return f"{prefix}{self.name}<{self.size}>"

    @classmethod
    def from_size(cls, size: Size, signed: bool = False) -> 'DataType':
        """Create a DataType from a Size enum."""
        size_map = {
            Size.SIZE_8: "char",
            Size.SIZE_16: "short",
            Size.SIZE_32: "int",
            Size.SIZE_64: "long",
            Size.AUTO: "unknown",
        }
        return cls(size_map.get(size, "unknown"), size, signed)


class TypeEnvironment:
    """Environment tracking types for all SSA variables."""

    def __init__(self):
        self.types: Dict[Var, DataType] = {}
        self.struct_types: Dict[str, DataType] = {}
        self.type_aliases: Dict[str, str] = {}
        self.var_map: Dict[str, Var] = {}

    def get_type(self, var: Var) -> Optional[DataType]:
        return self.types.get(var, None)

    def get_type_by_name(self, name: str) -> Optional[DataType]:
        self.var_map.setdefault(name, Var(name))
        return self.types.get(self.var_map[name], None)

    def set_type(self, var: Var, dtype: DataType):
        self.types[var] = dtype

    def set_type_by_name(self, name: str, dtype: DataType):
        self.var_map.setdefault(name, Var(name))
        self.types[self.var_map[name]] = dtype


class TypeAnalyzer:
    """
    Type inference engine for the decompiler.

    Pipeline:
    1. ExpressionNormalizer -> normalize expression patterns
    2. EquivalenceClassBuilder -> group equivalent expressions
    3. TypeCollector -> collect types from patterns
    4. DataTypeBuilder -> build types from collected data
    5. TypeTransformer -> transform raw types to structured types
    6. ComplexTypeNamer -> name structs/unions/enums
    """

    def __init__(self, env: Optional[TypeEnvironment] = None):
        self.env = env or TypeEnvironment()
        self.pending_phis: Dict[str, Var] = {}

    def analyze(self) -> TypeEnvironment:
        """Run the full type inference pass."""
        # Phase 1: Infer types from constant propagation
        self._infer_from_constants()

        # Phase 2: Infer types from memory access patterns
        self._infer_from_memory()

        # Phase 3: Infer struct types from field patterns
        self._infer_structs()

        return self.env

    def _infer_from_constants(self):
        """Infer types from constant operand values."""
        pass  # Placeholder - uses known const ranges

    def _infer_from_memory(self):
        """Infer types from memory access patterns."""
        pass  # Placeholder - uses MemRef analysis

    def _infer_structs(self):
        """Infer struct types from field access patterns."""
        pass  # Placeholder - tracks consistent byte offsets

    def infer_type_from_expr(self, expr: Expression) -> DataType:
        """Infer type from an expression by traversing."""
        if isinstance(expr, Const):
            return DataType.from_size(expr.size)
        elif isinstance(expr, Var):
            return self.env.get_type(expr) or DataType("unknown", Size.AUTO)
        elif isinstance(expr, MemRef):
            size_map = {Size.SIZE_8: "uchar", Size.SIZE_16: "ushort",
                        Size.SIZE_32: "uint", Size.SIZE_64: "ulong"}
            return DataType(size_map.get(expr.size, "void") + "*", expr.size)
        elif isinstance(expr, BinOp):
            return self._infer_binop_type(expr)
        elif isinstance(expr, UnOp):
            return self._infer_unop_type(expr)
        elif isinstance(expr, CallExpr):
            return self._infer_call_return_type(expr)
        elif isinstance(expr, CastOp):
            return DataType.from_size(expr.to_size, expr.to_signed)

        return DataType("int", Size.AUTO)

    def _infer_binop_type(self, expr: BinOp) -> DataType:
        """Infer type of binary operation."""
        left_type = self.infer_type_from_expr(expr.left)
        right_type = self.infer_type_from_expr(expr.right)
        if left_type.size != Size.AUTO:
            return DataType.from_size(left_type.size, left_type.signed)
        if right_type.size != Size.AUTO:
            return DataType.from_size(right_type.size, right_type.signed)
        return left_type

    def _infer_unop_type(self, expr: UnOp) -> DataType:
        """Infer type of unary operation. Result type matches operand."""
        operand_type = self.infer_type_from_expr(expr.operand)
        if operand_type.size == Size.AUTO:
            return operand_type
        # Preserve the operand's full type info (name, size, signedness)
        return DataType(operand_type.name, operand_type.size, operand_type.signed)

    def _infer_call_return_type(self, expr: CallExpr) -> DataType:
        """Infer return type for a call."""
        return DataType.from_size(Size.AUTO)  # Default: unknown return

    def merge_phi_types(self, phi_ops: List[Tuple[Var, Optional[str]]]):
        """Merge types for a phi node: use the largest common supertype."""
        if not phi_ops:
            return self.env.type_aliases.get("$phi", "")

        types: List[DataType] = []
        for var, _ in phi_ops:
            dtype = self.env.get_type(var)
            if dtype and dtype not in types:
                types.append(dtype)

        if len(types) == 1:
            return types[0]

        # Multiple types: use largest common supertype
        # 'int' is a supertype of other types regardless of size
        for dt in types:
            if dt.name == "int":
                return DataType("int", Size.AUTO)

        return DataType("unknown", Size.AUTO)
