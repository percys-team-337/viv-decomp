"""
Build IR from Vivisect's symboliks effects for a given function.
This is the entry point between Vivisect's analysis and our decompiler.

Pipeline:
  VivWorkspace -> getSymbolikAnalysisContext(fva)
    -> getSymbolikGraph(fva) [returns list of SymbolikEffect per opcode]
    -> convert to BlockGraph + IR instructions
"""
import logging
from typing import List, Dict, Optional
from vivisect.dec_impl.ir.expression import (
    Expression,
    Const,
    Var,
    MemRef,
    BinOp,
    PhiNode,
    CallExpr,
    UnOp,
    OpType,
    Size,
    build_mem_ref,
    sym_to_expr,
)
from vivisect.dec_impl.ir.instruction import (
    Assignment,
    Branch,
    Call,
    PhiInstruction,
    NoOp,
)
from vivisect.dec_impl.ir.block import BasicBlock, BlockGraph

logger = logging.getLogger(__name__)


class SymbolikAdaptor:
    """Convert Vivisect symbolik objects to our IR Expression tree."""

    @staticmethod
    def convert(effect, target_size: Optional[Size] = None) -> Expression:
        """Convert a symbolik symbol to expression tree."""
        if hasattr(effect, 'value'):
            return Const(effect.value, size=target_size)
        elif hasattr(effect, 'name') and not hasattr(effect, 'base'):
            return Var(effect.name, size=target_size)
        elif hasattr(effect, 'base'):
            # Memory reference
            base = SymbolikAdaptor.convert(effect.base, target_size)
            offset = SymbolikAdaptor.convert(effect.offset) if hasattr(effect, 'offset') else Const(0)
            scale = getattr(effect, 'scale', 1)
            return MemRef(base, offset, scale, target_size)
        elif hasattr(effect, 'operator'):
            # Binary or unary operation
            op = effect.operator
            left = SymbolikAdaptor.convert(effect.left, target_size)
            right = SymbolikAdaptor.convert(effect.right, target_size) if hasattr(effect, 'right') else None
            op_type = SymbolikAdaptor._map_op(op)
            if right:
                return BinOp(op_type, left, right, target_size)
            else:
                return UnOp(op_type, left, target_size)
        elif hasattr(effect, 'callee'):
            # Function call
            callee = SymbolikAdaptor.convert(effect.callee)
            args = [SymbolikAdaptor.convert(a) for a in getattr(effect, 'args', [])]
            return CallExpr(callee, args, target_size)
        else:
            return Const(0, size=target_size)

    @staticmethod
    def _map_op(symbolik_op) -> OpType:
        """Map symbolik operator to OpType."""
        op_map = {
            'o_add': OpType.ADD,
            'o_sub': OpType.SUB,
            'o_mul': OpType.MUL,
            'o_div': OpType.DIV,
            'o_mod': OpType.MOD,
            'o_and': OpType.AND,
            'o_or': OpType.OR,
            'o_xor': OpType.XOR,
            'o_not': OpType.NOT,
            'o_shl': OpType.SHL,
            'o_shr': OpType.SHR,
            'o_sar': OpType.SAR,
            'o_eq': OpType.EQ,
            'o_ne': OpType.NE,
            'o_lt': OpType.LT,
            'o_gt': OpType.GT,
            'o_le': OpType.LE,
            'o_ge': OpType.GE,
            'o_call': OpType.CALL,
            'o_load': OpType.LOAD,
            'o_store': OpType.STORE,
        }
        return op_map.get(symbolik_op, OpType.MEMORY)


class EffectsBuilder:
    """Convert Vivisect symboliks effects into IR instructions + basic blocks."""

    def __init__(self, vw):
        self.vw = vw
        self._temp_counter = 0
        self._symbolik_ctx = None
        self._block_map: Dict[int, BasicBlock] = {}
        self._var_map: Dict[str, Var] = {}

    def _get_temp_var(self, size=Size.AUTO) -> Var:
        """Allocate a new temporary variable for IR."""
        name = f"$t{self._temp_counter}"
        self._temp_counter += 1
        return Var(name, size)

    def _ensure_block(self, addr: int) -> BasicBlock:
        """Get or create a basic block for the given address."""
        if addr in self._block_map:
            return self._block_map[addr]
        bb = BasicBlock(addr, [])
        self._block_map[addr] = bb
        return bb

    def _get_effective_size(self, funcva: int, va: int) -> Size:
        """Determine the effective register width at a given address."""
        try:
            from vivisect.archinfo import addrSize
            sz = addrSize(self.vw)
            return Size.SIZE_64 if sz == 8 else Size.SIZE_32
        except:
            return Size.AUTO

    def build_from_function(self, funcva: int) -> BlockGraph:
        """Main entry: parse a function's symboliks effects into a BlockGraph."""
        self._symbolik_ctx = self.vw.getSymbolikAnalysisContext()
        if not self._symbolik_ctx:
            raise RuntimeError(f"No symbolik context for function @ 0x{funcva:x}")

        func_blocks = self.vw.getFunctionBlocks(funcva)
        if not func_blocks:
            raise RuntimeError(f"No blocks found for function @ 0x{funcva:x}")

        # Create the function/entry block
        entry_block = self._ensure_block(funcva)
        entry_block.is_entry = True
        entry_block.label = f"func_{funcva:x}"

        # Parse symboliks effects for this function
        effects = self._symbolik_ctx.getSymbolikGraph(funcva)
        if not effects:
            logger.warning(f"No symboliks effects for function @ 0x{funcva:x}")
            return BlockGraph(entry_block, name=f"func_{funcva:x}")

        # Group effects by block, build CFG
        block_order = self._group_by_block(funcva, effects)
        entry_block.instructions = self._process_effects(funcva, effects)

        # Build CFG edges from symbolik path constraints
        self._build_cfg_edges(funcva)

        graph = BlockGraph(entry_block, name=f"func_{funcva:x}")
        graph.blocks = self._block_map

        return graph

    def _group_by_block(self, funcva: int, effects) -> List[int]:
        """Group effects by their address/block."""
        return []

    def _process_effects(self, funcva: int, effects) -> List[Assignment]:
        """Convert symboliks effects to IR instructions."""
        instrs = []
        size = self._get_effective_size(funcva, 0)
        
        for effect in effects:
            if hasattr(effect, 'write'):
                # Write effect: assignment
                dst = Var(effect.write) if isinstance(effect.write, str) else effect.write
                src = SymbolikAdaptor.convert(effect.read, size) if hasattr(effect, 'read') else Const(0, size)
                instr = Assignment(
                    destination=dst,
                    source=src,
                    mnemonic=getattr(effect, 'mnemonic', ''),
                    address=getattr(effect, 'addr', 0),
                )
                instrs.append(instr)
            elif hasattr(effect, 'addr') and hasattr(effect, 'branch'):
                # Branch effect
                pass  # Handle branch constraints
            elif hasattr(effect, 'call'):
                # Call effect
                pass  # Handle call constraint
            else:
                # Unknown effect
                pass
        
        return instrs

    def _build_cfg_edges(self, funcva: int):
        """Build CFG edges from symbolik constraints and xrefs."""
        # Use Vivisect's existing xref infrastructure
        from vivisect.tools.graphutil import buildFunctionGraph
        graph = buildFunctionGraph(self.vw, funcva)
        if not graph:
            return
        
        # Map visgraph nodes to our basic blocks
        for node in graph.nodes():
            if hasattr(node, 'cbva') or hasattr(node, 'val'):
                addr = getattr(node, 'val', node) if hasattr(node, 'val') else node
                bb = self._ensure_block(addr)
                bb.label = f"bb_{addr:x}"
                
                # Add successors from visgraph
                succs = list(graph.edges(node))
                for edge in succs:
                    if hasattr(edge, 'dst'):
                        dst_addr = edge.dst if hasattr(edge, 'dst') else edge
                        target = self._ensure_block(dst_addr)
                        if target not in bb.successors:
                            bb.successors.append(target)
                    elif hasattr(edge, 'val'):
                        dst_addr = edge.val if hasattr(edge, 'val') else edge
                        target = self._ensure_block(dst_addr)
                        if target not in bb.successors:
                            bb.successors.append(target)


def decompile_function(vw, funcva: int) -> BlockGraph:
    """Top-level function to decompile a single function from a Vivisect workspace."""
    builder = EffectsBuilder(vw)
    return builder.build_from_function(funcva)
