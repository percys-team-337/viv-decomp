"""Dominators and natural loops for S2 structured control flow."""


def compute_dominators(graph):
    """Compute immediate dominator map {addr -> parent_addr or None}.
    
    Uses iterative dataflow algorithm:
    - Entry dominated by itself only
    - Other blocks start with all blocks as dominators
    - Iteratively narrow via predecessor intersection until fixed point
    """
    if not graph.blocks:
        return {}

    all_addrs = sorted(graph.keys())
    if not all_addrs:
        return {}

    # Find entry block
    entry_blk = getattr(graph, 'entry_block', None)
    entry_addr = None
    if (entry_blk and hasattr(entry_blk, 'addr') and 
            entry_blk.addr in graph.blocks):
        entry_addr = entry_blk.addr
    else:
        for addr, blk in sorted(graph.items()):
            if getattr(blk, 'is_entry', False):
                entry_addr = addr
                break
    if not entry_addr:
        entry_addr = min(all_addrs)

    # Initialize dominance sets
    doms = {}
    for a in all_addrs:
        doms[a] = {a} if a == entry_addr else set(all_addrs)

    # Iterate until fixed point (Cooper's algorithm)
    changed = True
    iters = 0
    max_it = len(all_addrs) * len(all_addrs) + 10

    while changed and iters < max_it:
        changed = False
        iters += 1
        for addr in all_addrs:
            if addr == entry_addr:
                continue

            blk = graph[addr]
            preds = [p.addr for p in getattr(blk, 'predecessors', [])
                     if hasattr(p, 'addr') and p.addr in doms 
                     and doms[p.addr]]
            if not preds:
                continue

            # Intersect all predecessor dominator sets
            common = set(doms[preds[0]])
            for p in preds[1:]:
                common &= doms.get(p, all_addrs)

            new_d = common | {addr}  # Every block dominates itself
            if new_d != doms[addr]:
                doms[addr] = new_d
                changed = True

    # Compute immediate dominators (closest strict dominator)
    idoms = {}
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
            idoms[addr] = min(strict_doms, 
                             key=lambda d: len(doms.get(d, {d})))

    return idoms


def detect_back_edges(graph, idoms):
    """Find back-edges: src->dst where dst dominates src.
    
    A back-edge indicates a potential loop in the CFG."""
    if not idoms or not graph.blocks:
        return []

    # Build full dominator sets from idom map
    all_keys = list(graph.keys())
    dom_sets = {}
    
    for addr in all_keys:
        ds = {addr}
        cur = idoms.get(addr) if addr in idoms else None
        while (cur is not None and cur != -1 and 
               cur in graph.blocks):
            ds.add(cur)
            nxt = idoms.get(cur) if cur in idoms else None
            if nxt == cur or nxt is None:
                break
            cur = nxt
        dom_sets[addr] = ds

    back_edges = []
    for addr, blk in graph.blocks.items():
        succ_list = getattr(blk, 'successors', [])
        dsts = [s.addr for s in succ_list
                if hasattr(s, 'addr') and s.addr in graph.blocks]
        
        for dst in dsts:
            if (dst != addr and 
                    dst in dom_sets.get(addr, set())):
                back_edges.append((addr, dst))

    return back_edges


def find_natural_loops(graph, idoms=None):
    """Find natural loops from dominator tree analysis.
    
    Returns list of dicts with keys: header, body_addrs, back_edges, size"""
    if not graph.blocks:
        return []

    # Compute dominators and detect back-edges  
    if idoms is None:
        cur_idms = compute_dominators(graph)
    else:
        cur_idms = idoms

    all_back_edges = detect_back_edges(graph, cur_idms)
    
    if not all_back_edges:
        return []

    # Group back-edges by loop header (the destination of the back-edge)
    grouped = {}
    for src_addr, dst_addr in all_back_edges:
        hdr_key = dst_addr
        if hdr_key not in grouped:
            grouped[hdr_key] = {'back_edges': [], 'body_addrs': {hdr_key}}
        grouped[hdr_key]['back_edges'].append((src_addr, dst_addr))

    result_list = []
    processed_headers = set()

    for loop_header in grouped:
        if loop_header in processed_headers:
            continue
        
        processed_headers.add(loop_header)
        
        # Compute loop body: walk predecessors from each back-edge source
        # until we reach the header (but don't include the header itself 
        # since it's not counted as part of the body, only a reachable node)
        body_nodes = set()
        all_back_edge_srcs = grouped[loop_header]['back_edges']
        
        for src_addr, _dst_addr in all_back_edge_srcs:
            walk_stack = [src_addr]
            visited_walk = set()
            
            while walk_stack:
                node_addr = walk_stack.pop()
                
                if not isinstance(node_addr, int) or \
                        node_addr not in graph.blocks:
                    continue
                
                # Skip the header to avoid infinite cycles
                if node_addr == loop_header:
                    body_nodes.add(loop_header)
                    continue
                
                if node_addr in visited_walk:
                    continue
                    
                visited_walk.add(node_addr)
                body_nodes.add(node_addr)  
                
                curr_blk = graph[node_addr]
                preds = getattr(curr_blk, 'predecessors', [])
                
                for pred_blk in preds:
                    pred_a = getattr(pred_blk, 'addr', None)
                    if pred_a is None or pred_a == loop_header:
                        continue
                    if pred_a not in visited_walk:
                        walk_stack.append(pred_a)

        grouped[loop_header]['body_addrs'].update(body_nodes)
        
        result_list.append({
            'header': loop_header,
            'body_addrs': grouped[loop_header]['body_addrs'],
            'back_edges': grouped[loop_header]['back_edges'],
            'size': len(grouped[loop_header]['body_addrs']),
        })

    return result_list
