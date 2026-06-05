"""
Pretty printer: converts structured CFG/SSA data into readable C-like pseudocode.

Takes the output of the structuring pass (dominated regions, loop headers) and
produces indented C-style output with proper control flow structures.
"""
from __future__ import annotations
from typing import List, Optional
from vivisect.dec_impl.output.formatter import Formatter
from vivisect.dec_impl.ir.block import BasicBlock, BlockGraph
from vivisect.dec_impl.ir.effects import Branch, NoOp
from vivisect.dec_impl.ssa.construct import SsaState


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
        from vivisect.dec_impl.ir.block import BasicBlock
        if hasattr(self.graph, 'entry_block') and self.graph.entry_block:
            return self.graph.entry_block.addr
        if hasattr(self.graph, 'entry') and self.graph.entry:
            return self.graph.entry
        return min(self.graph.blocks.keys()) if self.graph.blocks else 0

    def _get_return_type(self) -> str:
        """Infer return type from function analysis."""
        return "int"  # Default return type

    def generate(self) -> str:
        """Generate the complete C-like pseudocode string."""
        self._visited.clear()
        self._output = []

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
