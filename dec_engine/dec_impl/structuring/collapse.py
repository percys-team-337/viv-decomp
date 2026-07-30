"""
Structuring pass: merge basic blocks connected by unconditional forward jumps.

This simplifies the CFG before structured control flow analysis.
Pattern: Block A ends with "goto B" where B has only one predecessor (A) → merge A+B
"""
from __future__ import annotations

from typing import List, Dict, Set, Optional
import logging

logger = logging.getLogger(__name__)


def collapse_unconditional_jumps(graph):
    """Merge basic blocks connected by unconditional forward-only jumps.
    
    Pattern: If block A has single successor B and ends with an unconditional branch to B,
             then merge A instructions into B and remove the jump instruction.
    
    Args:
        graph: BlockGraph object
        
    Returns:
        Modified graph in-place (blocks dict updated, entry_block preserved)
    """
    from dec_engine.dec_impl.ir.block import BasicBlock, BlockGraph
    
    changed = True
    iterations = 0
    max_iterations = len(graph.blocks) * 2  # Safety limit
    
    while changed and iterations < max_iterations:
        changed = False
        iterations += 1
        
        for addr, block in list(graph.blocks.items()):
            if not should_collapse_block(block):
                continue
                
            # Collapse this block into its successor
            succ = block.successors[0] if block.successors else None
            if succ is None:
                continue
                
            changed = True
            
            logger.debug("C collapsing @ 0x%x -> 0x%x", block.addr, succ.addr)
            
            # Move instructions from A to B (preserve order)
            succ.instructions = list(block.instructions) + list(succ.instructions)
            
            # Update dominator/pred/succ relationships
            for pred in block.predecessors:
                if block in pred.successors:
                    idx = pred.successors.index(block)
                    pred.successors[idx] = succ
                succ.add_predecessor(pred)
            
            # Remove the old block from graph (after moving instructions)
            if block.addr in graph.blocks:
                del graph.blocks[block.addr]

    logger.info("Collapse pass: %d iterations", iterations)
    
    return graph
    
def should_collapse_block(block):
    """Determine if a block should be merged with its successor.
    
    Pattern: If block A has single successor B and ends with an unconditional branch to B,
             then merge A instructions into B (removing the jump instruction).
    
    Conditions for collapsing A → B:
    1. Block A has exactly one successor (B)
    2. Last instruction is an unconditional branch to B  
    3. A becomes part of B, reducing total block count
    
    Returns True if collapsing makes sense, False otherwise.
    """
    from dec_engine.dec_impl.ir.effects import Branch
    
    # Must have exactly one successor
    if not block.successors or len(block.successors) != 1:
        return False
        
    succ = block.successors[0]
    
    # Check: does last instruction jump directly to our successor?
    if not block.instructions:
        return False
    
    last_instr = block.instructions[-1]
    
    # Unconditional branch means Branch with condition=None or true_target == succ
    if isinstance(last_instr, Branch):
        if last_instr.condition is None:  # Unconditional jump to succ
            return True
    
    return False
