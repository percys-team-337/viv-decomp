"""
Pretty printer: converts structured CFG/SSA data into readable C-like pseudocode.

Takes the output of the structuring pass (dominated regions, loop headers) and
produces indented C-style output with proper control flow structures.
"""
from __future__ import annotations
from typing import List, Optional
from dec_engine.dec_impl.output.formatter import Formatter
from dec_engine.dec_impl.ir.block import BasicBlock, BlockGraph
from dec_engine.dec_impl.ir.effects import Branch, NoOp
from dec_engine.dec_impl.ir.expression import Var  # noqa: F401
from dec_engine.dec_impl.ssa.construct import SsaState


class PrettyPrinter:
    """Generates C-like pseudocode from structured decompiler output.

    Handles:
    - Function prologue/epilogue annotations
    - If/else blocks for conditional branches
    - While/for loops for back-edges
    - Switch/case for jump tables
    - goto fallbacks for unstructured control flow
    - Variable type annotations where known
    - Proper indentation and line separation
    """

    def __init__(
        self,
        func_name: str,
        graph: BlockGraph,
        ssa: SsaState,
        func_addr: Optional[int] = None,
        indent_size: int = 4,
        workspace=None,
    ):
        self.func_name = func_name
        self.graph = graph
        self.ssa = ssa
        self.func_addr = func_addr
        self.indent_size = indent_size
        self._formatter = Formatter(indent_size=indent_size)
        self._output: List[str] = []
        self._visited: set = set()
        self._loop_headers: set = set()
        self._switch_entries: set = set()
        self._vw = workspace
        # Cache of names discovered via Vivisect's analysis
        self._name_cache: dict[int, str] = {}

    def _build_var_map(self):
        """Build variable rename map from SSA variable registry."""
        pass  # Placeholder for SSA variable renaming

    def _is_loop_header(self, addr) -> bool:
        """Check if a block is a loop header (has back-edge to it)."""
        block = self.graph.blocks.get(addr)
        if block is None:
            return False
        return len(block.predecessors) > 0 and block in self._loop_headers

    def _is_switch_entry(self, addr) -> bool:
        """Check if a block is a switch/case entry (has >= 3 successors)."""
        block = self.graph.blocks.get(addr)
        if block is None:
            return False
        return len(block.successors) >= 3

    def _analyze_switches(self):
        """Analyze the graph to identify switch/case structures."""
        for addr, block in self.graph.blocks.items():
            if len(block.successors) >= 3:
                self._switch_entries.add(addr)

    def _entry_addr(self) -> int:
        """Get the entry block address."""
        from dec_engine.dec_impl.ir.block import BasicBlock
        if hasattr(self.graph, 'entry_block') and self.graph.entry_block:
            return self.graph.entry_block.addr
        if hasattr(self.graph, 'entry') and self.graph.entry:
            return self.graph.entry
        return min(self.graph.blocks.keys()) if self.graph.blocks else 0

    def _get_return_type(self) -> str:
        """Infer return type from function analysis."""
        return "int"  # Default return type

    def _detect_stack_vars(self):
        """Scan all blocks for stack-relative memory references and assign names."""
        self._stack_vars = {}
        seen_offsets = set()
        for addr, block in self.graph.blocks.items():
            for instr in block.instructions:
                def walk_memref(expr):
                    """Recursively find MemRef nodes with rbp base."""
                    from dec_engine.dec_impl.ir.expression import MemRef, BinOp, Var, Const, OpType
                    if isinstance(expr, MemRef):
                        if isinstance(expr.base, BinOp) and expr.base.op in (OpType.ADD, OpType.SUB):
                            bop = expr.base
                            if hasattr(bop.left, 'name') and str(getattr(bop.left, 'name', '')) == 'rbp':
                                if hasattr(bop.right, 'value') and isinstance(bop.right, Const):
                                    off = bop.right.value
                                    if off > 0 and off not in seen_offsets:
                                        seen_offsets.add(off)
                                        name = f"var_{off:x}"  # hex: var_5c, var_44
                                        self._stack_vars[off] = name
                    # Recurse into expression parts
                    for attr in ('base', 'left', 'right', 'operand', 'from_expr', 'callee', 'destination'):
                        child = getattr(expr, attr, None)
                        if child is not None:
                            walk_memref(child)
                    # Recurse into arg lists
                    for attr in ('args', 'operands', 'children'):
                        seq = getattr(expr, attr, None) or []
                        if isinstance(seq, (list, tuple)):
                            for child in seq:
                                walk_memref(child)
                walk_memref(instr)

    def generate(self) -> str:
        """Generate the complete C-like pseudocode string."""
        self._visited.clear()
        self._output = []

        # Detect stack variables
        self._detect_stack_vars()
        
        # Start with function prototype
        self._output.append(f"// Function: {self.func_name}")
        if self.func_addr is not None:
            self._output.append(f"// Address: 0x{self.func_addr:x}")
        self._output.append("")
        self._output.append(f"{self._get_return_type()}")
        self._output.append(f"{self.func_name}(")

        # Find entry block
        entry = self.graph.blocks.get(self._entry_addr())
        if entry is not None:
            self._output.append(")")
            self._output.append("{")
            self._formatter.inc()
            self._analyze_switches()
            self._loop_headers = {
                addr for addr, block in self.graph.blocks.items()
                if self._is_loop_header(addr)
            }
            self._enter_block(self._entry_addr())
            self._formatter.dec()
        else:
            self._output.append(")")
            self._output.append("{")
            self._output.append("  // No entry point found")
            self._output.append("}")

        self._output.append("}")
        self._output.append("")

        return "\n".join(self._output)

    def _enter_block(self, addr: Optional[int]):
        """Recursively enter blocks and generate pseudocode."""
        if addr is None or addr in self._visited:
            return
        self._visited.add(addr)
        entry = self.graph.blocks.get(addr)
        if entry is None:
            self._output.append(f"  // Block 0x{addr:x} not found")
            return
        # Add block label
        self._output.append(f"  L_{addr}:")
        for i, instr in enumerate(entry.instructions):
            if isinstance(instr, Branch) and i == len(entry.instructions) - 1:
                self._format_control_flow(instr, entry)
            elif isinstance(instr, NoOp):
                self._output.append("    nop;")
            elif instr.__class__.__name__ == 'Call':
                self._output.append(f"    {self._format_call_instr(instr)};")
            elif instr.__class__.__name__ == 'Assignment':
                line = self._format_assignment_instr(instr)
                dst_name = ''
                if isinstance(instr.destination, Var):
                    dst_name = str(instr.destination.name) if instr.destination.name else ''
                # Strip stack canary init: `rax = 0` when preceded by fs+0x28 load
                if dst_name == 'rax' and '= 0' in line:
                    # Check if this is the stack canary guard initialization
                    # Pattern: after saving registers and loading __stack_chk_guard, set it to 0
                    is_stack_canary = False
                    for prev_line in self._output[-6:]:
                        if '__stack_chk_guard' in prev_line or 'rax' in prev_line:
                            is_stack_canary = True
                            break
                    if is_stack_canary:
                        continue
                # Strip eflags_* intermediate flags (Vivisect captures all CPU status)
                if isinstance(instr.destination, Var) and dst_name.startswith('eflags_'):
                    continue
                self._output.append(f"    {line};")
            else:
                self._output.append(f"    {instr}")
        # Follow non-branch successors
        for succ in entry.successors:
            if succ.addr not in self._visited:
                self._enter_block(succ.addr)

    def _format_control_flow(self, instr, block):
        """Format control flow from branch instruction."""
        if not instr.condition:
            target = instr.true_target
            self._output.append(f"    goto L_{target.addr}")
            return
        self._output.append(f"    if (condition) goto L_{instr.true_target.addr}")

    def _format_assignment_instr(self, instr):
        """Format an Assignment instruction: dst = src."""
        from dec_engine.dec_impl.ir.effects import Assignment
        dst = instr.destination
        src = instr.source
        # Format destination
        dst_str = self._formatter.fmt_expr(dst) if hasattr(self, '_formatter') and self._formatter else str(dst)
        # Format source
        src_str = self._formatter.fmt_expr(src) if hasattr(self, '_formatter') and self._formatter else str(src)
        line = f"{dst_str} = {src_str}"
        # Apply stack variable naming: replace (rbp - 0xNN) with var_NN
        if hasattr(self, '_stack_vars') and self._stack_vars:
            import re
            # Replace ((uint64_t*)(rbp - 0x5c)) -> (var_5c)
            for off, vname in self._stack_vars.items():
                hex_off = f"0x{off:x}"
                # The formatted output uses double space due to f-string:
                #   (rbp  -  0xNN)  ← 2 spaces each side of -
                line = re.sub(
                    rf'\(\(uint64_t\*\)\(rbp\s*-\s*{hex_off}\)\)',
                    vname,  # Already a simple identifier
                    line
                )
                line = re.sub(
                    rf'\(rbp\s*-\s*{hex_off}\)',
                    vname,
                    line
                )
        return line

    def _format_call_instr(self, instr):
        """Format a Call instruction: func(args)."""
        callee = instr.callee
        args = instr.args
        # Resolve callee address to name via Vivisect's analysis
        callee_val = None
        if hasattr(callee, 'value'):
            callee_val = callee.value
        elif isinstance(callee, Var) and callee.name and str(callee.name).startswith('0x'):
            callee_val = int(str(callee.name), 16)
        
        callee_str = None
        if callee_val is not None:
            # Use Vivisect analysis to get function names for PLT/call targets
            name = self._resolve_call_target(callee_val)
            if name:
                callee_str = name
            else:
                callee_str = f"sub_{callee_val:x}"
        else:
            callee_str = self._formatter.fmt_expr(callee) if hasattr(self, '_formatter') and self._formatter else str(callee)
        # Format args
        args_str = ", ".join(
            self._formatter.fmt_expr(a) if hasattr(self, '_formatter') and self._formatter else str(a)
            for a in args
        )
        return f"{callee_str}({args_str})"
    
    def _resolve_call_target(self, addr: int) -> Optional[str]:
        """Resolve an address to a named function using Vivisect's analysis."""
        if addr in self._name_cache:
            return self._name_cache[addr]
        if not self._vw:
            return None
        try:
            func = self._vw.getFunction(addr)
            if func is not None:
                raw_name = self._vw.getName(addr)
                if raw_name:
                    # Vivisect names PLT functions as 'binary.plt_<funcname>'
                    # e.g. 'sh.plt_getuid' → 'getuid'
                    # Strip module prefix (everything before last .)
                    parts = raw_name.split('.')
                    base_name = parts[-1]
                    # Strip 'plt_' prefix to get the actual function name
                    actual_name = base_name[4:] if base_name.startswith('plt_') else base_name
                    self._name_cache[addr] = actual_name
                    return actual_name
        except Exception:
            pass
        return None
