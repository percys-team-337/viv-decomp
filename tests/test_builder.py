"""
Tests for dec_impl/ir/builder.py -- SymbolikAdaptor, EffectsBuilder, decompile_function.

Tests production logic in builder.py for edge cases and boundary conditions.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from types import new_class
from dec_engine.dec_impl.ir.expression import (
    Const, Var, Size, BinOp, UnOp, MemRef, OpType, CallExpr
)
from dec_engine.dec_impl.ir.builder import SymbolikAdaptor


# ========================= Mock objects ================
# These dynamically create classes with the right __name__
# so SymbolikAdaptor's name-dispatch logic works correctly.

def _make_mock_class(name):
    """Create a class with a dynamic name."""
    return type(name, (), {})


MockConstType = _make_mock_class('Const')
MockVarType = _make_mock_class('Var')
MockMemType = _make_mock_class('Mem')
MockCallType = _make_mock_class('Call')


def make_mock_const(value, width=8):
    cls = MockConst.__class__.__bases__[0] if False else None
    return MockConst(value, width)


# Actually, let's just define classes explicitly
class MockConst:
    """A mock Const symbol. SymbolikAdaptor checks __class__.__name__ == 'Const'"""
    pass
MockConst.__name__ = 'Const'
MockConst.__module__ = 'vivisect.symboliks.expression'


class MockVar:
    """A mock Var symbol."""
    pass
MockVar.__name__ = 'Var'
MockVar.__module__ = 'vivisect.symboliks.expression'


class MockMem:
    """A mock Mem symbolik type: __name__='Mem', .kids=[base, offset?, scale?]"""
    pass
MockMem.__name__ = 'Mem'
MockMem.__module__ = 'vivisect.symboliks.expression'


class MockCall:
    """A mock Call symbolik type."""
    pass
MockCall.__name__ = 'Call'
MockCall.__module__ = 'vivisect.symboliks.expression'


def mock_const(value, width=8):
    obj = type('Const', (), {'value': value, 'width': width})()
    return obj


def mock_var(name, width=8):
    obj = type('Var', (), {'name': name, 'width': width})()
    return obj


def mock_mem(base, offset=None, sz=8):
    kids = [base] if offset is None else [base, offset]
    obj = type('Mem', (), {'kids': kids, 'width': sz})()
    return obj


def mock_binop(op_name, left, right=None, width=8):
    """Create a binary-op mock: __name__='o_<op>', .kids=[left, right?], .width"""
    cn = 'o_' + op_name
    obj = type(cn, (), {
        'kids': [left, right] if right is not None else [left],
        'width': width
    })()
    return obj


def mock_unop(op_name, operand, width=8):
    """Create a unary-op mock."""
    cn = 'o_' + op_name if not op_name else 'cnot'
    obj = type(cn, (), {
        'kids': [operand],
        'width': width
    })()
    return obj


def mock_call(funcsym, args=None, width=8):
    """Create a Call mock."""
    obj = type('Call', (), {
        'funcsym': funcsym,
        'argsyms': args or [],
        'width': width
    })()
    return obj


__all__ = ['mock_const', 'mock_var', 'mock_mem', 'mock_binop', 'mock_unop', 'mock_call']


# ================= Test suite =======================

class TestSymbolikAdaptorConvert:
    """Test SymbolikAdaptor.convert() production logic for all effect types."""

    def test_const_effect(self):
        mock = mock_const(42)
        result = SymbolikAdaptor.convert(mock)
        assert isinstance(result, Const)
        assert result.value == 42

    def test_const_effect_with_target_size(self):
        # hint_sz is used for Nested conversions, not top-level symbol width
        # Top-level uses getattr(sym, 'width', 8) which returns mock's width=8 (8 bytes = 64 bits)
        mock = mock_const(42)
        result = SymbolikAdaptor.convert(mock, 64)  # 64 is ignored for top-level
        assert result.size == Size.SIZE_64  # width=8 bytes → 64 bits

    def test_var_effect(self):
        mock = mock_var("eax")
        result = SymbolikAdaptor.convert(mock)
        assert isinstance(result, Var)
        assert result.name == "eax"

    def test_var_effect_with_target_size(self):
        mock = mock_var("rbx")
        # hint_sz is for nested ops. Top-level uses mock's .width=8 (8 bytes = 64 bits)
        result = SymbolikAdaptor.convert(mock, 64)
        assert result.size == Size.SIZE_64

    def test_unknown_effect_falls_through_to_zero(self):
        class WildEffect:
            pass
        result = SymbolikAdaptor.convert(WildEffect())
        assert isinstance(result, Const)
        assert result.value == 0

    def test_unknown_effect_with_target_size(self):
        class WildEffect:
            pass
        # WildEffect has no .name attribute, falls through to zero Const
        # hint_sz not used for top-level fallback
        result = SymbolikAdaptor.convert(WildEffect(), 32)
        assert isinstance(result, Const)
        assert result.value == 0

    def test_mem_effect_base_only(self):
        mock_base = mock_var("rsp")
        mock = mock_mem(mock_base)
        result = SymbolikAdaptor.convert(mock)
        assert isinstance(result, MemRef)
        assert result.base is not None

    def test_mem_effect_with_offset(self):
        mock_base = mock_var("rbp")
        mock_offset = mock_const(16)
        mock = mock_mem(mock_base, offset=mock_offset)
        result = SymbolikAdaptor.convert(mock)
        assert isinstance(result, MemRef)
        assert result.offset is not None

    def test_unary_op(self):
        inner = mock_var('x')
        obj = mock_unop('not', inner)
        result = SymbolikAdaptor.convert(obj)
        from dec_engine.dec_impl.ir.expression import UnOp
        assert isinstance(result, UnOp)

    def test_binary_op(self):
        left = mock_const(1)
        right = mock_const(2)
        obj = mock_binop('add', left, right)
        result = SymbolikAdaptor.convert(obj)
        assert isinstance(result, BinOp)
        assert hasattr(result, 'left')
        assert hasattr(result, 'right')

    def test_call_effect(self):
        callee = mock_var("printf")
        arg1 = mock_const(1)
        mock = mock_call(callee, [arg1])
        result = SymbolikAdaptor.convert(mock)
        assert isinstance(result, CallExpr)
        assert result.callee is not None
        assert len(result.args) == 1

    def test_nested_binop_convert(self):
        """Nested ops should recursively convert."""
        inner = mock_const(1)
        middle = mock_binop('add', inner, mock_const(2))
        outer = mock_binop('mul', middle, mock_const(3))
        result = SymbolikAdaptor.convert(outer)
        assert isinstance(result, BinOp)
        assert hasattr(result, 'left')
        assert hasattr(result, 'right')

    def test_mem_effect_with_scale(self):
        mock_base = mock_var('rbx')
        mock = mock_mem(mock_base, offset=mock_const(0), sz=1)
        # Scale needs third kid element
        obj = type('Mem', (), {
            'kids': [mock_base, mock_const(0), mock_const(4)],
            'width': 64
        })()
        result = SymbolikAdaptor.convert(obj)
        assert isinstance(result, MemRef)
        assert result.scale == 4

    def test_convert_with_explicit_target_size(self):
        # For top-level conversions with .width, hint_sz is ignored
        mock = mock_const(0xFF)
        result = SymbolikAdaptor.convert(mock, 16)
        assert result.size == Size.SIZE_64  # mock's .width=8 bytes = 64 bits
        assert result.value == 0xFF


class TestSymbolikAdaptorMapOp:
    """Test _op_type static method."""

    def test_all_standard_ops_map(self):
        op_map = {
            'o_add': OpType.ADD,
            'o_sub': OpType.SUB,
            'o_mul': OpType.MUL,
            'o_div': OpType.DIV,
            'o_mod': OpType.MOD,
            'o_and': OpType.AND,
            'o_or': OpType.OR,
            'o_xor': OpType.XOR,
            'o_not': OpType.NOT,
            'o_lshift': OpType.SHL,
            'o_rshift': OpType.SHR,
            'o_eq': OpType.EQ,
            'o_ne': OpType.NE,
            'o_lt': OpType.LT,
            'o_gt': OpType.GT,
            'o_le': OpType.LE,
            'o_ge': OpType.GE,
            'o_pow': OpType.PTR_ADD,
            'o_sextend': OpType.SIGN_EXTEND,
        }
        for sym_op, expected in op_map.items():
            result = SymbolikAdaptor._op_type(sym_op)
            assert result == expected, f"Failed for {sym_op}: got {result}, expected {expected}"

    def test_unknown_op_returns_memory(self):
        result = SymbolikAdaptor._op_type('o_unknown_xyz')
        assert result == OpType.MEMORY

    def test_map_op_preserves_value_ordering(self):
        """OpType values should be auto()-generated."""
        assert OpType.ADD.value < OpType.SUB.value


class TestSymbolikAdaptorConvertEdgeCases:
    """Edge cases for convert()."""

    def test_convert_none_input(self):
        result = SymbolikAdaptor.convert(None)
        assert isinstance(result, Const)
        assert result.value == 0

    def test_convert_empty_string_var(self):
        obj = type('Var', (), {'name': '', 'width': 8})()
        result = SymbolikAdaptor.convert(obj)
        assert isinstance(result, Var)
        assert result.name == ""

    def test_convert_negative_value(self):
        obj = type('Const', (), {'value': -256, 'width': 8})()
        result = SymbolikAdaptor.convert(obj)
        assert result.value == -256

    def test_convert_zero_value(self):
        obj = type('Const', (), {'value': 0, 'width': 8})()
        result = SymbolikAdaptor.convert(obj)
        assert result.value == 0

    def test_convert_large_value(self):
        obj = type('Const', (), {'value': (1 << 64) - 1, 'width': 64})()
        result = SymbolikAdaptor.convert(obj, 64)
        assert result.value == (1 << 64) - 1
