"""
Core decompiler engine — ties the graph builder → SSA → type inference → output pipeline together.

The VivisectDecompiler class is the orchestration layer:
  1. Load binary / get graph source
  2. Build BlockGraph via a GraphBuilder plugin
  3. Run analysis passes (SSA, structural, type inference)
  4. Format output

Graph builders are pluggable: a GraphBuilder is any class that implements
  def build(self, graph): BlockGraph
    Takes a raw graph dict/obj and returns a BlockGraph ready for analysis.
"""
from __future__ import annotations

import logging
import sys
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Any

# Ensure the project root is on sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from vivisect.dec_impl.ir.block import BasicBlock, BlockGraph
from vivisect.dec_impl.ssa.construct import SsaState, SsaTransform
from vivisect.dec_impl.type_inference.analyze import TypeAnalyzer, TypeEnvironment
from vivisect.dec_impl.output.pretty import PrettyPrinter

logger = logging.getLogger("viv-decomp")


# ── Plugin interface ──

class GraphBuilder(ABC):
    """Abstract base class for graph source plugins.

    Subclasses are initialized with a binary path and must implement
    ``get_graph(funcva) -> BlockGraph`` which returns the CFG for a function.
    """

    def __init__(self, binary_path: str):
        self.binary_path = binary_path

    @abstractmethod
    def get_graph(self, funcva: int, name: str = "") -> BlockGraph:
        """Return a BlockGraph for the function at the given virtual address."""
        ...

    def load(self) -> None:
        """Optional hook called once before any ``get_graph`` calls."""
        pass


# ── Vivisect graph builder ──

class VivisectGraphBuilder(GraphBuilder):
    """Builds BlockGraph from an existing Vivisect workspace."""

    def __init__(self, binary_path: str):
        super().__init__(binary_path)
        self.vw = None
        self.workspace_loaded = False

    def load(self) -> None:
        """Import Vivisect, load the binary workspace."""
        if self.workspace_loaded:
            return
        try:
            import vivisect  # noqa: F811
        except ImportError:
            raise RuntimeError(
                "vivisect package is not installed. Install it to use the "
                "Vivisect graph builder.\n"
                "  pip install vivisect\n"
                "Or use --graph raw with manual graph construction."
            )
        try:
            vw = vivisect.VivWorkspace()
            vw.loadFromFile(self.binary_path)
            vw.analyze()
            self.vw = vw
            self.workspace_loaded = True
            logger.info(f"Loaded Vivisect workspace: {self.binary_path}")
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load {self.binary_path} in Vivisect: {exc}"
            ) from exc

    def get_graph(self, funcva: int, name: str = "") -> BlockGraph:
        """Build a BlockGraph from the Vivisect workspace."""
        if not self.workspace_loaded:
            self.load()
        vw = self.vw
        assert vw is not None, "Vivisect workspace not loaded"

        # Build block graph from Vivisect's function analysis
        blocks: dict[int, BasicBlock] = {}

        # Get function blocks
        func_blocks = vw.getFunctionBlocks(funcva)
        if not func_blocks:
            # Fallback: build from raw disassembly
            func_blocks = {funcva: vw.getMeta("FunctionBlock", funcva)}

        # Build blocks from Vivisect's instruction analysis
        if func_blocks is None:
            # No function at this address — try to extract one
            func_blocks = {funcva: True}

        # Gather all blocks by traversing xrefs
        visited = set()
        stack = [funcva]
        while stack:
            addr = stack.pop()
            if addr in visited:
                continue
            visited.add(addr)

            # Create or get block
            block = blocks.get(addr)
            if block is None:
                block = BasicBlock(
                    addr=addr,
                    is_entry=(addr == funcva),
                    label=f"bb_{addr:x}",
                )
                blocks[addr] = block

            # Get successors from Vivisect
            succs = vw.getXrefsDrw(addr) or vw.getXrefsTo(addr) or []
            for (_, dst_addr, _) in succs:
                if dst_addr not in blocks:
                    blocks[dst_addr] = BasicBlock(
                        addr=dst_addr,
                        label=f"bb_{dst_addr:x}",
                    )
                    stack.append(dst_addr)
                block.successors.append(blocks[dst_addr])
                blocks[dst_addr].predecessors.append(block)

        if not blocks:
            return BlockGraph(
                entry_block=BasicBlock(
                    addr=funcva,
                    is_entry=True,
                    label=f"bb_{funcva:x}",
                ),
                blocks={},
                name=name or f"func_{funcva:x}",
            )

        entry_block = blocks.get(funcva, blocks[funcva])

        # Collect all disassembly for this function
        func_size = 0
        try:
            func_size = vw.getFunctionSize(funcva) or 0x100  # default fallback
        except Exception:
            func_size = 0x100

        all_vw_insts = vw.getFunctions()
        for addr_in_func in range(funcva, funcva + func_size):
            try:
                inst = vw.parseDisasm(addr_in_func)
                if inst is not None:
                    pass  # placeholder for instruction parsing
            except Exception:
                break

        graph = BlockGraph(
            entry_block=entry_block,
            blocks=blocks,
            name=name or f"func_{funcva:x}",
        )
        return graph


# ── Raw (stub) graph builder for testing ──

class RawGraphBuilder(GraphBuilder):
    """Graph builder that creates a minimal test graph from scratch.

    Useful for testing the pipeline without binaries.
    """

    def get_graph(self, funcva: int, name: str = "") -> BlockGraph:
        """Return a simple test graph with two blocks."""
        bb1 = BasicBlock(addr=funcva, is_entry=True,
                         label=f"{name}_entry" if name else f"entry_{funcva:x}")
        bb2 = BasicBlock(addr=funcva + 0x10,
                         label=f"{name}_body" if name else f"body_{funcva + 0x10:x}")
        bb1.successors = [bb2]
        bb2.predecessors = [bb1]
        return BlockGraph(
            entry_block=bb1,
            blocks={funcva: bb1, funcva + 0x10: bb2},
            name=name or f"func_{funcva:x}",
        )


# ── Analysis result ──

@dataclass
class DecompOutput:
    """Container for decompiler output."""
    text: str
    json: dict  # Structured data (graph, ssa info, types)
    success: bool
    error: Optional[str] = None


# ── Main decompiler class ──

class VivisectDecompiler:
    """Orchestrates the full decompiler pipeline.

    Usage:
        decomp = VivisectDecompiler(binary_path="/bin/ls")
        output = decomp.decompile_address(0x401000)
        print(output.text)
    """

    BUILDER_MAP = {
        "vivisect": VivisectGraphBuilder,
        "ghidra": VivisectGraphBuilder,  # Stub for now
        "raw": RawGraphBuilder,
    }

    def __init__(
        self,
        binary_path: str,
        graph_source: str = "vivisect",
        do_ssa: bool = True,
        analyze_types: bool = True,
    ):
        self.binary_path = binary_path
        self.do_ssa = do_ssa
        self.analyze_types = analyze_types

        builder_cls = self.BUILDER_MAP.get(graph_source, RawGraphBuilder)
        self.graph_builder = builder_cls(binary_path)

        # Analysis state
        self.graph: Optional[BlockGraph] = None
        self.ssa_state: Optional[SsaState] = None
        self.type_env: Optional[TypeEnvironment] = None

    def decompile_address(self, funcva: int, name: str = "") -> Optional[dict[str, str]]:
        """Run the full decompiler pipeline on a single function."""
        result = DecompOutput(text="", json={}, success=False)
        try:
            # 1. Build graph
            self.graph = self.graph_builder.get_graph(funcva, name)
            logger.debug(f"Built BlockGraph: {len(self.graph.blocks)} blocks")

            # 2. Run SSA construction
            if self.do_ssa:
                self.ssa_state = SsaState()
                ssa = SsaTransform(self.graph)
                self.graph = ssa.analyze_graph()  # returns the graph
                logger.debug("SSA construction complete")

            # 3. Run type inference
            if self.analyze_types:
                self.type_env = TypeAnalyzer().analyze()
                logger.debug("Type inference complete")

            # 4. Format output
            pp = PrettyPrinter(
                func_name=name or f"func_{funcva:x}",
                graph=self.graph,
                ssa=self.ssa_state or SsaState(),
            )
            c_code = pp.generate()

            # Build structured JSON snapshot
            json_data = {
                "func_name": name or f"func_{funcva:x}",
                "func_address": f"0x{funcva:x}",
                "num_blocks": len(self.graph.blocks),
                "ssa_rounds": getattr(self.ssa_state, "_rounds", 0) if self.ssa_state else 0,
                "type_env": {
                    "num_types": len(self.type_env.types) if self.type_env else 0,
                } if self.type_env else {},
            }

            result = DecompOutput(
                text=c_code,
                json=json_data,
                success=True,
            )
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            logger.error(f"Pipeline failed: {result.error}")
            result.text = f"// Error: {result.error}"
            result.json = {"success": False, "error": result.error}

        return result  # type: ignore


# ── Convenience function ──

def decompile(binary_path: str, funcva: int, name: str = "") -> str:
    """Quick decompile one function to C code string."""
    decomp = VivisectDecompiler(binary_path)
    out = decomp.decompile_address(funcva, name)
    assert out is not None
    return out.text
