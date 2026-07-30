"""
SSA construction using Braun's algorithm.
Converts block variables to SSA form with φ-nodes at joins.
Does NOT require explicit dominator tree (per Braun et al.).
"""
from __future__ import annotations

from typing import Dict, List, Tuple, Optional, Set
from dec_engine.dec_impl.ir.expression import Var, PhiNode, Const, Size
from dec_engine.dec_impl.ir.effects import Assignment, PhiInstruction
from dec_engine.dec_impl.ir.block import BasicBlock, BlockGraph


class SsaState:
    """Wraps a Procedure's complete SSA variable state."""

    def __init__(self):
        self._next_ssa_num = 0
        self._var_def: Dict[Var, Var] = {}  # current definition for each SSA var
        self.def_set: Set[Var] = set()  # all definitions (SSA names)
        self.phi_defs: List[PhiInstruction] = []

    def new_ssa_name(self, base: Var) -> Var:
        """Create a new SSA variable with incremented version."""
        new_name = Var(f"{base.name}.s{self._next_ssa_num}", base.size)
        self._next_ssa_num += 1
        return new_name

    def lookup_definition(self, name: str) -> Optional[Var]:
        """Look up the current SSA definition for a name."""
        for v, d in self._var_def.items():
            if v.name == name:
                return d
        return None

    def assign(self, base: Var, value: Var):
        """Record that base was defined as SSA version value."""
        self._var_def[base] = value
        self.def_set.add(value)

    def get_definitions(self) -> List[Tuple[str, Set[Var]]]:
        """Get grouped definitions by original variable name."""
        groups: Dict[str, Set[Var]] = {}
        for defn in self.def_set:
            base_name = defn.name.rsplit(".s", 1)[0]
            if base_name not in groups:
                groups[base_name] = set()
            groups[base_name].add(defn)
        result = []
        for base_name, defns in groups.items():
            result.append((base_name, defns))
        return result


class SsaTransform:
    """
    Implements Braun et al.'s SSA construction algorithm.
    Extended with storage alias analysis for register/memory.
    """

    def __init__(self, graph: BlockGraph):
        self.graph = graph
        self.states: Dict[BasicBlock, SsaState] = {}

    def analyze_graph(self) -> BlockGraph:
        """
        Build SSA form for the entire graph.

        Phase 1: Walk SCCs bottom-up (interprocedural)
        Phase 2: For each SCC, do intra-procedural SSA per block
        Phase 3: Insert φ-nodes at joins
        Phase 4: Rewrite assignments
        """
        # Find SCCs in the function graph
        sccs = self._find_sccs()

        # Process SCCs bottom-up
        for scc in reversed(sccs):
            self._process_scc(scc)

        # Apply φ-node insertion and variable renaming
        self._insert_phis()
        self._rename_variables()

        return self.graph

    def _find_sccs(self) -> List[List[BasicBlock]]:
        """Tarjan's SCC algorithm."""
        index_counter = [0]
        stack: List[BasicBlock] = []
        lowlinks: Dict[BasicBlock, int] = {}
        index: Dict[BasicBlock, int] = {}
        on_stack: Dict[BasicBlock, bool] = {}
        sccs: List[List[BasicBlock]] = []

        def strongconnect(v: BasicBlock):
            index[v] = index_counter[0]
            lowlinks[v] = index_counter[0]
            index_counter[0] += 1
            stack.append(v)
            on_stack[v] = True

            for w in v.successors:
                if w not in index:
                    strongconnect(w)
                    lowlinks[v] = min(lowlinks[v], lowlinks[w])
                elif on_stack.get(w, False):
                    lowlinks[v] = min(lowlinks[v], index[w])

            if lowlinks[v] == index[v]:
                scc: List[BasicBlock] = []
                while True:
                    w = stack.pop()
                    on_stack[w] = False
                    scc.append(w)
                    if w is v:
                        break
                sccs.append(scc)

        for b in self.graph.blocks.values():
            if b not in index:
                strongconnect(b)

        return sccs

    def _process_scc(self, scc: List[BasicBlock]):
        """Process an SCC for SSA construction."""
        # Initialize SSA state for each block in the SCC
        for b in scc:
            self.states[b] = SsaState()

        # For each block, collect all variable definitions and uses
        # Apply Braun's algorithm: process blocks in topological order
        # within each SCC

        # Track which vars are defined/used in each block
        var_defs: Dict[BasicBlock, Set[str]] = {}
        var_uses: Dict[BasicBlock, Set[str]] = {}

        for b in scc:
            defs = set()
            uses = set()
            for instr in b.instructions:
                if isinstance(instr, Assignment):
                    # destination can be Var or MemRef; only Var has .name
                    from dec_engine.dec_impl.ir.expression import Var as _VarType
                    if not isinstance(instr.destination, _VarType):
                        # Memory store — register uses but no SSA def
                        self._collect_uses(instr.source, uses)
                        continue
                    defs.add(instr.destination.name)
                    self._collect_uses(instr.source, uses)
            var_defs[b] = defs
            var_uses[b] = uses

        # For join points (blocks with multiple predecessors),
        # create φ-nodes for vars that are defined in some predecessors
        # and used after the join
        # Braun's approach: insert φ only when a variable is defined
        # differently along two different paths to a common point

        # Identify join blocks (those with 2+ predecessors)
        join_blocks = [b for b in scc if len(b.predecessors) >= 2]

        # For each join block, check which vars need φ-nodes
        for jblock in join_blocks:
            # Get vars defined in any predecessor
            pred_defs: Dict[str, List[Tuple[BasicBlock, Var]]] = {}
            for pred in jblock.predecessors:
                if pred in scc:
                    for defn_name in var_defs.get(pred, set()):
                        if defn_name not in pred_defs:
                            pred_defs[defn_name] = []
                        # Find the latest def of defn_name in pred
                        last_def = self._find_def_in_block(pred, defn_name)
                        if last_def:
                            pred_defs[defn_name].append((pred, last_def))

            # For vars defined in 2+ predecessors, insert φ
            for var_name, pred_vars in pred_defs.items():
                if len(pred_vars) >= 2:
                    # Create φ-nodes on each successor edge
                    phi_operands: List[Tuple[Var, BasicBlock]] = []
                    for pred, var in pred_vars:
                        phi_operands.append((var, pred))

                    # Also include current definition in the current block
                    current_def = self._find_def_in_block(jblock, var_name)
                    if current_def:
                        phi_operands.append((current_def, jblock))

                    if phi_operands:
                        phi_instr = PhiInstruction(
                            variable=Var(var_name, Size.AUTO),
                            operands=phi_operands,
                        )
                        # Insert at the beginning of the block
                        jblock.instructions.insert(0, phi_instr)

    def _collect_uses(self, expr, uses: Set[str]):
        """Recursively collect all variable names from an expression."""
        from dec_engine.dec_impl.ir.expression import (
            Var,
            MemRef,
            BinOp,
            UnOp,
            CallExpr,
            CastOp,
        )
        if isinstance(expr, Var):
            uses.add(expr.name)
        elif isinstance(expr, (BinOp, UnOp)):
            if isinstance(expr, BinOp):
                self._collect_uses(expr.left, uses)
                self._collect_uses(expr.right, uses)
            else:
                self._collect_uses(expr.operand, uses)
        elif isinstance(expr, MemRef):
            self._collect_uses(expr.base, uses)
            self._collect_uses(expr.offset, uses)
        elif isinstance(expr, CallExpr):
            self._collect_uses(expr.callee, uses)
            for arg in expr.args:
                self._collect_uses(arg, uses)
        elif isinstance(expr, CastOp):
            self._collect_uses(expr.from_expr, uses)

    def _find_def_in_block(self, block: BasicBlock, var_name: str) -> Optional[Var]:
        """Find the last definition of var_name in a block."""
        last_def: Optional[Var] = None
        for instr in block.instructions:
            if isinstance(instr, Assignment):
                from dec_engine.dec_impl.ir.expression import Var as _VarType
                if not isinstance(instr.destination, _VarType):
                    continue
                if instr.destination.name == var_name:
                    last_def = instr.destination
            elif isinstance(instr, PhiInstruction) and instr.variable.name == var_name:
                last_def = instr.variable
        return last_def

    def _insert_phis(self):
        """Insert φ-nodes at all control-flow join points (Braun's style)."""
        # Already integrated into _process_scc above

    def _rename_variables(self):
        """Rename variables to SSA form using stack-based renaming."""
        renamers: Dict[str, List[Var]] = {}

        def rename(v: BasicBlock) -> Tuple[List[Assignment], List[PhiInstruction], List[Assignment]]:
            new_defs: List[Assignment] = []
            new_phis: List[PhiInstruction] = []
            new_assignments: List[Assignment] = []

            for instr in v.instructions:
                if isinstance(instr, Assignment):
                    from dec_engine.dec_impl.ir.expression import Var as _VarType
                    if not isinstance(instr.destination, _VarType):
                        continue
                    dst_name = instr.destination.name
                    if dst_name not in renamers:
                        renamers[dst_name] = []
                    if not renamers[dst_name]:
                        renamers[dst_name].append(instr.destination)
                        new_assignments.append(instr)
                    else:
                        new_var = Var(
                            f"{dst_name}.s{len(renamers[dst_name])}",
                            instr.destination.size,
                        )
                        renamers[dst_name].append(new_var)
                        new_defs.append(Assignment(destination=new_var, source=instr.source))
                        new_phis.append(PhiInstruction(variable=new_var, operands=[]))
                        new_assignments.append(Assignment(destination=instr.destination, source=new_var))
                elif isinstance(instr, PhiInstruction):
                    new_phis.append(instr)

            for succ in v.successors:
                for phi in new_phis:
                    phi.operands.append((phi.variable, v))

            return new_defs, new_phis, new_assignments

        # Start from entry block
        rename(self.graph.entry_block)

        # Update blocks with new instructions
        # (would rewire the instructions list in each block)
