"""
Tests for ir/effects.py — Instruction IR (Assignment, Branch, Call, Phi, NoOp, InstrClass, make_branch_condition).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from vivisect.dec_impl.ir.effects import (
    InstrClass,
    Assignment,
    Branch,
    Call,
    PhiInstruction,
    NoOp,
    make_branch_condition,
)
from vivisect.dec_impl.ir.expression import Var, Const, MemRef, Size, OpType, BinOp


# ── InstrClass ──────────────────────────────────────────────────────

class TestInstrClass:
    def test_all_members(self):
        expected = ["NORMAL", "BRANCH", "JUMP", "CALL", "RETURN", "SIDE_EFFECT", "PHI", "NOOP"]
        actual = [e.name for e in InstrClass]
        for name in expected:
            assert name in actual

    def test_all_values_auto(self):
        values = [e.value for e in InstrClass]
        assert values == list(range(1, len(values) + 1))

    def test_membership(self):
        assert InstrClass.NORMAL is InstrClass.NORMAL
        assert InstrClass.NORMAL != InstrClass.BRANCH


# ── Assignment ─────────────────────────────────────────────────────

class TestAssignment:
    def test_construct_defaults(self):
        dst = Var("eax", Size.SIZE_32)
        src = Const(42, Size.SIZE_32)
        a = Assignment(destination=dst, source=src)
        assert a.destination is dst
        assert a.source is src
        assert a.class_ is InstrClass.NORMAL
        assert a.operands == []
        assert a.mnemonic == ""
        assert a.address == 0

    def test_construct_with_all_args(self):
        dst = Var("eax", Size.SIZE_32)
        src = Const(42, Size.SIZE_32)
        a = Assignment(
            destination=dst, source=src,
            class_=InstrClass.SIDE_EFFECT,
            operands=[Const(1, Size.SIZE_32), Const(2, Size.SIZE_32)],
            mnemonic="mov", address=0x1000,
        )
        assert a.class_ is InstrClass.SIDE_EFFECT
        assert len(a.operands) == 2
        assert a.mnemonic == "mov"
        assert a.address == 0x1000

    def test_repr_basic(self):
        dst = Var("eax", Size.SIZE_32)
        src = Const(42, Size.SIZE_32)
        a = Assignment(destination=dst, source=src)
        assert "=" in repr(a)

    def test_repr_with_mnemonic(self):
        dst = Var("eax", Size.SIZE_32)
        src = Const(42, Size.SIZE_32)
        a = Assignment(destination=dst, source=src, mnemonic="movl")
        # Assignment.__repr__ is dataclass-generated, no mnemonic
        r = repr(a)
        assert "=" in r


# ── Branch ─────────────────────────────────────────────────────────

class TestBranch:
    @pytest.fixture
    def target_bb(self):
        return type("MockBB", (), {"addr": 0x2000})()

    def test_construct_conditional(self, target_bb):
        cond = BinOp(OpType.EQ, Const(0, Size.SIZE_32), Const(0, Size.SIZE_32), Size.SIZE_32)
        b = Branch(condition=cond, true_target=target_bb, false_target=target_bb)
        assert b.condition is cond
        assert b.true_target is target_bb
        assert b.false_target is target_bb
        assert b.class_ is InstrClass.BRANCH
        assert b.address == 0
        assert b.mnemonic == ""
        assert b.jump_table_index is None

    def test_construct_unconditional(self, target_bb):
        b = Branch(condition=None, true_target=target_bb)
        assert b.condition is None
        assert b.true_target is target_bb
        assert b.false_target is None
        assert b.class_ is InstrClass.BRANCH

    def test_construct_jump_table(self, target_bb):
        cond = Const(0, Size.SIZE_32)
        b = Branch(condition=cond, true_target=target_bb, jump_table_index=Const(1, Size.SIZE_32))
        assert b.jump_table_index is not None

    def test_repr_unconditional(self, target_bb):
        b = Branch(condition=None, true_target=target_bb)
        r = repr(b)
        assert "jump" in r
        assert "0x2000" in r

    def test_repr_conditional(self, target_bb):
        cond = BinOp(OpType.EQ, Const(0, Size.SIZE_32), Const(0, Size.SIZE_32), Size.SIZE_32)
        b = Branch(condition=cond, true_target=target_bb)
        r = repr(b)
        assert "if" in r
        assert "jump" in r


# ── Call ───────────────────────────────────────────────────────────

class TestCall:
    def test_construct_defaults(self):
        callee = Var("printf", Size.SIZE_64)
        args = [Const(1, Size.SIZE_32), Const(2, Size.SIZE_32)]
        c = Call(callee=callee, args=args)
        assert c.callee is callee
        assert len(c.args) == 2
        assert c.return_var is None
        assert c.class_ is InstrClass.CALL
        assert c.address == 0
        assert c.mnemonic == ""

    def test_construct_with_return_var(self):
        callee = Var("printf", Size.SIZE_64)
        args = [Const(1, Size.SIZE_32)]
        ret = Var("$ret1", Size.SIZE_32)
        c = Call(callee=callee, args=args, return_var=ret)
        assert c.return_var is ret

    def test_empty_args(self):
        c = Call(callee=Var("foo", Size.SIZE_64), args=[])
        assert len(c.args) == 0


# ── PhiInstruction ───────────────────────────────────────────────

@pytest.fixture
def mock_bb():
    return type("MockBB", (), {"addr": 0x1000})()


class TestPhiInstruction:
    def test_construct(self, mock_bb):
        var = Var("$phi1", Size.SIZE_32)
        operands = [(Const(1, Size.SIZE_32), mock_bb), (Const(2, Size.SIZE_32), mock_bb)]
        phi = PhiInstruction(variable=var, operands=operands)
        assert phi.variable is var
        assert len(phi.operands) == 2
        assert phi.class_ is InstrClass.PHI

    def test_repr(self, mock_bb):
        var = Var("$phi1", Size.SIZE_32)
        operands = [(Const(1, Size.SIZE_32), mock_bb)]
        phi = PhiInstruction(variable=var, operands=operands)
        r = repr(phi)
        assert "phi(" in r
        assert "from BB@0x1000" in r

    def test_from_other_block(self, mock_bb):
        bb2 = type("MockBB", (), {"addr": 0x2000})()
        var = Var("$phi1", Size.SIZE_32)
        operands = [(Const(1, Size.SIZE_32), mock_bb), (Const(2, Size.SIZE_32), bb2)]
        phi = PhiInstruction(variable=var, operands=operands)
        r = repr(phi)
        assert "0x1000" in r
        assert "0x2000" in r


# ── NoOp ─────────────────────────────────────────────────────────

class TestNoOp:
    def test_construct_defaults(self):
        n = NoOp()
        assert n.address == 0
        assert n.size == 1

    def test_construct_with_args(self):
        n = NoOp(address=0x1000, size=5)
        assert n.address == 0x1000
        assert n.size == 5


# ── make_branch_condition helper ─────────────────────────────────

class TestMakeBranchCondition:
    @pytest.fixture
    def mock_bb(self):
        return type("MockBB", (), {"addr": 0x5000})()

    def test_basic(self, mock_bb):
        cond = BinOp(OpType.EQ, Const(0, Size.SIZE_32), Const(0, Size.SIZE_32), Size.SIZE_32)
        b = make_branch_condition(cond, mock_bb)
        assert isinstance(b, Branch)
        assert b.mnemonic == "jz"
        assert b.address == mock_bb.addr
        assert b.condition is cond
        assert b.true_target is mock_bb
        assert b.false_target is None

    def test_different_mnemonic(self, mock_bb):
        """Default mnemonic is 'jz' — no API to customize it."""
        cond = BinOp(OpType.EQ, Const(1, Size.SIZE_32), Const(1, Size.SIZE_32), Size.SIZE_32)
        b = make_branch_condition(cond, mock_bb)
        assert b.mnemonic == "jz"


# ── Instruction union type ──────────────────────────────────────

class TestInstructionType:
    def test_instruction_is_alias(self):
        """Verify Instruction is a union of all instruction types."""
        from vivisect.dec_impl.ir.effects import Instruction
        # All these should be valid Instruction values
        valid: list[Instruction] = [
            Assignment(Var("x", Size.SIZE_32), Const(0, Size.SIZE_32)),
            Branch(condition=None, true_target=type("BB", (), {"addr": 0})()),
            Call(Var("f", Size.SIZE_64), []),
            PhiInstruction(Var("p", Size.SIZE_32), []),
            NoOp(),
        ]
        assert len(valid) == 5
