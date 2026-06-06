"""
Tests for output/formatter.py — Formatter (expressions, statements, block).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from vivisect.dec_impl.output.formatter import Formatter
from vivisect.dec_impl.ir.expression import Const, Var, MemRef, BinOp, OpType, Size, UnOp, PhiNode, CallExpr, CastOp
from vivisect.dec_impl.ir.effects import Assignment, Branch, Call, PhiInstruction, NoOp
from vivisect.dec_impl.ir.block import BasicBlock


@pytest.fixture
def fmt():
    return Formatter()


@pytest.fixture
def fmt4():
    return Formatter(indent_size=4)


@pytest.fixture
def entry_block():
    block = BasicBlock(addr=0x1000, is_entry=True)
    block.successors = [0x2000]
    block.predecessors = []
    block.instructions = []
    return block


# ── Basic formatting ──

class TestFormatterBasic:
    def test_construct(self):
        f = Formatter()
        assert f.indent_level == 0
        assert f._indent_size == 4

    def test_custom_indent(self):
        f = Formatter(indent_size=2)
        assert f._indent_size == 2
        assert f.indent_level == 0

    def test_indent_str(self, fmt4):
        # Level 0
        assert fmt4.indent() == ""
        fmt4.inc()
        # Level 1
        assert fmt4.indent() == "    "
        fmt4.inc()
        # Level 2
        assert fmt4.indent() == "        "
        fmt4.dec()
        # Level 1
        assert fmt4.indent() == "    "
        fmt4.dec()
        # Level 0
        assert fmt4.indent() == ""

    def test_increment(self, fmt):
        fmt.inc()
        assert fmt.indent_level == 1
        fmt.inc(3)
        assert fmt.indent_level == 4

    def test_decrement(self, fmt):
        fmt.inc(3)
        fmt.dec()
        assert fmt.indent_level == 2
        fmt.dec(5)
        assert fmt.indent_level == 0  # clamped

    def test_decrement_below_zero(self, fmt):
        fmt.dec(5)
        assert fmt.indent_level == 0


# ── Expression formatting ──

class TestFmtExpressions:
    def test_fmt_const_int(self, fmt):
        c = Const(value=42)
        assert fmt.fmt_expr(c) == "42"

    def test_fmt_const_hex(self, fmt):
        c = Const(value=42, size=Size.SIZE_32)
        assert fmt.fmt_expr(c) == "0x2a"

    def test_fmt_const_zero(self, fmt):
        c = Const(value=0)
        assert fmt.fmt_expr(c) == "0"

    def test_fmt_const_negative(self, fmt):
        c = Const(value=-1, size=Size.SIZE_32)
        assert fmt.fmt_expr(c) == "0x-1"

    def test_fmt_var_simple(self, fmt):
        v = Var(name="eax")
        assert fmt.fmt_expr(v) == "eax"

    def test_fmt_var_empty_name(self, fmt):
        v = Var(name="")
        assert fmt.fmt_expr(v) == ""

    def test_fmt_memref(self, fmt):
        base = Var("rbp", Size.SIZE_64)
        offset = Const(8, Size.SIZE_64)
        m = MemRef(base, offset, scale=1, size=Size.SIZE_64)
        r = fmt.fmt_expr(m)
        # MemRef format is (base+offset) — offset may be implicit
        assert "rbp" in r

    def test_fmt_memref_with_scale(self, fmt):
        base = Var("rbp", Size.SIZE_64)
        offset = Const(8, Size.SIZE_64)
        m = MemRef(base, offset, scale=4, size=Size.SIZE_32)
        r = fmt.fmt_expr(m)
        assert "rbp" in r
        assert "*4" in r

    def test_fmt_binop_add(self, fmt):
        lhs = Const(1, Size.SIZE_32)
        rhs = Const(2, Size.SIZE_32)
        op = BinOp(OpType.ADD, lhs, rhs, Size.SIZE_32)
        r = fmt.fmt_expr(op)
        assert "+ " in r
        assert "1" in r
        assert "2" in r

    def test_fmt_binop_eq(self, fmt):
        lhs = Var("eax", Size.SIZE_32)
        rhs = Const(0, Size.SIZE_32)
        op = BinOp(OpType.EQ, lhs, rhs, Size.SIZE_32)
        r = fmt.fmt_expr(op)
        assert "eax" in r
        assert "==" in r
        assert "0x0" in r

    def test_fmt_unop_not(self, fmt):
        op_expr = UnOp(OpType.NOT, Const(1, Size.SIZE_32), Size.SIZE_32)
        r = fmt.fmt_expr(op_expr)
        assert "!" in r

    def test_fmt_unop_neg(self, fmt):
        op_expr = UnOp(OpType.SUB, Const(5, Size.SIZE_32), Size.SIZE_32)
        r = fmt.fmt_expr(op_expr)
        assert "-" in r

    def test_fmt_phi(self, fmt):
        bb = type("BB", (), {"addr": 0x1000})()
        phi = PhiNode([(Const(1, Size.SIZE_32), "predecessor")], size=Size.SIZE_32)
        r = fmt.fmt_expr(phi)
        assert "phi(" in r
        assert "predecessor" in r

    def test_fmt_call(self, fmt):
        callee = Var("printf", Size.SIZE_64)
        args = [Const(1, Size.SIZE_32)]
        call = CallExpr(callee, args, Size.SIZE_32)
        r = fmt.fmt_expr(call)
        assert "printf(" in r
        assert "1" in r

    def test_fmt_cast(self, fmt):
        expr = CastOp(Const(42, Size.SIZE_32), Size.SIZE_64, False, False)
        r = fmt.fmt_expr(expr)
        assert "SIZE_64" in r

    def test_fmt_exprs(self, fmt):
        exprs = [Const(1, Size.SIZE_32), Const(2, Size.SIZE_32)]
        result = fmt.fmt_exprs(exprs)
        assert len(result) == 2
        assert "0x1" in result[0]
        assert "0x2" in result[1]


# ── Statement formatting ──

class TestFmtStatements:
    def test_fmt_assignment_simple(self, fmt):
        dst = Var("eax", Size.SIZE_32)
        src = Const(42, Size.SIZE_32)
        stmt = Assignment(dst, src, mnemonic="", address=0)
        r = fmt.fmt_assignment(stmt)
        assert "eax" in r
        assert "0x2a" in r

    def test_fmt_assignment_with_mnemonic(self, fmt):
        dst = Var("eax", Size.SIZE_32)
        src = Const(42, Size.SIZE_32)
        stmt = Assignment(dst, src, mnemonic="movl", address=0)
        r = fmt.fmt_assignment(stmt)
        assert "movl" in r

    def test_fmt_branch_conditional(self, fmt):
        cond = BinOp(OpType.EQ, Const(0, Size.SIZE_32), Const(1, Size.SIZE_32), Size.SIZE_32)
        target = type("BB", (), {"addr": 0x2000})()
        false_target = type("BB", (), {"addr": 0x3000})()
        branch = Branch(cond, target, false_target, mnemonic="jz", address=0)
        r = fmt.fmt_branch(branch)
        assert "if" in r
        assert "goto" in r
        assert "false" in r.lower() or "0x" in r

    def test_fmt_branch_unconditional(self, fmt):
        target = type("BB", (), {"addr": 0x2000})()
        branch = Branch(None, target, mnemonic="jmp", address=0)
        r = fmt.fmt_branch(branch)
        assert "goto" in r
        assert "BB" in r

    def test_fmt_call_stmt_no_return(self, fmt):
        callee = Var("printf", Size.SIZE_64)
        call = Call(callee, [Const(1, Size.SIZE_32)], return_var=None)
        r = fmt.fmt_call_stmt(call)
        assert "printf(" in r
        assert "void" in r.lower()

    def test_fmt_call_stmt_with_return(self, fmt):
        callee = Var("malloc", Size.SIZE_64)
        call = Call(callee, [Const(16, Size.SIZE_64)], return_var=Var("$t0", Size.SIZE_64))
        r = fmt.fmt_call_stmt(call)
        assert "malloc(" in r
        assert "t0" in r

    def test_fmt_phi_instr(self, fmt):
        var = Var("$phi1", Size.SIZE_32)
        operands = [(Const(1, Size.SIZE_32), type("BB", (), {"addr": 0x1000})())]
        phi = PhiInstruction(var, operands)
        r = fmt.fmt_phi_instr(phi)
        # fmt_phi_instr calls variable.__repr__() which returns <Var>
        assert "Var" in r

    def test_fmt_all_noop(self, fmt):
        noop = NoOp(address=0x1000, size=1)
        lines = fmt.fmt_block(type("Block", (), {"instructions": [noop]})())
        assert any("nop" in line.lower() for line in lines)


# ── Block formatting ──

class TestFmtBlock:
    def test_empty_block(self, fmt):
        block = BasicBlock(addr=0x1000, is_entry=True)
        block.successors = []
        block.predecessors = []
        block.instructions = []
        lines = fmt.fmt_block(block)
        assert lines == []

    def test_block_with_assignment(self, fmt):
        block = BasicBlock(addr=0x1000, is_entry=True)
        block.successors = []
        block.predecessors = []
        block.instructions = [Assignment(Var("eax", Size.SIZE_32), Const(42, Size.SIZE_32), mnemonic="movl", address=0)]
        lines = fmt.fmt_block(block)
        assert len(lines) == 1
        assert "eax" in lines[0]

    def test_block_with_branch(self, fmt):
        block = BasicBlock(addr=0x1000, is_entry=True)
        block.successors = [0x2000]
        block.predecessors = []
        target = type("BB", (), {"addr": 0x2000})()
        block.instructions = [Branch(None, target, mnemonic="jmp", address=0)]
        lines = fmt.fmt_block(block)
        assert len(lines) == 1
        assert "goto" in lines[0]

    def test_block_with_multiple_instructions(self, fmt):
        block = BasicBlock(addr=0x1000, is_entry=True)
        block.successors = []
        block.predecessors = []
        block.instructions = [
            Assignment(Var("eax", Size.SIZE_32), Const(1, Size.SIZE_32), mnemonic="movl", address=0),
            Assignment(Var("ebx", Size.SIZE_32), Const(2, Size.SIZE_32), mnemonic="movl", address=0),
        ]
        lines = fmt.fmt_block(block)
        assert len(lines) == 2

    def test_block_with_noop(self, fmt):
        block = BasicBlock(addr=0x1000, is_entry=True)
        block.successors = [0x2000]
        block.predecessors = []
        block.instructions = [NoOp(address=0x1000, size=1)]
        lines = fmt.fmt_block(block)
        assert len(lines) == 1
        assert any("nop" in line.lower() for line in lines)
