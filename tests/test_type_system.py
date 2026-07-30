"""
Tests for type_inference/analyze.py — DataType, TypeEnvironment, TypeAnalyzer.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from dec_engine.dec_impl.type_inference.analyze import DataType, TypeEnvironment, TypeAnalyzer
from dec_engine.dec_impl.ir.expression import Const, Var, MemRef, BinOp, UnOp, OpType, Size, CallExpr, CastOp


# ── DataType ──

class TestDataType:
    def test_construct(self):
        dt = DataType(name="int", size=Size.SIZE_32, signed=True)
        assert dt.name == "int"
        assert dt.size == Size.SIZE_32
        assert dt.signed is True

    def test_construct_unsigned(self):
        dt = DataType(name="uint", size=Size.SIZE_32, signed=False)
        assert dt.signed is False

    def test_construct_default_signed(self):
        dt = DataType(name="int", size=Size.SIZE_32)
        assert dt.signed is False

    def test_from_size_8(self):
        dt = DataType.from_size(Size.SIZE_8)
        assert dt.name == "char"
        assert dt.size == Size.SIZE_8

    def test_from_size_16(self):
        dt = DataType.from_size(Size.SIZE_16)
        assert dt.name == "short"
        assert dt.size == Size.SIZE_16

    def test_from_size_32(self):
        dt = DataType.from_size(Size.SIZE_32)
        assert dt.name == "int"
        assert dt.size == Size.SIZE_32

    def test_from_size_64(self):
        dt = DataType.from_size(Size.SIZE_64)
        assert dt.name == "long"
        assert dt.size == Size.SIZE_64

    def test_from_size_auto(self):
        dt = DataType.from_size(Size.AUTO)
        assert dt.name == "unknown"

    def test_eq_same(self):
        d1 = DataType("int", Size.SIZE_32, signed=True)
        d2 = DataType("int", Size.SIZE_32, signed=True)
        assert d1 == d2

    def test_eq_different_name(self):
        d1 = DataType("int", Size.SIZE_32)
        d2 = DataType("char", Size.SIZE_32)
        assert d1 != d2

    def test_eq_different_size(self):
        d1 = DataType("int", Size.SIZE_32)
        d2 = DataType("int", Size.SIZE_64)
        assert d1 != d2

    def test_eq_non_dtype(self):
        dt = DataType("int", Size.SIZE_32)
        assert dt != "int"
        assert dt != None

    def test_repr_signed(self):
        dt = DataType("int", Size.SIZE_32, signed=True)
        r = repr(dt)
        assert "signed" in r
        assert "int" in r

    def test_repr_unsigned(self):
        dt = DataType("int", Size.SIZE_32, signed=False)
        r = repr(dt)
        assert "unsigned" in r

    def test_from_size_signed_true(self):
        dt = DataType.from_size(Size.SIZE_32, signed=True)
        assert dt.signed is True
        assert dt.name == "int"


# ── TypeEnvironment ──

class TestTypeEnvironment:
    def test_construct_empty(self):
        env = TypeEnvironment()
        assert env.types == {}
        assert env.struct_types == {}
        assert env.type_aliases == {}
        assert env.var_map == {}

    def test_get_type_missing_var(self):
        env = TypeEnvironment()
        result = env.get_type(Var("x", Size.SIZE_32))
        assert result is None

    def test_set_type(self):
        env = TypeEnvironment()
        var = Var("x", Size.SIZE_32)
        dtype = DataType("int", Size.SIZE_32)
        env.set_type(var, dtype)

    def test_get_type_after_set(self):
        env = TypeEnvironment()
        var = Var("x", Size.SIZE_32)
        dtype = DataType("int", Size.SIZE_32)
        env.set_type(var, dtype)
        result = env.get_type(var)
        assert result is dtype

    def test_get_type_by_name(self):
        env = TypeEnvironment()
        dtype = DataType("int", Size.SIZE_32)
        env.set_type_by_name("x", dtype)
        result = env.get_type_by_name("x")
        assert result is dtype

    def test_get_type_by_name_undefined(self):
        env = TypeEnvironment()
        result = env.get_type_by_name("unknown")
        assert result is None

    def test_set_type_by_name_creates_var_map(self):
        env = TypeEnvironment()
        dtype = DataType("int", Size.SIZE_32)
        env.set_type_by_name("x", dtype)
        assert "x" in env.var_map

    def test_struct_types_default_empty(self):
        env = TypeEnvironment()
        assert env.struct_types == {}

    def test_type_aliases_default_empty(self):
        env = TypeEnvironment()
        assert env.type_aliases == {}

    def test_var_map_default_empty(self):
        env = TypeEnvironment()
        assert env.var_map == {}

    def test_struct_types_set(self):
        env = TypeEnvironment()
        env.struct_types["Foo"] = DataType("struct_Foo", Size.SIZE_64)
        assert "Foo" in env.struct_types

    def test_type_aliases_set(self):
        env = TypeEnvironment()
        env.type_aliases["x"] = "y"
        assert env.type_aliases["x"] == "y"

    def test_multiple_types_same_map(self):
        env = TypeEnvironment()
        env.set_type(Var("x", Size.SIZE_32), DataType("int", Size.SIZE_32))
        env.set_type(Var("y", Size.SIZE_64), DataType("char", Size.SIZE_8))
        assert env.get_type(Var("x", Size.SIZE_32)) is not None
        assert env.get_type(Var("y", Size.SIZE_64)) is not None


# ── TypeAnalyzer ──

class TestTypeAnalyzer:
    def test_construct_default_env(self):
        ta = TypeAnalyzer()
        assert ta.env is not None
        assert isinstance(ta.env, TypeEnvironment)
        assert ta.pending_phis == {}

    def test_construct_custom_env(self):
        env = TypeEnvironment()
        ta = TypeAnalyzer(env=env)
        assert ta.env is env

    def test_pending_phis_default_empty(self):
        ta = TypeAnalyzer()
        assert ta.pending_phis == {}
        assert isinstance(ta.pending_phis, dict)

    def test_analyze(self):
        ta = TypeAnalyzer()
        env = ta.analyze()
        assert env is ta.env

    def test_analyze_empty(self):
        ta = TypeAnalyzer()
        env = ta.analyze()
        assert env.types == {}
        assert env.var_map == {}

    def test_analyze_no_side_effects(self):
        ta = TypeAnalyzer()
        result1 = ta.analyze()
        result2 = ta.analyze()
        assert result1 is result2

    def test_infer_type_from_expr_const(self):
        ta = TypeAnalyzer()
        c = Const(value=42, size=Size.SIZE_32)
        dt = ta.infer_type_from_expr(c)
        assert dt.name == "int"
        assert dt.size == Size.SIZE_32

    def test_infer_type_from_expr_const_auto_size(self):
        ta = TypeAnalyzer()
        c = Const(value=0)
        dt = ta.infer_type_from_expr(c)
        assert dt.name == "unknown"
        assert dt.size == Size.AUTO

    def test_infer_type_from_expr_var(self):
        ta = TypeAnalyzer()
        v = Var("x", Size.SIZE_32)
        dt = ta.infer_type_from_expr(v)
        assert dt.name == "unknown"
        assert dt.size == Size.AUTO

    def test_infer_type_from_expr_var_with_type(self):
        ta = TypeAnalyzer()
        v = Var("x", Size.SIZE_32)
        ta.env.set_type(v, DataType("int", Size.SIZE_32))
        dt = ta.infer_type_from_expr(v)
        assert dt.name == "int"
        assert dt.size == Size.SIZE_32

    def test_infer_type_from_expr_memref(self):
        ta = TypeAnalyzer()
        base = Var("rbp", Size.SIZE_64)
        offset = Const(8, Size.SIZE_64)
        mem = MemRef(base, offset, size=Size.SIZE_32)
        dt = ta.infer_type_from_expr(mem)
        assert "uint" in dt.name or "uint" in dt.name.lower()
        assert dt.size == Size.SIZE_32

    def test_infer_type_from_expr_memref_64(self):
        ta = TypeAnalyzer()
        base = Var("rbp", Size.SIZE_64)
        offset = Const(8, Size.SIZE_64)
        mem = MemRef(base, offset, size=Size.SIZE_64)
        dt = ta.infer_type_from_expr(mem)
        assert "ulong" in dt.name

    def test_infer_type_from_expr_binop(self):
        ta = TypeAnalyzer()
        left = Const(1, Size.SIZE_32)
        right = Const(2, Size.SIZE_32)
        op = BinOp(OpType.ADD, left, right, Size.SIZE_32)
        dt = ta.infer_type_from_expr(op)
        assert dt.size == Size.SIZE_32

    def test_infer_type_from_expr_unop(self):
        ta = TypeAnalyzer()
        operand = Const(5, Size.SIZE_32)
        op = UnOp(OpType.NOT, operand, Size.SIZE_32)
        dt = ta.infer_type_from_expr(op)
        assert dt.size == Size.SIZE_32

    def test_infer_type_from_expr_call(self):
        ta = TypeAnalyzer()
        callee = Var("printf", Size.SIZE_64)
        call = CallExpr(callee, [Const(1, Size.SIZE_32)], Size.SIZE_32)
        dt = ta.infer_type_from_expr(call)
        assert dt.size == Size.AUTO
        assert dt.name == "unknown"

    def test_infer_type_from_expr_cast(self):
        ta = TypeAnalyzer()
        expr = CastOp(Const(42, Size.SIZE_32), Size.SIZE_64, True, False)
        dt = ta.infer_type_from_expr(expr)
        assert dt.size == Size.SIZE_64
        assert dt.signed is True

    def test_infer_type_from_expr_unknown(self):
        ta = TypeAnalyzer()
        class UnknownExpr:
            pass
        dt = ta.infer_type_from_expr(UnknownExpr())
        assert dt.name == "int"

    def test_infer_binop_type_left_size(self):
        ta = TypeAnalyzer()
        left = Const(1, Size.SIZE_32)
        right = Const(2, Size.SIZE_64)
        op = BinOp(OpType.ADD, left, right, Size.SIZE_32)
        dt = ta._infer_binop_type(op)
        assert dt.size == Size.SIZE_32

    def test_infer_call_return_type_default(self):
        ta = TypeAnalyzer()
        callee = Var("printf", Size.SIZE_64)
        call = CallExpr(callee, [Const(1, Size.SIZE_32)], Size.SIZE_32)
        dt = ta._infer_call_return_type(call)
        assert dt.size == Size.AUTO
        assert dt.name == "unknown"

    def test_merge_phi_types_empty_list(self):
        ta = TypeAnalyzer()
        result = ta.merge_phi_types([])
        assert result == ""

    def test_merge_phi_types_single_type(self):
        ta = TypeAnalyzer()
        var = Var("x", Size.SIZE_32)
        ta.env.set_type(var, DataType("int", Size.SIZE_32))
        dt = ta.merge_phi_types([(var, "pred1")])
        assert dt is not None
        assert dt.name == "int"

    def test_merge_phi_types_multiple_same_type(self):
        ta = TypeAnalyzer()
        var1 = Var("x", Size.SIZE_32)
        var2 = Var("y", Size.SIZE_32)
        dtype = DataType("int", Size.SIZE_32)
        ta.env.set_type(var1, dtype)
        ta.env.set_type(var2, dtype)
        result = ta.merge_phi_types([(var1, "pred1"), (var2, "pred2")])
        assert result is not None
        assert result.name == "int"

    def test_merge_phi_types_multiple_different_type(self):
        ta = TypeAnalyzer()
        var1 = Var("x", Size.SIZE_32)
        var2 = Var("y", Size.SIZE_32)
        ta.env.set_type(var1, DataType("int", Size.SIZE_32))
        ta.env.set_type(var2, DataType("char", Size.SIZE_8))
        dt = ta.merge_phi_types([(var1, "pred1"), (var2, "pred2")])
        # Multiple types: largest common supertype = int
        assert dt is not None
        assert dt.name == "int"

    def test_merge_phi_types_no_types_in_env(self):
        ta = TypeAnalyzer()
        var1 = Var("x", Size.SIZE_32)
        var2 = Var("y", Size.SIZE_32)
        dt = ta.merge_phi_types([(var1, "pred1"), (var2, "pred2")])
        assert dt is not None
        assert dt.name == "unknown"

    def test_private_methods_placeholder(self):
        ta = TypeAnalyzer()
        # These are placeholders, should not crash
        ta._infer_from_constants()
        ta._infer_from_memory()
        ta._infer_structs()

    def test_analyze_returns_env(self):
        ta = TypeAnalyzer()
        result = ta.analyze()
        assert result is ta.env

    def test_infer_type_from_expr_binop_right_size(self):
        ta = TypeAnalyzer()
        left = Var("x", Size.AUTO)  # No type info
        right = Const(2, Size.SIZE_64)
        op = BinOp(OpType.ADD, left, right, Size.SIZE_64)
        dt = ta.infer_type_from_expr(op)
        assert dt.size == Size.SIZE_64

    def test_infer_type_from_expr_binop_auto(self):
        ta = TypeAnalyzer()
        var_x = Var("x", Size.AUTO)
        left = Var("x", Size.AUTO)
        right = Const(2, Size.SIZE_32)
        op = BinOp(OpType.ADD, left, right, Size.AUTO)
        ta.env.set_type(var_x, DataType("int", Size.AUTO))
        dt = ta.infer_type_from_expr(op)
        assert dt is not None

    def test_infer_type_from_expr_unop_var_no_env_type(self):
        """UnOp with Var operand and no type info should return unknown with AUTO size."""
        ta = TypeAnalyzer()
        operand = Var("x", Size.AUTO)
        op = UnOp(OpType.NOT, operand, Size.AUTO)
        dt = ta.infer_type_from_expr(op)
        assert dt.name == "unknown"
        assert dt.size == Size.AUTO

    def test_infer_type_from_expr_unop_with_env_type(self):
        """UnOp should use operand's env type when available."""
        ta = TypeAnalyzer()
        operand = Var("x", Size.SIZE_64)
        ta.env.set_type(operand, DataType("ulong", Size.SIZE_64))
        op = UnOp(OpType.NOT, operand, Size.SIZE_64)
        dt = ta.infer_type_from_expr(op)
        assert dt.name == "ulong"
        assert dt.size == Size.SIZE_64

    def test_infer_type_from_expr_unop_memref(self):
        """UnOp with MemRef operand should infer pointer type."""
        ta = TypeAnalyzer()
        base = Var("rsp", Size.SIZE_64)
        offset = Const(0, Size.SIZE_64)
        mem = MemRef(base, offset, size=Size.SIZE_32)
        op = UnOp(OpType.NOT, mem, Size.SIZE_32)
        dt = ta.infer_type_from_expr(op)
        assert "uint" in dt.name
        assert dt.size == Size.SIZE_32

    def test_infer_type_from_expr_unop_signed(self):
        """UnOp should preserve signedness from operand."""
        ta = TypeAnalyzer()
        operand = Var("x", Size.SIZE_32)
        ta.env.set_type(operand, DataType("int", Size.SIZE_32, signed=True))
        op = UnOp(OpType.NOT, operand, Size.SIZE_32)
        dt = ta.infer_type_from_expr(op)
        assert dt.signed is True

    def test_merge_phi_types_char_then_int(self):
        """Merge char + int (different order) should still return int."""
        ta = TypeAnalyzer()
        var1 = Var("x", Size.SIZE_8)
        var2 = Var("y", Size.SIZE_32)
        ta.env.set_type(var1, DataType("char", Size.SIZE_8))
        ta.env.set_type(var2, DataType("int", Size.SIZE_32))
        dt = ta.merge_phi_types([(var1, "pred1"), (var2, "pred2")])
        assert dt is not None
        assert dt.name == "int"

    def test_merge_phi_types_two_unsigned_different_sizes(self):
        """Merge two unsigned types of different sizes — no int present."""
        ta = TypeAnalyzer()
        var1 = Var("x", Size.SIZE_8)
        var2 = Var("y", Size.SIZE_16)
        ta.env.set_type(var1, DataType("uchar", Size.SIZE_8))
        ta.env.set_type(var2, DataType("ushort", Size.SIZE_16))
        dt = ta.merge_phi_types([(var1, "pred1"), (var2, "pred2")])
        assert dt is not None
        assert dt.name == "unknown"  # no supertype found

    def test_infer_call_with_empty_args(self):
        """Call with no arguments should still return unknown type."""
        ta = TypeAnalyzer()
        callee = Var("foo", Size.SIZE_64)
        call = CallExpr(callee, [], Size.SIZE_64)
        dt = ta.infer_type_from_expr(call)
        assert dt.name == "unknown"

    def test_infer_type_var_nullptr_fallback(self):
        """Var with no env type should always fall back to unknown, not crash."""
        ta = TypeAnalyzer()
        v = Var("")
        dt = ta.infer_type_from_expr(v)
        assert dt is not None
        assert dt.name == "unknown"
        assert dt.size == Size.AUTO
