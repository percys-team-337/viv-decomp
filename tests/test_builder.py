"""
Tests for dec_impl/ir/builder.py — SymbolikAdaptor, EffectsBuilder, decompile_function.

Tests production logic in builder.py for edge cases and boundary conditions.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from vivisect.dec_impl.ir.expression import Const, Var, Size, BinOp, OpType
from vivisect.dec_impl.ir.builder import SymbolikAdaptor


# Minimal mock objects mimicking Vivisect symbolik effects
class MockConst:
    def __init__(self, value):
        self.value = value
        self._is_const = True

class MockVar:
    def __init__(self, name):
        self.name = name
        self._is_var = True

class MockMemRef:
    def __init__(self, base, offset=None):
        self.base = base
        self.offset = offset
        self._is_mem = True

class MockBinOp:
    def __init__(self, op, left, right=None):
        self.operator = op
        self.left = left
        self.right = right
        if not hasattr(self, '_is_op'):
            self._is_op = True

class MockCall:
    def __init__(self, callee, args=None):
        self.callee = callee
        self.args = args or []
        self._is_call = True


class TestSymbolikAdaptorConvert:
    """Test SymbolikAdaptor.convert() production logic for all effect types."""

    def test_const_effect(self):
        mock = MockConst(42)
        result = SymbolikAdaptor.convert(mock)
        assert isinstance(result, Const)
        assert result.value == 42

    def test_const_effect_with_target_size(self):
        mock = MockConst(42)
        result = SymbolikAdaptor.convert(mock, Size.SIZE_64)
        assert result.size == Size.SIZE_64

    def test_var_effect(self):
        mock = MockVar("eax")
        result = SymbolikAdaptor.convert(mock)
        assert isinstance(result, Var)
        assert result.name == "eax"

    def test_var_effect_with_target_size(self):
        mock = MockVar("rbx")
        result = SymbolikAdaptor.convert(mock, Size.SIZE_64)
        assert result.size == Size.SIZE_64

    def test_unknown_effect_falls_through_to_zero(self):
        class WildEffect:
            __slots__ = []
        result = SymbolikAdaptor.convert(WildEffect())
        assert isinstance(result, Const)
        assert result.value == 0

    def test_unknown_effect_with_target_size(self):
        class WildEffect:
            __slots__ = []
        result = SymbolikAdaptor.convert(WildEffect(), Size.SIZE_32)
        assert result.size == Size.SIZE_32

    def test_mem_effect_base_only(self):
        mock_base = MockVar("rsp")
        mock = MockMemRef(mock_base)
        result = SymbolikAdaptor.convert(mock)
        # MemRef: has 'base' attr → goes to MemRef path
        assert hasattr(result, 'base')

    def test_mem_effect_with_offset(self):
        mock_base = MockVar("rbp")
        mock_offset = MockConst(16)
        mock = MockMemRef(mock_base, offset=mock_offset)
        result = SymbolikAdaptor.convert(mock)
        assert hasattr(result, 'offset')

    def test_unary_op(self):
        inner = MockVar('x')
        class MockUnop:
            operator = 'o_not'
            left = inner
            # No 'right' attribute – signals unary operation
        mock = MockUnop()
        result = SymbolikAdaptor.convert(mock)
        assert hasattr(result, 'operand')  # UnOp path

    def test_binary_op(self):
        left = MockConst(1)
        right = MockConst(2)
        mock = MockBinOp('o_add', left, right)
        result = SymbolikAdaptor.convert(mock)
        assert hasattr(result, 'left')
        assert hasattr(result, 'right')

    def test_call_effect(self):
        callee = MockVar("printf")
        arg1 = MockConst(1)
        mock = MockCall(callee, [arg1])
        result = SymbolikAdaptor.convert(mock)
        assert hasattr(result, 'callee')
        assert hasattr(result, 'args')

    def test_nested_binop_convert(self):
        """Nested ops should recursively convert."""
        inner = MockConst(1)
        middle = MockBinOp('o_add', inner, MockConst(2))
        outer = MockBinOp('o_mul', middle, MockConst(3))
        result = SymbolikAdaptor.convert(outer)
        # At top level, should have left + right
        assert hasattr(result, 'left')

    def test_mem_effect_with_scale(self):
        mock_base = MockVar('rbx')
        class MockMemScale:
            base = mock_base
            scale = 4
        mock = MockMemScale()
        result = SymbolikAdaptor.convert(mock)
        assert result.scale == 4

    def test_convert_with_explicit_target_size(self):
        mock = MockConst(0xFF)
        result = SymbolikAdaptor.convert(mock, Size.SIZE_16)
        assert result.size == Size.SIZE_16
        assert result.value == 0xFF


class TestSymbolikAdaptorMapOp:
    """Test _map_op static method."""

    def test_all_standard_ops_map(self):
        op_map = [
            ('o_add', OpType.ADD),
            ('o_sub', OpType.SUB),
            ('o_mul', OpType.MUL),
            ('o_div', OpType.DIV),
            ('o_mod', OpType.MOD),
            ('o_and', OpType.AND),
            ('o_or', OpType.OR),
            ('o_xor', OpType.XOR),
            ('o_not', OpType.NOT),
            ('o_shl', OpType.SHL),
            ('o_shr', OpType.SHR),
            ('o_sar', OpType.SAR),
            ('o_eq', OpType.EQ),
            ('o_ne', OpType.NE),
            ('o_lt', OpType.LT),
            ('o_gt', OpType.GT),
            ('o_le', OpType.LE),
            ('o_ge', OpType.GE),
            ('o_call', OpType.CALL),
            ('o_load', OpType.LOAD),
            ('o_store', OpType.STORE),
        ]
        for sym_op, expected in op_map:
            result = SymbolikAdaptor._map_op(sym_op)
            assert result == expected, f"Failed for {sym_op}: got {result}, expected {expected}"

    def test_unknown_op_returns_memory(self):
        result = SymbolikAdaptor._map_op('o_unknown_xyz')
        assert result == OpType.MEMORY

    def test_map_op_preserves_value_ordering(self):
        """OpType values should be auto()-generated."""
        assert OpType.ADD.value < OpType.SUB.value


class TestSymbolikAdaptorConvertEdgeCases:
    """Edge cases for convert()."""

    def test_convert_none_like_value(self):
        class Fake:
            value = None
        result = SymbolikAdaptor.convert(Fake())
        assert result.value is None

    def test_convert_empty_string_var(self):
        class Fake:
            name = ""
        result = SymbolikAdaptor.convert(Fake())
        assert isinstance(result, Var)
        assert result.name == ""

    def test_convert_negative_value(self):
        class Fake:
            value = -256
        result = SymbolikAdaptor.convert(Fake())
        assert result.value == -256

    def test_convert_zero_value(self):
        class Fake:
            value = 0
        result = SymbolikAdaptor.convert(Fake())
        assert result.value == 0

    def test_convert_large_value(self):
        class Fake:
            value = (1 << 64) - 1
        result = SymbolikAdaptor.convert(Fake(), Size.SIZE_64)
        assert result.value == (1 << 64) - 1
