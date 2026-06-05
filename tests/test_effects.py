"""
Tests for dec_impl/ir/effects.py — Instruction types and make_branch_condition.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from vivisect.dec_impl.ir.effects import (
    Assignment, Branch, Call, PhiInstruction, NoOp,
    InstrClass, make_branch_condition,
)
from vivisect.dec_impl.ir.expression import Var, Const, MemRef, Size, OpType, BinOp
from vivisect.dec_impl.ir.block import BasicBlock


class TestAssignment:
    def test_default_instr_class(self):
        a = Assignment(destination=Var("x", Size.SIZE_32), source=Const(1, Size.SIZE_32))
        assert a.class_ == InstrClass.NORMAL

    def test_custom_instr_class(self):
        a = Assignment(destination=Var("x", Size.SIZE_32), source=Const(1, Size.SIZE_32),
                       class_=InstrClass.SIDE_EFFECT)
        assert a.class_ == InstrClass.SIDE_EFFECT

    def test_with_mnemonic(self):
        a = Assignment(destination=Var("x", Size.SIZE_32), source=Const(1, Size.SIZE_32),
                       mnemonic="mov", address=0x1000)
        assert a.mnemonic == "mov"
        assert a.address == 0x1000

    def test_repr(self):
        a = Assignment(destination=Var("eax", Size.SIZE_32), source=Const(42, Size.SIZE_32))
        assert "eax" in a.__repr__()
        assert "=" in a.__repr__()

    def test_mem_destination(self):
        base = Var("rbp", Size.SIZE_64)
        offset = Const(8, Size.SIZE_64)
        mem = MemRef(base, offset, size=Size.SIZE_64)
        a = Assignment(destination=mem, source=Const(1, Size.SIZE_64))
        assert a.destination == mem

    def test_empty_destination_name(self):
        a = Assignment(destination=Var(""), source=Const(0, Size.SIZE_32))
        assert a.destination.name == ""

    def test_operands_default_empty(self):
        a = Assignment(destination=Var("x", Size.SIZE_32), source=Const(1, Size.SIZE_32))
        assert a.operands == []


class TestBranch:
    def test_unconditional(self):
        target = BasicBlock(0x2000)
        b = Branch(condition=None, true_target=target)
        assert b.condition is None
        assert b.false_target is None
        assert "jump 0x" in b.__repr__()

    def test_conditional(self):
        target = BasicBlock(0x2000)
        false_target = BasicBlock(0x3000)
        cond = BinOp(OpType.EQ, Const(1, Size.SIZE_32), Const(1, Size.SIZE_32), Size.SIZE_32)
        b = Branch(condition=cond, true_target=target, false_target=false_target)
        assert b.condition is not None
        assert "0x2000" in b.__repr__()

    def test_with_jump_table_index(self):
        target = BasicBlock(0x2000)
        b = Branch(condition=Const(1, Size.SIZE_32), true_target=target,
                   jump_table_index=Const(0, Size.SIZE_32))
        assert b.jump_table_index is not None

    def test_unconditional_false_target_none(self):
        target = BasicBlock(0x2000)
        b = Branch(condition=None, true_target=target, false_target=None)
        assert b.class_ == InstrClass.BRANCH

    def test_address_default(self):
        target = BasicBlock(0x2000)
        b = Branch(condition=Const(1, Size.SIZE_32), true_target=target)
        assert b.address == 0

    def test_mnemonic_stored(self):
        target = BasicBlock(0x2000)
        b = Branch(condition=Const(1, Size.SIZE_32), true_target=target, mnemonic="jnz")
        assert b.mnemonic == "jnz"


class TestCall:
    def test_minimal(self):
        callee = Var("printf", Size.SIZE_32)
        c = Call(callee=callee, args=[], return_var=None)
        assert c.callee == callee
        assert c.args == []
        assert c.return_var is None

    def test_with_return_var(self):
        callee = Var("malloc", Size.SIZE_32)
        ret = Var("$t0", Size.SIZE_64)
        c = Call(callee=callee, args=[Const(16, Size.SIZE_64)], return_var=ret)
        assert c.return_var == ret
        assert len(c.args) == 1

    def test_default_class(self):
        c = Call(callee=Var("foo", Size.SIZE_32), args=[])
        assert c.class_ == InstrClass.CALL

    def test_default_address_mnemonic(self):
        c = Call(callee=Var("foo", Size.SIZE_32), args=[])
        assert c.address == 0
        assert c.mnemonic == ""


class TestPhiInstruction:
    def test_minimal(self):
        var = Var("x", Size.SIZE_32)
        phi = PhiInstruction(variable=var, operands=[])
        assert phi.variable == var
        assert phi.operands == []
        assert phi.class_ == InstrClass.PHI

    def test_with_operands(self):
        var = Var("x", Size.SIZE_32)
        block1 = BasicBlock(0x1000)
        block2 = BasicBlock(0x2000)
        val1 = Var("x.s0", Size.SIZE_32)
        val2 = Var("x.s1", Size.SIZE_32)
        phi = PhiInstruction(variable=var, operands=[(val1, block1), (val2, block2)])
        assert len(phi.operands) == 2

    def test_repr(self):
        var = Var("x", Size.SIZE_32)
        block1 = BasicBlock(0x1000)
        phi = PhiInstruction(variable=var, operands=[(Var("a", Size.SIZE_32), block1)])
        assert "phi(" in phi.__repr__()


class TestNoOp:
    def test_defaults(self):
        n = NoOp()
        assert n.address == 0
        assert n.size == 1

    def test_custom(self):
        n = NoOp(address=0x1000, size=5)
        assert n.address == 0x1000
        assert n.size == 5


class TestInstrClass:
    def test_all_members(self):
        members = [e.name for e in InstrClass]
        expected = ["NORMAL", "BRANCH", "JUMP", "CALL", "RETURN", "SIDE_EFFECT", "PHI", "NOOP"]
        for name in expected:
            assert name in members

    def test_values_are_auto(self):
        values = [e.value for e in InstrClass]
        assert values == [1, 2, 3, 4, 5, 6, 7, 8]


class TestMakeBranchCondition:
    def test_basic(self):
        cond = BinOp(OpType.EQ, Const(1, Size.SIZE_32), Const(1, Size.SIZE_32), Size.SIZE_32)
        target = BasicBlock(0x2000)
        branch = make_branch_condition(cond, target)
        assert branch.condition is cond
        assert branch.true_target is target
        assert branch.mnemonic == "jz"
        assert branch.address == 0x2000

    def test_address_from_target(self):
        cond = Const(1, Size.SIZE_32)
        class FakeTarget:
            addr = 0x9ABC
        branch = make_branch_condition(cond, FakeTarget())
        assert branch.address == 0x9ABC

    def test_true_target_set(self):
        cond = Const(1, Size.SIZE_32)
        target = BasicBlock(0xDEAD)
        branch = make_branch_condition(cond, target)
        assert branch.true_target is target
