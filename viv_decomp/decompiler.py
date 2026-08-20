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

from dec_engine.dec_impl.ir.block import BasicBlock, BlockGraph
from dec_engine.dec_impl.ssa.construct import SsaState, SsaTransform
from dec_engine.dec_impl.type_inference.analyze import TypeAnalyzer, TypeEnvironment
from dec_engine.dec_impl.output.pretty import PrettyPrinter

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
        """Build a BlockGraph from the Vivisect workspace using the symbolik graph."""
        if not self.workspace_loaded:
            self.load()
        vw = self.vw
        assert vw is not None, "Vivisect workspace not loaded"

        # Ensure the function has a symbolik graph (analyzed)
        if funcva not in vw.getFunctions():
            # Try to discover it via analysis
            try:
                vw.analyzeFunction(funcva)
            except Exception:
                pass

        if funcva not in vw.getFunctions():
            # No function — build a minimal block graph
            entry = BasicBlock(
                addr=funcva, is_entry=True, label=f"bb_{funcva:x}" if funcva else "bb_entry",
            )
            fallback_name = f"func_{funcva:x}"
            return BlockGraph(
                entry_block=entry, blocks={funcva: entry}, name=fallback_name,
            )

        # Get symbolik graph from architecture-specific analysis context
        from vivisect.symboliks.archs.amd64 import Amd64SymbolikAnalysisContext
        from dec_engine.dec_impl.ir.builder import EffectsBuilder

        ctx = Amd64SymbolikAnalysisContext(vw)
        sgraph = ctx.getSymbolikGraph(funcva)

        # Validate we have symbolik effects to process
        has_effects = False
        for va_node, ninfo in sgraph.getNodes():
            if isinstance(ninfo, dict) and 'symbolik_effects' in ninfo:
                if ninfo['symbolik_effects']:
                    has_effects = True
                    break

        builder = EffectsBuilder(funcva)
        label = name or (vw.getName(funcva) if vw.getName(funcva) else f"func_{funcva:x}")

        if has_effects:
            return builder.build(sgraph, func_name=label)
        else:
            builder_empty = EffectsBuilder(funcva)
            # Build with empty graph (no symbolik effects)
            blocks_dict = {}
            entry_block = BasicBlock(
                addr=funcva, is_entry=True, label=f"func_{funcva:x}"
            )
            blocks_dict[funcva] = entry_block
            return BlockGraph(
                entry_block=entry_block, blocks=blocks_dict, name=label,
            )


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
            # 1. Build graph (this triggers graph_builder.load() → vw.analyze())
            self.graph = self.graph_builder.get_graph(funcva, name)
            logger.debug(f"Built BlockGraph: {len(self.graph.blocks)} blocks")
            
            # S2 Step: Collapse unconditional forward jumps (pre-SSA simplification)
            from dec_engine.dec_impl.structuring import collapse_unconditional_jumps
            old_block_count = len(self.graph.blocks)
            self.graph = collapse_unconditional_jumps(self.graph)
            if old_block_count != len(self.graph.blocks):
                logger.debug("Collapse pass: %d -> %d blocks", old_block_count, len(self.graph.blocks))
            
            # 2. Run SSA construction
            if self.do_ssa:
                self.ssa_state = SsaState()
                ssa = SsaTransform(self.graph)
                self.graph = ssa.analyze_graph()  # returns the graph
                logger.debug("SSA construction complete")
            
            # 3. Run type inference
            if self.analyze_types:
                analyzer = TypeAnalyzer()
                analyzer.analyze_graph(self.graph)  # propagate types over the CFG
                self.type_env = analyzer.env
                logger.debug("Type inference complete")
            
            # 4. Format output — pass workspace for call target resolution via vw.getName()
            pp = PrettyPrinter(
                func_name=name or f"func_{funcva:x}",
                graph=self.graph,
                ssa=self.ssa_state or SsaState(),
                workspace=self.graph_builder.vw if hasattr(self.graph_builder, 'vw') else None,
            )
            c_code = pp.generate()
            
            # Build structured JSON snapshot
            json_data = {
                "func_name": name or f"func_{funcva:x}",
                "func_address": f"0x{funcva:x}",
                "num_blocks": len(self.graph.blocks) if self.graph else 0,
                "ssa_rounds": self.ssa_state._rounds if self.ssa_state and hasattr(self.ssa_state, "_rounds") else 0,
                "type_env": {
                    "num_types": len(self.type_env.types) if self.type_env and hasattr(self.type_env, "types") else 0,
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
