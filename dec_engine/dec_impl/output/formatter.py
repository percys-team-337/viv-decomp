"""
Expression and statement formatter for C-like output.

Maps IR expression nodes to C-like syntax and manages control flow formatting.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List
from dec_engine.dec_impl.ir.expression import (
    Expression,
    Const,
    Var,
    MemRef,
    BinOp,
    UnOp,
    PhiNode,
    CallExpr,
    CastOp,
    OpType,
    Size,
)
from dec_engine.dec_impl.ir.effects import (
    Assignment,
    Branch,
    Call,
    PhiInstruction,
    NoOp,
)
from dec_engine.dec_impl.ir.block import BasicBlock

if TYPE_CHECKING:
    from dec_engine.dec_impl.type_inference.analyze import DataType


class Formatter:
    """Formats IR expressions and instructions into C-like pseudocode."""

    def __init__(self, indent_size: int = 4):
        self._indent_level = 0
        self._indent_size = indent_size
        self._types: dict[str, DataType] = {}  # Placeholder for type mapping

    @property
    def indent_level(self) -> int:
        return self._indent_level

    @indent_level.setter
    def indent_level(self, val: int):
        self._indent_level = val

    def indent(self) -> str:
        return " " * (self._indent_size * self._indent_level)

    def inc(self, delta: int = 1):
        self._indent_level += delta

    def dec(self, delta: int = 1):
        self._indent_level = max(0, self._indent_level - delta)

    # ---- Expression formatting ----

    def fmt_expr(self, expr: Expression) -> str:
        """Format a single expression node to C-like syntax."""
        if isinstance(expr, Const):
            return self._fmt_const(expr)
        elif isinstance(expr, Var):
            return self._fmt_var(expr)
        elif isinstance(expr, MemRef):
            return self._fmt_memref(expr)
        elif isinstance(expr, BinOp):
            return self._fmt_binop(expr)
        elif isinstance(expr, UnOp):
            return self._fmt_unop(expr)
        elif isinstance(expr, PhiNode):
            return self._fmt_phi(expr)
        elif isinstance(expr, CallExpr):
            return self._fmt_call(expr)
        elif isinstance(expr, CastOp):
            return self._fmt_cast(expr)
        return str(expr)

    def fmt_exprs(self, exprs: List[Expression]) -> List[str]:
        """Format a list of expressions to C-like strings."""
        return [self.fmt_expr(e) for e in exprs]

    def _fmt_const(self, expr: Const) -> str:
        """Format a constant literal."""
        val = expr.value
        if expr.size != Size.AUTO:
            return f"0x{val:x}"
        return str(val)

    def _fmt_var(self, expr: Var) -> str:
        """Format a variable reference."""
        return expr.name

    def _fmt_memref(self, expr: MemRef) -> str:
        """Format a memory reference: *(type*)addr."""
        addr_str = self._fmt_memref_base(expr)
        scale_str = f"*{expr.scale}" if expr.scale != 1 else ""
        return f"({addr_str}{scale_str})"

    def _fmt_memref_base(self, expr: MemRef) -> str:
        """Format the base address of a MemRef, adding *(type*) prefix."""
        addr_str = self.fmt_expr(expr.base)
        size_name = self._size_to_type_name(expr.size) or self._size_to_type_name(Size.SIZE_64)
        return f"({size_name}*){addr_str}"

    def _size_to_type_name(self, sz) -> str:
        """Convert Size to C type name."""
        if sz == Size.SIZE_8:
            return "uint8_t"
        elif sz == Size.SIZE_16:
            return "uint16_t"
        elif sz == Size.SIZE_32:
            return "uint32_t"
        elif sz == Size.SIZE_64:
            return "uint64_t"
        return ""

    def _fmt_binop(self, expr: BinOp) -> str:
        """Format a binary operation: a <op> b with XOR simplification."""
        lhs_raw = self.fmt_expr(expr.left)
        rhs_raw = self.fmt_expr(expr.right)
        
        # XOR simplification: (X ^ X) → 0
        if expr.op == OpType.XOR and lhs_raw == rhs_raw:
            return "0"
        
        # Simplify XOR with 0: (X ^ 0) → X
        if expr.op == OpType.XOR:
            if rhs_raw == "0":
                return lhs_raw
            # Check for Const XOR with 0
            if isinstance(expr.right, Const) and expr.right.value == 0:
                return lhs_raw

        # Constant folding: binop(const, const) → value
        if isinstance(expr.left, Const) and isinstance(expr.right, Const):
            lhs_val = expr.left.value
            rhs_val = expr.right.value
            if isinstance(lhs_val, int) and isinstance(rhs_val, int):
                try:
                    folded = {
                        OpType.ADD: lhs_val + rhs_val,
                        OpType.SUB: lhs_val - rhs_val,
                        OpType.MUL: lhs_val * rhs_val,
                        OpType.DIV: lhs_val // rhs_val,
                        OpType.AND: lhs_val & rhs_val,
                        OpType.OR: lhs_val | rhs_val,
                        OpType.XOR: lhs_val ^ rhs_val,
                        OpType.SHL: lhs_val << rhs_val,
                        OpType.SHR: lhs_val >> rhs_val,
                    }.get(expr.op)
                    if folded is not None:
                        # Use hex for 64-bit values, decimal for small
                        return hex(folded) if folded > 0xfff else str(folded)
                except (ZeroDivisionError, OverflowError, ValueError):
                    pass

        op_str = self._lookup_op(expr.op, " ")
        return f"({lhs_raw} {op_str} {rhs_raw})"

    def _fmt_unop(self, expr: UnOp) -> str:
        """Format a unary operation: <op> a or a <op>."""
        operand = self.fmt_expr(expr.operand)
        op_str = self._lookup_op(expr.op, "")
        if op_str in ("!", "~", "-"):
            return f"{op_str}{operand}"
        return f"{operand}{op_str}"

    def _fmt_phi(self, expr: PhiNode) -> str:
        """Format a phi node."""
        parts = []
        for var_expr, pred_label in expr.operands:
            parts.append(f"({var_expr}, {pred_label})")
        return f"phi({', '.join(parts)})"

    def _fmt_call(self, expr: CallExpr) -> str:
        """Format a function call."""
        callee_str = self.fmt_expr(expr.callee)
        args = ", ".join(self.fmt_expr(a) for a in expr.args)
        return f"{callee_str}({args})"

    def _fmt_cast(self, expr: CastOp) -> str:
        """Format a cast: cast<to>(from)."""
        operand = self.fmt_expr(expr.from_expr)
        return f"({expr.to_size.name}){operand}"

    # ---- Instruction formatting ----

    def fmt_assignment(self, stmt: Assignment) -> str:
        """Format an assignment: dst = src"""
        lhs = self.fmt_expr(stmt.destination)
        rhs = self.fmt_expr(stmt.source)
        return f"{lhs} = {rhs} {stmt.mnemonic}" if stmt.mnemonic else f"{lhs} = {rhs}"

    def fmt_branch(self, stmt: Branch) -> str:
        """Format a conditional branch."""
        cond = self.fmt_expr(stmt.condition) if stmt.condition else "true"
        target = self.fmt_expr(stmt.true_target)
        if stmt.false_target:
            return f"if ({cond}) {{ goto {target}; }} else {{ goto {self.fmt_expr(stmt.false_target)}; }}"
        return f"if ({cond}) goto {target}"

    def fmt_call_stmt(self, stmt: Call) -> str:
        """Format a function call statement."""
        callee_str = self.fmt_expr(stmt.callee)
        args = ", ".join(self.fmt_expr(a) for a in stmt.args)
        dest = "void"
        if stmt.return_var is not None:
            dest = self.fmt_expr(stmt.return_var)
        return f"{dest} = {callee_str}({args})"

    def fmt_phi_instr(self, stmt: PhiInstruction) -> str:
        """Format a phi instruction."""
        return stmt.variable.__repr__()

    # Helper to look up operator strings
    @staticmethod
    def _lookup_op(op: OpType, sep: str = " ") -> str:
        """Lookup operator string in C syntax."""
        op_str = {
            OpType.ADD: f"+{sep}",
            OpType.SUB: f"-{sep}",
            OpType.MUL: f"*{sep}",
            OpType.DIV: f"/{sep}",
            OpType.MOD: f"%{sep}",
            OpType.AND: f"&{sep}",
            OpType.OR: f"|{sep}",
            OpType.XOR: f"^{sep}",
            OpType.NOT: "!",
            OpType.SHL: f"<<<{sep}",
            OpType.SHR: f">>>{sep}",
            OpType.SAR: f">>>{sep}",
            OpType.EQ: f"{sep}=={sep}",
            OpType.NE: f"{sep}!={sep}",
            OpType.LT: f"{sep}<{sep}",
            OpType.GT: f"{sep}>{sep}",
            OpType.LE: f"{sep}<{sep}",
            OpType.GE: f"{sep}>{sep}",
            OpType.LOAD: f"[{sep}",
            OpType.STORE: f"]{sep}",
            OpType.PHI: "phi-",
            OpType.CALL: "call-",
            OpType.CAST: "cast-",
        }
        return op_str.get(op, str(op))

    def fmt_block(self, block: BasicBlock) -> List[str]:
        """Format an entire basic block into lines of C-like pseudocode."""
        lines = []
        for instr in block.instructions:
            if isinstance(instr, Assignment):
                lines.append(self.fmt_assignment(instr))
            elif isinstance(instr, Branch):
                lines.append(self.fmt_branch(instr))
            elif isinstance(instr, Call):
                lines.append(self.fmt_call_stmt(instr))
            elif isinstance(instr, PhiInstruction):
                lines.append(self.fmt_phi_instr(instr))
            elif isinstance(instr, NoOp):
                lines.append("nop;")
            else:
                lines.append(str(instr))
        return lines
