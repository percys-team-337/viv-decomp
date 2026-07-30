"""
Tests for ir/expression.py — Expression tree construction, immutability, equality, hashing.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from dec_engine.dec_impl.ir.expression import (
    Expression, Const, Var, MemRef, BinOp, UnOp, PhiNode, CallExpr, CastOp,
    OpType, Size, build_mem_ref,
)


class TestConst:
    def test_construct_with_defaults(self):
        c = Const(42)
        assert c.value == 42
        assert c.size == Size.AUTO
        assert c.signed is False

    def test_construct_with_all_args(self):
        c = Const(value=255, size=Size.SIZE_8, signed=False)
        assert c.value == 255
        assert c.size == Size.SIZE_8
        assert c.signed is False

    def test_str_representation_hex(self):
        # str() returns hex when size is explicitly set
        assert str(Const(0x2a, size=Size.SIZE_32)) == "0x2a"
        # When size is AUTO (default), str() returns decimal
        assert str(Const(42, size=Size.AUTO)) == "42"

    def test_immutable(self):
        c = Const(42)
        with pytest.raises(AttributeError):
            c.value = 99
        with pytest.raises(AttributeError):
            c.size = Size.SIZE_64

    def test_equality(self):
        c1 = Const(42, Size.SIZE_32)
        c2 = Const(42, Size.SIZE_32)
        c3 = Const(43, Size.SIZE_32)
        c4 = Const(42, Size.SIZE_32, signed=False)
        c5 = Const(42, Size.SIZE_32, signed=True)
        assert c1 == c2
        assert c1 != c3
        assert c1 == c4
        assert c1 != c5

    def test_hashing(self):
        c1 = Const(42, Size.SIZE_32)
        c2 = Const(42, Size.SIZE_32)
        assert hash(c1) == hash(c2)

    def test_in_set(self):
        c1 = Const(42, Size.SIZE_32)
        c2 = Const(42, Size.SIZE_32)
        s = {c1, c2}
        assert len(s) == 1

    def test_negative_value(self):
        c = Const(-1, Size.SIZE_32)
        assert c.value == -1

    def test_hash_stable(self):
        c = Const(42, Size.SIZE_32)
        h1 = hash(c)
        h2 = hash(c)
        assert h1 == h2


class TestVar:
    def test_construct(self):
        v = Var("eax", Size.SIZE_32)
        assert v.name == "eax"
        assert v.size == Size.SIZE_32

    def test_construct_default_size(self):
        v = Var("esp")
        assert v.size == Size.AUTO

    def test_equality(self):
        v1 = Var("eax", Size.SIZE_32)
        v2 = Var("eax", Size.SIZE_32)
        v3 = Var("ecx", Size.SIZE_32)
        assert v1 == v2
        assert v1 != v3

    def test_hashing(self):
        v1 = Var("eax", Size.SIZE_32)
        v2 = Var("eax", Size.SIZE_32)
        assert hash(v1) == hash(v2)

    def test_immutable(self):
        v = Var("eax")
        with pytest.raises(AttributeError):
            v.name = "ebx"


class TestMemRef:
    def test_construct(self):
        base = Var("rsp", Size.SIZE_64)
        offset = Const(0x10, Size.SIZE_64)
        m = MemRef(base, offset, scale=1, size=Size.SIZE_64)
        assert m.base == base
        assert m.offset == offset
        assert m.scale == 1
        assert m.size == Size.SIZE_64

    def test_construct_complex_offset(self):
        base = Var("rbp", Size.SIZE_64)
        offset = BinOp(op=OpType.MUL, left=Const(4, Size.SIZE_64), right=Var("rbx", Size.SIZE_64), size=Size.SIZE_64)
        m = MemRef(base, offset, scale=1, size=Size.SIZE_64)
        assert m.scale == 1

    def test_str_representation(self):
        base = Var("rbp", Size.SIZE_64)
        offset = Const(8, Size.SIZE_64)
        m = MemRef(base, offset)
        assert "[" in str(m)
        assert "++" in str(m) or "+" in str(m)

    def test_equality(self):
        base1 = Var("rbp", Size.SIZE_64)
        base2 = Var("rbp", Size.SIZE_64)
        off1 = Const(8, Size.SIZE_64)
        off2 = Const(8, Size.SIZE_64)
        m1 = MemRef(base1, off1)
        m2 = MemRef(base2, off2)
        assert m1 == m2

    def test_hashing(self):
        base = Var("rbp", Size.SIZE_64)
        off = Const(8, Size.SIZE_64)
        m1 = MemRef(base, off)
        m2 = MemRef(base, off)
        assert hash(m1) == hash(m2)

    def test_immutable(self):
        base = Var("rsp", Size.SIZE_64)
        off = Const(0, Size.SIZE_64)
        m = MemRef(base, off)
        with pytest.raises(AttributeError):
            m.scale = 2


class TestBinOp:
    def test_construct(self):
        left = Const(1, Size.SIZE_32)
        right = Const(2, Size.SIZE_32)
        b = BinOp(op=OpType.ADD, left=left, right=right, size=Size.SIZE_32)
        assert b.op == OpType.ADD
        assert b.left == left
        assert b.right == right
        assert b.size == Size.SIZE_32

    def test_repr_contains_op_name(self):
        left = Const(1, Size.SIZE_32)
        right = Const(2, Size.SIZE_32)
        b = BinOp(op=OpType.XOR, left=left, right=right)
        assert "XOR" in repr(b)

    def test_equality(self):
        l1, r1 = Const(1, Size.SIZE_32), Const(2, Size.SIZE_32)
        l2, r2 = Const(1, Size.SIZE_32), Const(2, Size.SIZE_32)
        b1 = BinOp(OpType.ADD, l1, r1)
        b2 = BinOp(OpType.ADD, l2, r2)
        assert b1 == b2

    def test_inequality_different_op(self):
        l, r = Const(1, Size.SIZE_32), Const(2, Size.SIZE_32)
        b1 = BinOp(OpType.ADD, l, r)
        b2 = BinOp(OpType.SUB, l, r)
        assert b1 != b2

    def test_immutable(self):
        b = BinOp(OpType.ADD, Const(1, Size.SIZE_32), Const(2, Size.SIZE_32))
        with pytest.raises(AttributeError):
            b.op = OpType.SUB


class TestUnOp:
    def test_construct(self):
        operand = Var("eax", Size.SIZE_32)
        u = UnOp(op=OpType.NOT, operand=operand, size=Size.SIZE_32)
        assert u.op == OpType.NOT
        assert u.operand == operand

    def test_repr(self):
        operand = Var("eax", Size.SIZE_32)
        u = UnOp(op=OpType.NOT, operand=operand)
        assert "~" in repr(u)

    def test_equality(self):
        op1 = Var("eax", Size.SIZE_32)
        op2 = Var("eax", Size.SIZE_32)
        u1 = UnOp(OpType.NOT, op1)
        u2 = UnOp(OpType.NOT, op2)
        assert u1 == u2


class TestPhiNode:
    def test_construct(self):
        c1 = Const(1, Size.SIZE_32)
        c2 = Const(2, Size.SIZE_32)
        phi = PhiNode([(c1, "block_a"), (c2, "block_b")], size=Size.SIZE_32)
        assert len(phi.operands) == 2
        assert phi.operands[0][0] == c1
        assert phi.operands[0][1] == "block_a"

    def test_repr(self):
        phi = PhiNode([(Const(1, Size.SIZE_32), "a"), (Const(2, Size.SIZE_32), "b")])
        assert "phi(" in repr(phi)

    def test_equality(self):
        phi1 = PhiNode([(Const(1, Size.SIZE_32), "a"), (Const(2, Size.SIZE_32), "b")])
        phi2 = PhiNode([(Const(1, Size.SIZE_32), "a"), (Const(2, Size.SIZE_32), "b")])
        assert phi1 == phi2


class TestCallExpr:
    def test_construct(self):
        callee = Var("printf", Size.SIZE_64)
        args = [Const(1, Size.SIZE_64), Const(2, Size.SIZE_64)]
        c = CallExpr(callee=callee, args=args, return_size=Size.SIZE_32)
        assert c.callee == callee
        assert len(c.args) == 2
        assert c.size == Size.SIZE_32


class TestCastOp:
    def test_construct(self):
        src = Const(42, Size.SIZE_32)
        cast_op = CastOp(from_expr=src, to_size=Size.SIZE_16, to_signed=True, from_signed=False)
        assert cast_op.from_expr == src
        assert cast_op.to_size == Size.SIZE_16
        assert cast_op.to_signed is True
        assert cast_op.from_signed is False

    def test_repr(self):
        src = Const(42, Size.SIZE_32)
        cast_op = CastOp(from_expr=src, to_size=Size.SIZE_16, to_signed=True, from_signed=False)
        assert "cast<" in repr(cast_op)
        assert "s" in repr(cast_op)

    def test_size_is_to_size(self):
        src = Const(42, Size.SIZE_32)
        cast_op = CastOp(from_expr=src, to_size=Size.SIZE_16, to_signed=False, from_signed=False)
        assert cast_op.size == Size.SIZE_16


class TestBuildMemRef:
    def test_with_all_args(self):
        base = Var("rbp", Size.SIZE_64)
        offset = Const(8, Size.SIZE_64)
        m = build_mem_ref(base, offset, scale=1, size=Size.SIZE_64)
        assert m.base == base
        assert m.offset == offset
        assert m.scale == 1

    def test_with_offset_as_int(self):
        base = Var("rsp", Size.SIZE_32)
        m = build_mem_ref(base, offset=0x10, size=Size.SIZE_32)
        assert m.offset.value == 0x10

    def test_with_none_offset(self):
        base = Var("rsp", Size.SIZE_32)
        m = build_mem_ref(base, offset=None, size=Size.SIZE_32)
        assert m.offset.value == 0


class TestOpType:
    def test_all_ops_present(self):
        expected = ["ADD", "SUB", "MUL", "DIV", "MOD", "AND", "OR", "XOR",
                     "NOT", "SHL", "SHR", "SAR", "EQ", "NE", "LT", "GT",
                     "LE", "GE", "CAST", "LOAD", "STORE", "PTR_ADD", "PTR_SUB",
                     "CALL", "PHI", "MEMORY", "SIGN_EXTEND", "ZERO_EXTEND"]
        all_op_types = [e.name for e in OpType]
        for name in expected:
            assert name in all_op_types, f"Missing op type: {name}"

    def test_all_values_are_auto(self):
        values = [e.value for e in OpType]
        assert values == list(range(1, len(values) + 1))


class TestSize:
    def test_standard_sizes(self):
        assert Size.SIZE_8.value == 8
        assert Size.SIZE_16.value == 16
        assert Size.SIZE_32.value == 32
        assert Size.SIZE_64.value == 64
        assert Size.AUTO.value == -1


class TestExpressionBasics:
    def test_immutable_via_subclass(self):
        expressions = [
            ("Const", Const(42)),
            ("Var", Var("eax")),
            ("MemRef", MemRef(Var("rsp", Size.SIZE_64), Const(0, Size.SIZE_64))),
            ("BinOp", BinOp(OpType.ADD, Const(1, Size.SIZE_32), Const(2, Size.SIZE_32))),
            ("UnOp", UnOp(OpType.NOT, Var("eax"))),
            ("PhiNode", PhiNode([(Const(1, Size.SIZE_32), "a")])),
        ]
        for name, exp in expressions:
            assert hash(exp) is not None, f"{name} is not hashable"

    def test_hash_consistency_with_nested_expressions(self):
        base = Var("rbp", Size.SIZE_64)
        offset = Const(8, Size.SIZE_64)
        m1 = MemRef(base, offset)
        m2 = MemRef(base, offset)
        assert hash(m1) == hash(m2)
