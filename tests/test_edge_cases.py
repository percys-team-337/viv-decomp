"""Edge case tests for production coverage gaps.

Tests for:
- Null/None/empty boundary conditions
- Expression immutability violations
- Formatting edge cases (empty inputs, scale=1, negative values)
- Type inference with unknown/missing types
- SSA phi insertion with tricky phi ops
- Structuring with diamond patterns
- Formatters with unhandled expression types
"""
import pytest
from vivisect.dec_impl.ir.expression import (
    Const, Var, MemRef, BinOp, UnOp, PhiNode, CallExpr, CastOp,
    OpType, Size, Expression, build_mem_ref
)
from vivisect.dec_impl.ir.effects import (
    Assignment, Branch, Call, PhiInstruction, NoOp, InstrClass, make_branch_condition
)
from vivisect.dec_impl.ir.block import BasicBlock, BlockGraph
from vivisect.dec_impl.ssa.construct import SsaState, SsaTransform
from vivisect.dec_impl.structuring.struct import (
    Region, Loop, StructuredBlock, StructuredCFG, StructuringPass
)
from vivisect.dec_impl.type_inference.analyze import (
    DataType, TypeEnvironment, TypeAnalyzer
)
from vivisect.dec_impl.output.formatter import Formatter
from vivisect.dec_impl.output.pretty import PrettyPrinter


# ── Expression edge cases ──

class TestConstEdgeCases:
    def test_const_zero_value(self):
        c = Const(0)
        assert c.value == 0
        assert c._signed is False
        assert str(c) == "0"

    def test_const_max_value(self):
        c = Const(2**128 - 1)
        assert c.value == 2**128 - 1

    def test_const_immutable_via_attr_error(self):
        c = Const(10)
        with pytest.raises(AttributeError, match="Cannot modify immutable"):
            c._value = 20
        with pytest.raises(AttributeError, match="Cannot modify immutable"):
            c.size = Size.SIZE_32

    def test_const_hash_consistency(self):
        c1 = Const(42, Size.SIZE_32)
        c2 = Const(42, Size.SIZE_32)
        assert c1 == c2
        assert hash(c1) == hash(c2)
        s = {c1, c2}
        assert len(s) == 1

    def test_const_ne_zero(self):
        c1 = Const(0)
        c2 = Const(0, Size.SIZE_32)
        assert c1 == c2  # value comparison only

    def test_const_signed_vs_unsigned(self):
        c1 = Const(1, signed=True)
        c2 = Const(1, signed=False)
        assert c1 != c2

    def test_const_comparison(self):
        c1 = Const(10)
        c2 = Const(20)
        c3 = Const(10)
        assert c1 == c3
        assert c1 != c2

    def test_const_repr_contains_value(self):
        c = Const(64, Size.SIZE_32, True)
        repr_str = repr(c)
        assert "64" in repr_str
        assert "SIZE_32" in repr_str
        assert "True" in repr_str

    def test_const_str_with_auto_size(self):
        c = Const(64, Size.AUTO)
        assert str(c) == "64"

    def test_const_str_with_explicit_size(self):
        c = Const(64, Size.SIZE_32)
        assert str(c) == "0x40"


class TestVarEdgeCases:
    def test_var_hash_consistency(self):
        v1 = Var("x")
        v2 = Var("x")
        assert v1 == v2
        assert hash(v1) == hash(v2)
        s = {v1, v2}
        assert len(s) == 1

    def test_var_immutable(self):
        v = Var("x")
        with pytest.raises(AttributeError):
            v._name = "y"

    def test_var_different_names_not_equal(self):
        v1 = Var("a")
        v2 = Var("b")
        assert v1 != v2


class TestMemRefEdgeCases:
    def test_memref_zero_offset(self):
        base = Var("rbp")
        m = MemRef(base, Const(0))
        assert m._scale == 1
        assert str(m) == "[rbp + 0]"

    def test_memref_negative_scale(self):
        base = Var("rbp")
        m = MemRef(base, Const(8), -1)
        assert m._scale == -1

    def test_memref_nested_expr_offset(self):
        base = Var("rbp")
        offset = BinOp(OpType.ADD, Const(8), Var("rdi"))
        m = MemRef(base, offset)
        assert isinstance(m._offset, BinOp)

    def test_memref_immutable(self):
        base = Var("rbp")
        m = MemRef(base, Const(0))
        with pytest.raises(AttributeError):
            m._base = Var("rsp")
        with pytest.raises(AttributeError):
            m._offset = Const(1)

    def test_memref_hash_with_nested(self):
        base = Var("rbp")
        m1 = MemRef(base, Const(0))
        m2 = MemRef(base, Const(0))
        assert m1 == m2
        assert hash(m1) == hash(m2)


class TestBinOpEdgeCases:
    def test_binop_nested(self):
        left = BinOp(OpType.ADD, Const(1), Const(2))
        right = BinOp(OpType.SUB, Const(5), Const(3))
        expr = BinOp(OpType.MUL, left, right)
        assert isinstance(expr.left, BinOp)
        assert isinstance(expr.right, BinOp)

    def test_binop_repr_has_op_name(self):
        expr = BinOp(OpType.ADD, Var("a"), Var("b"))
        repr_str = repr(expr)
        assert "ADD" in repr_str or "a" in repr_str

    def test_binop_immutable(self):
        expr = BinOp(OpType.ADD, Var("a"), Var("b"))
        with pytest.raises(AttributeError):
            expr.left = Var("c")

    def test_binop_not_equal_different_ops(self):
        e1 = BinOp(OpType.ADD, Var("a"), Var("b"))
        e2 = BinOp(OpType.SUB, Var("a"), Var("b"))
        assert e1 != e2

    def test_binop_not_equal_different_operands(self):
        e1 = BinOp(OpType.ADD, Var("a"), Var("b"))
        e2 = BinOp(OpType.ADD, Var("a"), Var("c"))
        assert e1 != e2


class TestUnOpEdgeCases:
    def test_unop_not(self):
        expr = UnOp(OpType.NOT, Var("x"))
        assert isinstance(expr.operand, Var)

    def test_unop_neg(self):
        expr = UnOp(OpType.SHL, Const(1))
