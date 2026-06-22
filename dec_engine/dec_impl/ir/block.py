"""
Basic block and control flow graph representation.
Maps from Vivisect's visgraph.HierGraph to our IR-level CFG.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Set, Tuple


@dataclass
class BasicBlock:
    """A basic block in the decompiler IR."""

    addr: int  # Entry address in the function
    instructions: List["Instruction"] = field(default_factory=list)  # Ordered list
    predecessors: List["BasicBlock"] = field(default_factory=list)
    successors: List["BasicBlock"] = field(default_factory=list)
    label: str = ""  # Human-readable label
    is_entry: bool = False  # Is this the function entry?
    is_exit: bool = False  # Does this block terminate the function?
    metadata: Dict = field(default_factory=dict)  # Extra info (flags, etc.)


    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, other):
        if not isinstance(other, BasicBlock):
            return NotImplemented
        return self is other

    def add_predecessor(self, pred: "BasicBlock"):
        if pred not in self.predecessors:
            self.predecessors.append(pred)
            if self not in pred.successors:
                pred.successors.append(self)

    def __repr__(self):
        return f"BB@0x{self.addr:x} ({len(self.instructions)} instr)"


# Forward ref placeholder - Instruction type union resolved in builder.py
Instruction = None  # type: ignore


@dataclass
class BlockGraph:
    """CFG for a function: set of basic blocks with control flow edges."""

    entry_block: Optional[BasicBlock] = None  # type: ignore
    blocks: Dict[int, BasicBlock] = field(default_factory=dict)  # addr -> BB
    name: str = ""  # Function name

    def __post_init__(self):
        if self.entry_block is None and self.blocks:
            self.entry_block = min(self.blocks.values(), key=lambda b: b.addr)

    def find_block_by_addr(self, addr: int) -> Optional[BasicBlock]:
        return self.blocks.get(addr, None)

    def post_dominators(self) -> Dict[BasicBlock, Optional[BasicBlock]]:
        """Compute post-dominator tree (needed for structuring).
        Standard iterative algorithm: postdom(entry) = all blocks,
        iterate backward until fixed point.
        """
        if not self.blocks:
            return {}

        all_blocks = list(self.blocks.values())
        entry_block = self.entry_block

        # Post-dominators: PDBlock dominates QDBlock if all paths from entry to
        # QDBlock must pass through PDBlock.
        # entry post-dominates everything; all post-dominates entry;
        # others post-dom = intersection of successors' post-doms.

        # Reverse the graph (swap pred/succ)
        reverse_succ = {b: b.successors for b in all_blocks}

        # Initialize
        post_dom: Dict[BasicBlock, Optional[frozenset]] = {}
        for b in all_blocks:
            if b == entry_block:
                post_dom[b] = frozenset(all_blocks)
            else:
                if b.is_exit:
                    post_dom[b] = frozenset({b})
                else:
                    post_dom[b] = frozenset(b.successors)

        # Iterate until fixed point
        changed = True
        while changed:
            changed = False
            for b in all_blocks:
                if b.is_exit or b == entry_block:
                    continue
                # Compute post-dom as intersection of all successor post-doms
                # PLUS the block itself
                succs = [s for s in b.successors if s in post_dom]
                if not succs:
                    # Dead end?
                    continue
                new_pd: Optional[frozenset] = post_dom[succs[0]]
                if new_pd is None:
                    continue
                new_pd = frozenset(new_pd | {b})
                for s in succs[1:]:
                    s_pd = post_dom.get(s)
                    if s_pd is None:
                        continue
                    # Intersection
                    min_set = new_pd if len(new_pd) < len(s_pd) else s_pd
                    max_set = s_pd if min_set is s_pd else new_pd
                    new_pd = frozenset(x for x in min_set if x in max_set)
                if new_pd is None:
                    continue
                # If changed, update
                if post_dom[b] != new_pd:
                    post_dom[b] = new_pd
                    changed = True

        # Build result: block -> closest post-dominator
        result: Dict[BasicBlock, Optional[BasicBlock]] = {}
        for b in all_blocks:
            pd_set = post_dom.get(b)
            if pd_set is None or pd_set == frozenset():
                result[b] = None
            elif len(pd_set) == 1:
                result[b] = list(pd_set)[0]
            else:
                # Closest post-dominator
                closest: Optional[BasicBlock] = None
                closest_depth = -1
                for pred_b in pd_set:
                    pd_for_pred = post_dom.get(pred_b)
                    if pd_for_pred and len(pd_for_pred) > closest_depth:
                        closest = pred_b
                        closest_depth = len(pd_for_pred)
                result[b] = closest
        return result

    def dominators(self) -> Dict[BasicBlock, Set[BasicBlock]]:
        """Compute dominator tree (needed for structuring and phi insertion).
        Standard iterative algorithm (Allen & Cocke):
          dom(entry) = {entry}
          dom(others) = all blocks intersect successors (predecessors)
        """
        all_blocks = list(self.blocks.values())
        entry_block = self.entry_block

        if not entry_block:
            return {}

        # Initial: dom(entry) = {entry}; dom(others) = all blocks
        dom: Dict[BasicBlock, Set[BasicBlock]] = {entry_block: {entry_block}}
        others_set = set(all_blocks) - {entry_block}
        for b in all_blocks:
            if b != entry_block:
                dom[b] = set(all_blocks)

        # Iterate until fixed point
        changed = True
        while changed:
            changed = False
            for b in all_blocks:
                if b == entry_block:
                    continue
                preds = [p for p in b.predecessors if p in dom and dom[p] is not None]
                if not preds:
                    continue
                # Start with all blocks
                new_dom: Set[BasicBlock] = set(all_blocks)
                for p in preds:
                    dom_p = dom.get(p)
                    if dom_p is None:
                        continue
                    new_dom = new_dom & dom_p
                # Add self
                new_dom = new_dom | {b}
                if new_dom != dom[b]:
                    dom[b] = new_dom
                    changed = True

        return dom

    def back_edges(self) -> List[Tuple[BasicBlock, BasicBlock]]:
        """Find back edges in the CFG (used for loop detection).
        DFS-based: when visiting a successor that's already GRAY, it's a back edge.
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[BasicBlock, int] = {b: WHITE for b in self.blocks.values()}
        back_edges: List[Tuple[BasicBlock, BasicBlock]] = []

        def dfs(u: BasicBlock):
            color[u] = GRAY
            for v in u.successors:
                if v not in color:
                    continue
                if color[v] == GRAY:
                    back_edges.append((u, v))
                elif color[v] == WHITE:
                    dfs(v)
            color[u] = BLACK

        for b in self.blocks.values():
            if color[b] == WHITE:
                dfs(b)

        return back_edges

    def get_strongly_connected_components(
        self,
    ) -> List[List["BasicBlock"]]:
        """Find SCCs in the function's CFG using Tarjan's algorithm."""
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

        all_blocks = list(self.blocks.values())
        # Use iterative approach to avoid stack overflow on large CFGs
        for b in all_blocks:
            if b not in index:
                strongconnect(b)

        return sccs
