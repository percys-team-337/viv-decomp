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
        # Structured control flow data
        self._dominators: dict[int, Optional[int]] = {}  # idom map
        self._natural_loops: list[dict] = []  # [{header, body_addrs, back_edges}]
        self._visited_blocks: set[int] = set()

    def _detect_prologue_length(self, entry):
        """Count prologue instructions in the entry block before real work."""
        count = 0
        saved_regs = set()
        instrs = entry.instructions
        i = 0
        while i < len(instrs):
            s = str(instrs[i])
            # Skip eflags_* intermediate instructions
            if 'eflags_' in s:
                count += 1
                i += 1
                continue
            # Detect push pattern: rsp decrement + store (rsp SUB 0x8) followed by [rsp] = reg
            if 'rsp' in s and 'SUB 0x8' in s and i + 1 < len(instrs):
                nxt = str(instrs[i + 1])
                if '[rsp' in nxt:
                    # Extract saved register: "[rsp + 0] = rbp" → rbp
                    parts = nxt.split('= ')
                    if len(parts) > 1:
                        saved_regs.add(parts[1].strip())
                    count += 2
                    i += 2
                    continue
            # Frame pointer setup: rbp = rsp
            if s.strip() == 'rbp = rsp':
                count += 1
                i += 1
                continue
            # Frame allocation: rsp = (rsp SUB N) where N > 8
            if 'rsp' in s and 'SUB 0x' in s and '0x8' not in s:
                count += 1
                i += 1
                continue
            # Stack canary init: fs + 0x28 load sequence
            if 'fs' in s and '0x28' in s:
                count += 1
                i += 1
                continue
            if 'rax' in s and 'fs' not in s and '= ((uint64_t*)(fs' not in s:
                count += 1
                i += 1
                continue
            break
        self._prologue_saved_regs = saved_regs
        return count

    def _format_prologue(self, entry):
        """Format condensed prologue as comments."""
        lines = []
        regs = getattr(self, '_prologue_saved_regs', set())
        if regs:
            lines.append(f"  // prologue: save {', '.join(sorted(regs))}")
        lines.append(f"  // allocate stack frame")
        return lines

    def _entry_addr(self) -> Optional[int]:
        """Get the entry block address."""
        from dec_engine.dec_impl.ir.block import BasicBlock
        if hasattr(self.graph, 'entry_block') and self.graph.entry_block:
            return self.graph.entry_block.addr
        if hasattr(self.graph, 'entry') and self.graph.entry:
            return self.graph.entry
        return min(self.graph.blocks.keys()) if self.graph.blocks else None

    def _get_return_type(self) -> str:
        """Get return type from Vivisect API info if available."""
        if self.func_addr is None or not self._vw:
            return "int"
        try:
            api = self._vw.getFunctionApi(self.func_addr)
            if api and isinstance(api, tuple) and len(api) >= 5:
                ret = api[0]
                if ret and ret != 'None':
                    return ret
        except Exception:
            pass
        return "int"

    def _get_param_types(self) -> list[tuple[str, Optional[str]]]:
        """Get parameter types from Vivisect API info. Returns list of (type, name) tuples."""
        if self.func_addr is None or not self._vw:
            return []
        try:
            api = self._vw.getFunctionApi(self.func_addr)
            if api and isinstance(api, tuple) and len(api) >= 5:
                proto = api[1] if len(api) > 1 else None
                if proto and hasattr(proto, 'params') and proto.params:
                    params = []
                    for p in proto.params:
                        if p is None:
                            continue
                        ptype = str(getattr(p, 'type', 'unknown'))
                        pname = getattr(p, 'name', None)
                        if pname:
                            params.append((ptype, pname))
                        else:
                            params.append((ptype, None))
                    return params
                # Fallback: check api[4] (params list)
                params_list = api[4] if len(api) > 4 and api[4] else None
                if params_list and hasattr(params_list, '__iter__'):
                    params = []
                    for param in params_list:
                        if param is None:
                            continue
                        ptype = str(getattr(param, 'type', 'unknown'))
                        pname = getattr(param, 'name', None)
                        if pname:
                            params.append((ptype, pname))
                        else:
                            params.append((ptype, None))
                    return params
        except Exception:
            pass
        return []

    def _detect_stack_vars(self):
        """Scan all blocks for stack-relative memory references and assign names."""
        self._stack_vars = {}
        seen_offsets = set()
        # Also track which _t_ temps are used as sources (to skip dead temp assigns)
        self._used_temps = set()
        for addr, block in self.graph.blocks.items():
            for instr in block.instructions:
                def walk_src_refs(expr, is_dest=False):
                    """Find Var references starting with _t_ in source expressions."""
                    from dec_engine.dec_impl.ir.expression import Var
                    if isinstance(expr, Var) and hasattr(expr, 'name') and expr.name and not is_dest:
                        name = str(expr.name)
                        if name.startswith('_t_') or name.startswith('$_t_'):
                            self._used_temps.add(name.lstrip('$'))
                    # Recurse
                    for attr in ('base', 'left', 'right', 'operand', 'from_expr', 'callee'):
                        child = getattr(expr, attr, None)
                        if child is not None:
                            walk_src_refs(child, False)
                    # Recurse into source (not destination) — destinations are writes, not reads
                    src = getattr(expr, 'source', None)
                    if src is not None:
                        walk_src_refs(src, False)
                    # Recurse into arg lists (these are source operands in Call)
                    for attr in ('args', 'operands', 'children'):
                        seq = getattr(expr, attr, None) or []
                        for child in (seq if isinstance(seq, (list, tuple)) else []):
                            walk_src_refs(child, False)
                walk_src_refs(instr)

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
                                        name = f"var_{off:x}"
                                        self._stack_vars[off] = name
                    # Recurse into expression parts
                    for attr in ('base', 'left', 'right', 'operand', 'from_expr', 'callee', 'destination', 'source'):
                        child = getattr(expr, attr, None)
                        if child is not None:
                            walk_memref(child)
                    for attr in ('args', 'operands', 'children'):
                        seq = getattr(expr, attr, None) or []
                        for child in (seq if isinstance(seq, (list, tuple)) else []):
                            walk_memref(child)
                walk_memref(instr)

    def generate(self) -> str:
        """Generate the complete C-like pseudocode string using structured control flow."""
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

        # Find entry block and compute structured control flow
        entry = self.graph.blocks.get(self._entry_addr())
        if entry is not None:
            self._output.append(")")
            self._output.append("{")
            
            # Phase 1: Compute dominators and natural loops
            self._compute_dominators()
            self._find_natural_loops()
            
            # Phase 2: Walk CFG using dominator tree for structured output
            self._formatter.inc()
            loop_map = {l['header']: l for l in self._natural_loops}
            dom_children = self._build_dominator_tree()
            entry_addr = self._entry_addr()
            if entry_addr is not None and entry_addr in self.graph.blocks:
                self._walk_structured(entry_addr, loop_map, dom_children)
            
            self._formatter.dec()
            self._output.append("}")
        else:
            self._output.append(")")
            self._output.append("{")
            self._output.append("  // No entry point found")
            self._output.append("}")

        self._output.append("")
        return "\n".join(self._output)

    def _walk_structured(self, addr: int, loop_map: dict, dom_children: dict):
        """Walk CFG using dominator tree for structured output instead of DFS."""
        if addr in self._visited or addr not in self.graph.blocks:
            return
        self._visited.add(addr)
        
        block = self.graph.blocks[addr]
        is_header = addr in loop_map
        
        # Emit prologue/local vars once for entry
        if addr == self._entry_addr():
            prologue_len = self._detect_prologue_length(block)
            lines = self._format_prologue(block)
            if hasattr(self, '_stack_vars') and self._stack_vars:
                for off in sorted(self._stack_vars.keys()):
                    vname = self._stack_vars[off]
                    lines.append(f"    uint64_t {vname};")
            self._output.extend(lines)
        else:
            prologue_len = 0
        
        # Add block label
        if prologue_len == 0 and not is_header:
            self._output.append(f"  L_{addr}:")
        
        # Emit block body instructions (excluding branches)
        for i, instr in enumerate(block.instructions):
            if prologue_len > 0 and i < prologue_len:
                continue
            
            if isinstance(instr, Branch):
                continue  # Handled below
            if isinstance(instr, NoOp):
                self._output.append("    nop;")
            elif instr.__class__.__name__ == 'Call':
                self._output.append(f"    {self._format_call_instr(instr)};")
            elif instr.__class__.__name__ == 'Assignment':
                line = self._format_assignment_instr(instr)
                dst_name = ''
                if isinstance(instr.destination, Var):
                    dst_name = str(instr.destination.name) if instr.destination.name else ''
                # Strip stack canary init
                if dst_name == 'rax' and '= 0' in line:
                    is_stack_canary = any('__stack_chk_guard' in prev_line or 'rax' in prev_line 
                                         for prev_line in self._output[-6:])
                    if is_stack_canary:
                        continue
                # Strip eflags_ intermediates
                if isinstance(instr.destination, Var) and dst_name.startswith('eflags_'):
                    continue
                # Strip dead _t_ temps
                dst_str_check = (self._formatter.fmt_expr(instr.destination) 
                                if hasattr(self, '_formatter') else str(instr.destination))
                dst_str_check = dst_str_check.lstrip('$')
                if dst_str_check.startswith('_t_') and dst_str_check not in getattr(self, '_used_temps', set()):
                    continue
                self._output.append(f"    {line};")
            else:
                self._output.append(f"    {instr}")
        
        # Handle control flow based on branch type
        branches = [ins for ins in block.instructions if isinstance(ins, Branch)]
        
        if is_header:
            # Loop header: emit a structured while(cond) loop wrapping the body
            self._output_loop(addr, loop_map[addr], loop_map, dom_children)
        elif len(branches) >= 2:
            # If/else from two conditional branches
            self._output_if_else(block, addr, branch_count=1)  # Emit once per block level
        elif len(branches) == 1:
            # Single conditional branch or unconditional jump
            self._output_single_branch(block, addr)
        else:
            # No branches - follow successors (shouldn't happen for terminal blocks)
            for succ in block.successors:
                if hasattr(succ, 'addr') and succ.addr not in self._visited:
                    self._walk_structured(succ.addr, loop_map, dom_children)

    def _extract_loop_condition(self, header: BasicBlock) -> str:
        """Extract the loop condition string from the header block's branches.

        The header's conditional branch encodes the loop invariant: taken edge
        continues the body (or exits), while the fall-through exits (or loops).
        Without a resolved comparison, we emit a readable flag comment.
        """
        branches = [ins for ins in header.instructions if isinstance(ins, Branch)]
        cond_branch = next((b for b in branches if b.condition is not None), None)
        if cond_branch is None:
            return "true"  # unconditional loop
        cond_raw = self._formatter.fmt_expr(cond_branch.condition)
        if cond_raw.startswith('eflags_'):
            return f"/* {cond_raw}: flags */"
        return cond_raw.lstrip('(').rstrip(')')

    def _output_loop(self, header_addr: int, loop_info: dict, loop_map: dict, dom_children: dict):
        """Emit a structured while(cond) { ... } loop for a natural loop header."""
        block = self.graph.blocks[header_addr]

        # Emit while opener with the loop condition
        cond_str = self._extract_loop_condition(block)
        self._output.append(f"  while ({cond_str}) {{")
        self._formatter.inc()

        # Prologue/local-var declarations (only for entry-header)
        if header_addr == self._entry_addr():
            prologue_len = self._detect_prologue_length(block)
            lines = self._format_prologue(block)
            if getattr(self, '_stack_vars', None):
                for off in sorted(self._stack_vars.keys()):
                    vname = self._stack_vars[off]
                    lines.append(f"    uint64_t {vname};")
            self._output.extend(lines)
        else:
            prologue_len = 0

        # Emit the header's own non-branch instructions inside the lo body
        for i, instr in enumerate(block.instructions):
            if prologue_len > 0 and i < prologue_len:
                continue
            if isinstance(instr, Branch):
                continue  # control flow handled below
            if isinstance(instr, NoOp):
                self._output.append(f"{self._formatter.indent()}nop;")
            elif instr.__class__.__name__ == 'Call':
                self._output.append(f"{self._formatter.indent()}{self._format_call_instr(instr)};")
            elif instr.__class__.__name__ == 'Assignment':
                line = self._format_assignment_instr(instr)
                dst_name = ''
                if isinstance(instr.destination, Var):
                    dst_name = str(instr.destination.name) if instr.destination.name else ''
                # Strip stack-canary init / eflags_ / dead temps
                if dst_name == 'rax' and '= 0' in line:
                    is_stack_canary = any('__stack_chk_guard' in prev or 'rax' in prev
                                          for prev in self._output[-6:])
                    if is_stack_canary:
                        continue
                if isinstance(instr.destination, Var) and dst_name.startswith('eflags_'):
                    continue
                dst_str_check = (self._formatter.fmt_expr(instr.destination)
                                 if hasattr(self, '_formatter') else str(instr.destination))
                dst_str_check = dst_str_check.lstrip('$')
                if dst_str_check.startswith('_t_') and dst_str_check not in getattr(self, '_used_temps', set()):
                    continue
                self._output.append(f"{self._formatter.indent()}{line};")
            else:
                self._output.append(f"{self._formatter.indent()}{instr}")

        # Walk loop body: dominator-tree children that live inside the natural loop.
        # A dom-child of the header is part of the body iff it is in body_addrs
        # AND not already visited. Exit blocks (dom-children but NOT in the body)
        # are left for the enclosing scope — they must not render inside the loop.
        body_addrs = loop_info.get('body_addrs', set())
        for child in sorted(dom_children.get(header_addr, [])):
            if child in self._visited:
                continue
            if child not in body_addrs:
                continue  # exit / non-loop sibling: handled by enclosing scope
            self._walk_structured(child, loop_map, dom_children)

        # Close the loop
        self._formatter.dec()
        self._output.append(f"  }}")

    def _output_if_else(self, block, addr: int, branch_count: int):
        """Emit if/else construct from conditional branches."""
        branches = [ins for ins in block.instructions if isinstance(ins, Branch)]
        cond1_raw = self._formatter.fmt_expr(branches[0].condition) if branches[0].condition else "true"
        
        # Format condition string (handle eflags_ as unresolved flag check)
        if cond1_raw.startswith('eflags_'):
            cond_str = f"/* {cond1_raw}: flags */"
            actual_cond = "*"  # placeholder
        else:
            cond_str = cond1_raw.lstrip('(').rstrip(')')
            actual_cond = cond1_raw
        
        if len(branches) >= 2:
            # Two-way branch -> if/else  
            b1, b2 = branches[0], branches[1]
            t1_addr = getattr(getattr(b1, 'true_target', None), 'addr', None)
            t2_addr = getattr(getattr(b2, 'true_target', None), 'addr', None)
            
            if cond_str.startswith('/*') and '*/' in cond_str:
                self._output.append(f"    {cond_str}")
                self._output.append("    if (*) {")  # Unresolved condition
            else:
                self._output.append(f"    if ({cond_str}) {{")
            
            # Visit target block
            if t1_addr is not None and t1_addr not in self._visited:
                self._walk_structured(t1_addr, {}, {})
            
            if t2_addr is not None:
                self._output.append("    } else {")
                if t2_addr not in self._visited:
                    self._walk_structured(t2_addr, {}, {})
            
            self._output.append("}")
        else:
            # Single conditional branch
            target = getattr(getattr(branches[0], 'true_target', None), 'addr', None)
            if cond_str.startswith('/*') and '*/' in cond_str:
                self._output.append(f"    {cond_str}")
            elif not actual_cond.startswith('(NOT'):
                self._output.append(f"    if ({actual_cond}) {{")
                if target is not None and target not in self._visited:
                    self._walk_structured(target, {}, {})
                self._output.append("}")
            else:
                # Negation pattern
                base = actual_cond[4:].rstrip(')').replace('~', '').strip() if actual_cond.startswith('(NOT') or actual_cond.startswith('~(') else actual_cond[:-1]
                self._output.append(f"    if ({base}) {{")
                if target and target not in self._visited:
                    self._walk_structured(target, {}, {})
                self._output.append("}")

    def _compute_dominators(self):
        """Compute immediate dominators using iterative dataflow."""
        if not self.graph.blocks:
            return
        
        all_addrs = list(self.graph.blocks.keys())
        entry_addr = self._entry_addr()
        
        # Initialize: each block dominated by everyone (will narrow)
        doms = {}
        for addr in all_addrs:
            if addr == entry_addr:
                doms[addr] = {entry_addr}
            else:
                doms[addr] = set(all_addrs)
        
        changed = True
        iterations = 0
        max_iter = len(all_addrs) * 2 + 10
        
        while changed and iterations < max_iter:
            changed = False
            iterations += 1
            for addr in all_addrs:
                if addr == entry_addr:
                    continue
                block = self.graph.blocks[addr]
                preds = [p.addr for p in getattr(block, 'predecessors', [])
                         if hasattr(p, 'addr') and p.addr in doms and doms[p.addr]]
                if not preds:
                    continue
                common = set(doms[preds[0]])
                for p in preds[1:]:
                    common &= doms.get(p, all_addrs)
                new_dom = common | {addr}
                if new_dom != doms[addr]:
                    doms[addr] = new_dom
                    changed = True
        
        # Compute immediate dominators (closest strict dominator)
        idoms: dict[int, Optional[int]] = {}
        for addr in all_addrs:
            if addr not in doms or len(doms[addr]) <= 1:
                idoms[addr] = None
                continue
            strict_doms = doms[addr] - {addr}
            if not strict_doms:
                idoms[addr] = None
            elif len(strict_doms) == 1:
                idoms[addr] = next(iter(strict_doms))
            else:
                # Immediate dominator = closest strict dominator = the one
                # whose dominance set is LARGEST (it dominates more, i.e. is
                # lower in the tree, covering all other strict dominators).
                idoms[addr] = max(strict_doms, key=lambda d: len(doms.get(d, {d})))
        
        self._dominators = idoms

    def _find_natural_loops(self):
        """Find natural loops using dominator tree + back-edge detection."""
        if not self.graph.blocks or not self._dominators:
            return
        
        # Build dominance sets from idom map
        dom_sets: dict[int, set[int]] = {}
        for addr in self._dominators:
            d_set = {addr}
            cur = self._dominators.get(addr)
            while cur is not None and cur != -1 and cur in self.graph.blocks:
                d_set.add(cur)
                nxt = self._dominators.get(cur) if cur in self._dominators else None
                if nxt == cur or nxt is None:
                    break
                cur = nxt
            dom_sets[addr] = d_set
        
        # Find back-edges (src -> dst where dst dominates src)
        back_edges: list[tuple[int, int]] = []
        all_keys = list(self.graph.blocks.keys())
        for addr, block in self.graph.blocks.items():
            succs = [s.addr for s in getattr(block, 'successors', []) 
                     if hasattr(s, 'addr') and s.addr in self.graph.blocks]
            for dst in succs:
                if dst != addr and dst in dom_sets.get(addr, set()):
                    back_edges.append((addr, dst))
        
        # Group by header and compute bodies
        loop_map: dict[int, dict] = {}
        processed: set[int] = set()
        
        for src, dst in back_edges:
            if dst in processed:
                continue
            
            body_addrs: set[int] = {dst}  # Header in body
            worklist = [src]
            visited = {dst}
            
            while worklist:
                node_addr = worklist.pop()
                if node_addr in visited and node_addr != src:
                    continue
                visited.add(node_addr)
                body_addrs.add(node_addr)
                
                curr_blk = self.graph.blocks.get(node_addr)
                if not curr_blk:
                    continue
                preds = getattr(curr_blk, 'predecessors', [])
                for pred in preds:
                    pred_addr = getattr(pred, 'addr', None)
                    if (pred_addr is not None and 
                        pred_addr != dst and 
                        pred_addr not in visited):
                        worklist.append(pred_addr)
            
            processed.add(dst)
            loop_map[dst] = {
                'header': dst,
                'body_addrs': body_addrs,
                'back_edges': [(src, dst)],
                'size': len(body_addrs),
            }
        
        self._natural_loops = list(loop_map.values())

    def _build_dominator_tree(self) -> dict[int, list[int]]:
        """Build dominator tree from idom map."""
        children: dict[int, list[int]] = {}
        for child, parent in self._dominators.items():
            if parent is not None and parent != -1:
                children.setdefault(parent, []).append(child)
        
        return dict(children)

    def _output_single_branch(self, block, addr: int):
        """Emit a single conditional branch as if-then or just comment."""
        branches = [ins for ins in block.instructions if isinstance(ins, Branch)]
        if not branches:
            return
        
        b1 = branches[0]
        target_addr = getattr(getattr(b1, 'true_target', None), 'addr', None)
        
        # Handle unconditional jumps as plain block visits
        cond_raw = self._formatter.fmt_expr(b1.condition) if b1.condition else None
        if not cond_raw or cond_raw == "":
            # Unconditional jump - just follow it
            if target_addr is not None and target_addr not in self._visited:
                self._walk_structured(target_addr, {}, {})
            return
        
        # Conditional branch
        cond_str = f"/* {cond_raw}: flags */" if cond_raw.startswith('eflags_') else cond_raw
        self._output.append(f"    /* condition: {cond_raw} */")
        
        if target_addr and target_addr not in self._visited:
            # Check for negation pattern - strip NOT/~~ prefixes  
            base = cond_str.lstrip('(')
            if base.startswith('NOT('):
                base = base[4:]
            elif base.startswith('~'):
                base = base[1:].lstrip('(')
            base = base.rstrip(')')
            self._output.append(f"    if ({base}) {{")
            self._walk_structured(target_addr, {}, {})
            self._output.append("}")
            self._output.append("}")

    def _enter_block(self, addr: Optional[int], show_label: bool = True):
        """Recursively enter blocks and generate pseudocode."""
        if addr is None or addr in self._visited:
            return
        self._visited.add(addr)
        entry = self.graph.blocks.get(addr)
        if entry is None:
            self._output.append(f"  // Block 0x{addr:x} not found")
            return

        # For the entry block, condense the prologue
        if addr == self._entry_addr():
            # Detect prologue first (populates _prologue_saved_regs)
            prologue_len = self._detect_prologue_length(entry)
            lines = self._format_prologue(entry)
            # Add local variable declarations
            if hasattr(self, '_stack_vars') and self._stack_vars:
                # Sort by offset ascending
                for off in sorted(self._stack_vars.keys()):
                    vname = self._stack_vars[off]
                    lines.append(f"    uint64_t {vname};")
            self._output.extend(lines)
        else:
            prologue_len = 0

        # Add block label (skip for entry after prologue, or when suppressed)
        if prologue_len == 0 and show_label:
            self._output.append(f"  L_{addr}:")
        
        for i, instr in enumerate(entry.instructions):
            if prologue_len > 0 and i < prologue_len:
                continue
            if isinstance(instr, Branch):
                # Branches handled by _format_control_flow below
                self._branches_handled = True
                continue
            if isinstance(instr, NoOp):
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
                # Strip dead _t_ temp assignments (SSA temps never read)
                dst_str_check = self._formatter.fmt_expr(instr.destination) if hasattr(self, '_formatter') else str(instr.destination)
                dst_str_check = dst_str_check.lstrip('$')  # Remove $ prefix before checking
                if dst_str_check.startswith('_t_') and dst_str_check not in getattr(self, '_used_temps', set()):
                    continue
                self._output.append(f"    {line};")
            else:
                self._output.append(f"    {instr}")
        # Handle control flow from branch instructions
        if getattr(self, '_branches_handled', False):
            first_branch = next(
                (ins for ins in entry.instructions if isinstance(ins, Branch)),
                None
            )
            if first_branch:
                self._format_control_flow(first_branch, entry)
        else:
            # Follow non-branch successors
            for succ in entry.successors:
                if succ.addr not in self._visited:
                    self._enter_block(succ.addr)

    def _format_control_flow(self, instr, block):
        """Format control flow from branch instruction.
        Detects if-then-else patterns from successor blocks and emits structured code.
        """
        from dec_engine.dec_impl.ir.effects import Branch
        
        # If we have a valid block, try to detect if/else patterns
        branches = []
        if block is not None and hasattr(block, 'instructions'):
            branches = [ins for ins in block.instructions if isinstance(ins, Branch)]
        
        # Check the pattern: 2 conditional branches targeting different blocks
        if len(branches) >= 2:
            b1, b2 = branches[0], branches[1]
            cond1_raw = self._formatter.fmt_expr(b1.condition) if b1.condition else "condition"
            cond2_raw = self._formatter.fmt_expr(b2.condition) if b2.condition else "condition"
            
            # Recognize eflags-based conditions (Vivisect stores them as vars like eflags_eq, eflags_ne)
            # Convert to readable form with a note that the actual comparison is unknown
            cond1_str = f"/* {cond1_raw}: flags */" if cond1_raw.startswith('eflags_') else cond1_raw
            cond2_str = f"/* {cond2_raw}: flags */" if cond2_raw.startswith('eflags_') else cond2_raw
            
            # Detect negation patterns: if (NOT(X)) { A } else { B } -> if (X) { A } else { B }
            if cond1_raw.startswith('NOT(') or cond1_raw.startswith('~(') or cond1_raw == '~' + cond2_raw:
                base_cond1 = cond1_str[4:].rstrip(')') if cond1_str.startswith('/* NOT(') and ': flags */' in cond1_str else cond1_str
                cond1_str, cond2_str = cond2_str, cond1_str
            
            if b1.condition and b2.condition:
                # Check for empty blocks to avoid dead code in output
                b1_block = self.graph.blocks.get(b1.true_target.addr)
                b2_block = self.graph.blocks.get(b2.true_target.addr)
                b1_has_code = b1_block and any(
                    not isinstance(i, Branch) 
                    for i in b1_block.instructions
                )
                b2_has_code = b2_block and any(
                    not isinstance(i, Branch) 
                    for i in b2_block.instructions
                )
                
                # If the if-block is empty, emit else-if construct instead
                if not b1_has_code and b2_has_code:
                    # Check if condition is eflags-based (unresolved)
                    if '/*' in cond1_str and '*/' in cond1_str:
                        self._output.append(f"    {cond1_str}")
                        self._output.append("    if (*)")  # Unresolved condition
                    else:
                        self._output.append(f"    if ({cond1_str})")
                    self._output.append("    {")
                    self._output.append("    }")
                    
                    # Handle cond2 the same way for eflags
                    if '/*' in cond2_str and '*/' in cond2_str:
                        self._output.append(f"    else /* flags condition */")
                        self._output.append("    if (*)")
                    else:
                        self._output.append(f"    else if ({cond2_str})")
                    
                    self._output.append("    {")
                    self._enter_block(b2.true_target.addr, show_label=False)
                    self._output.append("    }")
                    return
                
                # Normal if-else handling  
                if '/*' in cond1_str and '*/' in cond1_str:
                    self._output.append(f"    {cond1_str}")
                    self._output.append("    if (*)")
                else:
                    self._output.append(f"    if ({cond1_str})")
                
                self._output.append("    {")
                if b1_has_code:
                    self._enter_block(b1.true_target.addr, show_label=False)
                self._output.append("    }")
                if b2_has_code:
                    self._output.append("    else")
                    self._output.append("    {")
                    self._enter_block(b2.true_target.addr, show_label=False)
                    self._output.append("    }")
                return
        
        # Fallback: emit based on the passed instruction
        target = getattr(instr, 'true_target', None)
        if target is not None and hasattr(instr, 'condition') and instr.condition:
            cond = self._formatter.fmt_expr(instr.condition) if hasattr(self, '_formatter') else str(instr.condition)
            # Recognize eflags-based conditions (Vivisect stores them as vars like eflags_eq, eflags_ne)
            # Convert to readable form with a note that the actual comparison is unknown
            if cond.startswith('eflags_'):
                self._output.append(f"    /* {cond}: check flags from previous cmp/test */")
                self._output.append(f"    if (1) goto L_{target.addr}")  # Always true - condition unresolved
            else:
                self._output.append(f"    if ({ cond}) goto L_{ target.addr}")
        elif target is not None:
            self._output.append(f"    goto L_{target.addr}")

    def _format_assignment_instr(self, instr):
        """Format an Assignment instruction: dst = src."""
        from dec_engine.dec_impl.ir.effects import Assignment
        dst = instr.destination
        src = instr.source
        # Format destination
        dst_str = self._formatter.fmt_expr(dst) if hasattr(self, '_formatter') and self._formatter else str(dst)
        # Clean up variable names: strip $ prefix from SSA temps
        if dst_str.startswith('$_t_'):
            dst_str = dst_str[1:]  # Remove leading $
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
        
        # Resolve callee to name
        callee_str = None
        callee_val = None
        
        # Try to extract address from various node types
        if hasattr(callee, 'value'):
            # Const node with direct address
            callee_val = callee.value
        elif isinstance(callee, Var) and callee.name:
            # Check if it's a register holding a known function pointer
            name_candidate = str(callee.name)
            # Look up if this is a known PLT stub address stored in rax/rbx/etc
            # Common pattern: mov rax, sub_... ; call rax -> we see the var but not the value
            # Try to resolve from workspace if we have register info (complex case - skip for now)
            pass
        
        # If we have a concrete address, use it; otherwise format the expression as-is
        if callee_val is not None:
            name = self._resolve_call_target(callee_val)
            if name:
                callee_str = name
            else:
                callee_str = f"sub_{callee_val:x}"
        
        # If still null, try extracting from formatted Var (e.g., Var with name like "func_401234")
        if callee_str is None and isinstance(callee, Var) and hasattr(self._formatter, 'fmt_expr'):
            expr_str = self._formatter.fmt_expr(callee)
            # Check if it's a known function name pattern  
            if expr_str.startswith("func_") or expr_str.startswith("plt_"):
                callee_str = expr_str
            elif expr_str in ("rax", "rbx", "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"):
                # Indirect call through register - we can't resolve the target without dataflow tracking
                callee_str = None  # Signal that this is unresolved
            else:
                callee_str = expr_str
        
        # Fallback to raw expression formatting or register-based indirection note
        if callee_str is None:
            if isinstance(callee, Var) and hasattr(self._formatter, 'fmt_expr'):
                expr_str = self._formatter.fmt_expr(callee)
                if expr_str in ("rax", "rbx", "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"):
                    # Indirect call - mark as unresolved but show register
                    callee_str = f"/* ind: {expr_str} */?"  
                else:
                    callee_str = expr_str
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

    def _is_loop_header(self, addr: int) -> bool:
        """Check if a block address is a loop header."""
        return addr in self._loop_headers

    def _is_switch_entry(self, addr: int) -> bool:
        """Check if a block at the given address has 3+ successors (switch pattern)."""
        block = self.graph.blocks.get(addr)
        if block is None:
            return False
        succs = getattr(block, 'successors', [])
        return len(succs) >= 3

    def _analyze_switches(self):
        """Scan all blocks for switch entry points (3+ successors)."""
        self._switch_entries.clear()
        for addr in self.graph.blocks:
            if self._is_switch_entry(addr):
                self._switch_entries.add(addr)
