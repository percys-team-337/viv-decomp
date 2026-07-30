"""
Control flow restructuring pass for the decompiler.

Maps from Reko's "Controlled Program Decomposition" to Vivisect's analysis.
Takes a BlockGraph with SSA form and decomposes it into:
- Domination regions
- Loop bodies
- Structured blocks (if/else/loop)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Set, Tuple
from dec_engine.dec_impl.ir.block import BasicBlock, BlockGraph
from dec_engine.dec_impl.ir.expression import Expression
from dec_engine.dec_impl.ir.effects import Branch, NoOp


class Region:
    """A set of blocks dominated by a header block."""

    def __init__(self, header: BasicBlock):
        self.header = header
        self.blocks: List[BasicBlock] = [header]
        self.children: List[Region] = []

    @property
    def size(self) -> int:
        return len(self.blocks)


class Loop:
    """A detected natural loop."""

    def __init__(self, header: BasicBlock, back_edge_src: Optional[BasicBlock] = None):
        self.header = header
        self.back_edges: List[Tuple[BasicBlock, BasicBlock]] = []
        if back_edge_src:
            self.back_edges.append((back_edge_src, header))
        self.body: List[BasicBlock] = []
        self.body_set: Set[int] = set()

    def add_back_edge(self, src: BasicBlock):
        self.back_edges.append((src, self.header))

    def add_body(self, block: BasicBlock):
        if block.addr not in self.body_set:
            self.body.append(block)
            self.body_set.add(block.addr)

    @property
    def is_nested(self) -> bool:
        return len(self.body) > 1

    def __repr__(self):
        return f"Loop(header=0x{self.header.addr:x}, body={len(self.body)})"


@dataclass
class StructuredBlock:
    """A structured block representing if/else/loop."""

    addr: int
    kind: str  # "if", "else", "loop", "switch", "sequence"
    condition: Optional[Expression] = None
    children: List[StructuredBlock] = field(default_factory=list)
    then_body: List[StructuredBlock] = field(default_factory=list)
    else_body: List[StructuredBlock] = field(default_factory=list)

    def add_child(self, child: 'StructuredBlock'):
        if child not in self.children:
            self.children.append(child)

    def __repr__(self):
        return f"StructuredBlock({self.kind}@0x{self.addr:x})"


class StructuredCFG:
    """Structured control flow for a function."""

    def __init__(self, entry_block: BasicBlock):
        self.entry_block = entry_block
        self.regions: List[Region] = []
        self.loops: List[Loop] = []
        self.root: Optional[StructuredBlock] = None

    @property
    def block_count(self) -> int:
        return len(self.enter_region_blocks()) + len(self.enter_loop_bodies())

    def enter_region_blocks(self) -> List[BasicBlock]:
        blocks = set()
        for region in self.regions:
            blocks.update(region.blocks)
        return list(blocks)

    def enter_loop_bodies(self) -> List[BasicBlock]:
        return [b for loop in self.loops for b in loop.body]


class StructuringPass:
    """Decompose a CFG into structured control flow.

    Performs:
    - Dominated region analysis
    - Natural loop detection
    - Structured block generation
    """

    def __init__(self, graph: BlockGraph):
        self.graph = graph
        self._region_map: Dict[int, Region] = {}
        self._loop_map: Dict[int, Loop] = {}
        self._structured_cfg: Optional[StructuredCFG] = None

    @property
    def regions(self) -> List[Region]:
        return list(self._region_map.values())

    @property
    def loops(self) -> List[Loop]:
        return list(self._loop_map.values())

    @property
    def structured_cfg(self) -> StructuredCFG:
        if self._structured_cfg is None:
            self._structured_cfg = self.run()
        return self._structured_cfg

    def run(self) -> StructuredCFG:
        """Run the structuring pass."""
        self._determine_regions()
        self._detect_loops()
        self._build_structured_cfg()
        return self._structured_cfg or StructuredCFG(self.graph.entry_block)

    def _determine_regions(self) -> None:
        """Find dominated regions in the CFG.

        A dominated region consists of all blocks dominated by a header block
        plus the header itself. This forms the building block for loop detection.
        """
        dominators = self.graph.dominators()
        all_blocks = list(self.graph.blocks.values())

        if not all_blocks:
            return

        entry = self.graph.entry_block
        if not entry:
            return

        # Each block with predecessors is a potential region header
        multi_pred = [b for b in all_blocks if len(b.predecessors) >= 2]

        # Also find natural loop headers from back edges
        back_edges = self.graph.back_edges()
        loop_headers = {target for _, target in back_edges}

        # Build regions for each candidate header
        for header in multi_pred + list(loop_headers):
            if header in self._region_map:
                continue

            # Collect all blocks dominated by this header
            region_blocks = []
            for b in all_blocks:
                if header in dominators.get(b, set()):
                    region_blocks.append(b)

            if region_blocks:
                region = Region(header)
                region.blocks = region_blocks
                self._region_map[header.addr] = region

        # Remaining blocks in their own regions
        seen = set(self._region_map.values())
        for b in all_blocks:
            if b not in seen:
                region = Region(b)
                self._region_map[b.addr] = region
                seen.add(b)

    def _detect_loops(self) -> None:
        """Find natural loops in the CFG using back-edges and dominators."""
        back_edges = self.graph.back_edges()
        dominators = self.graph.dominators()

        for src, target in back_edges:
            if target.addr in self._loop_map:
                loop = self._loop_map[target.addr]
                loop.add_back_edge(src)
                continue

            loop = Loop(target, src)

            # Find all blocks that can reach src without going through target
            worklist = [src]
            visited = set()
            while worklist:
                b = worklist.pop()
                if b.addr in visited or b is target:
                    continue
                visited.add(b.addr)
                loop.add_body(b)
                for pred in b.predecessors:
                    if pred is not target and pred.addr not in visited:
                        worklist.append(pred)

            self._loop_map[target.addr] = loop
            target_region = self._region_map.get(target.addr)
            if target_region is not None:
                for b in loop.body:
                    if b not in target_region.blocks:
                        target_region.blocks.append(b)

    def _build_structured_cfg(self) -> None:
        """Build structured block hierarchy from CFG."""
        entries = [b for b in self.graph.blocks.values() if b.is_entry]

        if not entries:
            return

        entry = entries[0]
        self._structured_cfg = StructuredCFG(entry)

        # Build structure from entry block following control flow
        self._enter_structure(entry, self._structured_cfg)

    def _enter_structure(self, block: BasicBlock, cfg: StructuredCFG) -> None:
        """Recursively build structured blocks from the CFG."""
        struct = StructuredBlock(addr=block.addr, kind="sequence")

        for instr in block.instructions:
            if isinstance(instr, Branch):
                # Handle conditional branch
                if instr.condition:
                    struct.kind = "if"
                    struct.condition = instr.condition
                    struct.then_body.append(
                        StructuredBlock(
                            addr=instr.true_target.addr,
                            kind="then"
                        )
                    )
                    if instr.false_target:
                        struct.else_body.append(
                            StructuredBlock(
                                addr=instr.false_target.addr,
                                kind="else"
                            )
                        )
                else:
                    struct.kind = "jump"
                    struct.then_body.append(
                        StructuredBlock(
                            addr=instr.true_target.addr,
                            kind="unconditional"
                        )
                    )
            elif isinstance(instr, NoOp):
                struct = StructuredBlock(addr=block.addr, kind="noop")

        cfg.root = struct

    def get_dominated_blocks(self, header: BasicBlock) -> List[BasicBlock]:
        """Get all blocks dominated by a given block."""
        return self._region_map.get(header.addr, Region(header)).blocks

    def enter_loop_body(self) -> List[BasicBlock]:
        """Return the loop body (union of all loop bodies)."""
        return self.enter_loop_bodies()

    def enter_loop_bodies(self) -> List[BasicBlock]:
        """Return the loop body (union of all loop bodies)."""
        return list({
            b for loop in self.loops for b in loop.body
        })
