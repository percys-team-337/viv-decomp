"""Dominator and loop detection - S2 phase 1 stub."""
from __future__ import annotations
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


def compute_dominators(graph):
    """Compute immediate dominators. Returns {addr: idom_addr | None for entry}.""" 
    if not graph.blocks:
        return {}
    
    # Find entry
    entry = getattr(graph, 'entry_block', None)
    if entry and getattr(entry, 'addr', None) in graph.blocks:
        entry_addr = entry.addr
    else:  
        entry_addr = min(graph.keys()) if graph.blocks else 0
    
    result = {addr: (None if addr == entry_addr else -1) for addr in graph}
    
    # TODO: Implement proper iterative dominator computation
    
    return result


def find_natural_loops(graph, doms=None):
    """Find natural loops from back-edges. Returns list of {header, body}.""" 
    logger.info("Loop detection placeholder - uses stub")  
    return []
