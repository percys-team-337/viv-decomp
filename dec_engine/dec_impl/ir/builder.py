"""
IR builder - lifts Vivisect symbolik effects into our IR.

Pipeline
    ctx.getSymbolikGraph(funcva) -> HierGraph
        nodes : (va, {'symbolik_effects': [eff...]})
        edges  : einfo may contain 'symbolik_constraints'
    -> SymbolikAdaptor.convert(eff)        -> our Expression tree
    -> EffectsBuilder                     -> our IR instructions
    -> BasicBlock + BlockGraph
"""
from __future__ import annotations

import logging
from typing import Any, List, Dict, Optional

logger = logging.getLogger(__name__)

# Late imports to avoid circular deps at module level
# All concrete types imported lazily inside methods that need them.


def _bits_to_size(w: Any) -> Any:
    if w is None:
        return -1  # AUTO
    w = int(w)
    m = {1: 1, 2: 2, 4: 4, 8: 8}
    return m.get(w, -1)


def _bytes_to_enum_size(b: int) -> int:
    """Convert Vivisect byte width to Size enum value (bits)."""
    m = {1: 8, 2: 16, 4: 32, 8: 64}
    return m.get(b, -1)


def _bytes_to_size(b: Any) -> int:
    if b is None:
        return -1
    b = int(b)
    m = {1: 1, 2: 2, 4: 4, 8: 8}
    return m.get(b, -1)


# ── Expression adaptor ── ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─

class SymbolikAdaptor:
    """Vivisect symbolik Expression/symbol -> our IR Expression tree."""

    __slots__ = ()

    @classmethod
    def convert(cls, sym: Any, hint_sz: int = -1) -> Any:
        """Convert one Vivisect symbolik symbol to an IR expression."""
        if sym is None:
            return cls._const(0, hint_sz)
        cn = sym.__class__.__name__

        # primitive constant
        if cn == 'Const':
            val = int(sym.value) if hasattr(sym, 'value') else 0
            return cls._const(val, _bits_to_size(getattr(sym, 'width', 8)))

        # primitive variable
        if cn == 'Var':
            return cls._var(sym.name, _bits_to_size(getattr(sym, 'width', 8)))

        # binary/unary operators (class names like o_add, o_sub, ...)
        if cn.startswith('o_') and hasattr(sym, 'kids') and len(sym.kids) >= 1:
            sz = _bits_to_size(getattr(sym, 'width', 8))
            op = cls._op_type(cn)
            left = cls.convert(sym.kids[0], sz)
            if len(sym.kids) > 1:
                right = cls.convert(sym.kids[1], sz)
                return cls._binop(op, left, right, sz)
            return cls._unop(op, left, sz)

        # NOT (class name 'cnot')
        if cn == 'cnot' and hasattr(sym, 'kids') and sym.kids:
            operand = cls.convert(sym.kids[0])
            from dec_engine.dec_impl.ir.expression import OpType as _OpType
            return cls._unop(_OpType.NOT, operand, hint_sz)

        # Constraint (comparison operator, Operator subclass) — lives in vivisect.symboliks.common
        from vivisect.symboliks.common import Constraint
        if isinstance(sym, Constraint) and hasattr(sym, 'kids') and sym.kids:
            return cls.convert(sym.kids[0], hint_sz)

        # Mem - symbolic memory reference
        if cn == 'Mem' and hasattr(sym, 'kids') and len(sym.kids) >= 1:
            kids = sym.kids
            base = cls.convert(kids[0], hint_sz)
            off = cls.convert(kids[1], hint_sz) if len(kids) > 1 else cls._const(0, -1)
            scale = 1
            if len(kids) > 2:
                try:
                    scale = int(cls.convert(kids[2], hint_sz).value)
                except Exception:
                    pass
            return cls._memref(base, off, scale, hint_sz)

        # Call - symbolic function call
        if cn == 'Call' and hasattr(sym, 'funcsym'):
            callee = cls.convert(sym.funcsym)
            argsyms = getattr(sym, 'argsyms', None) or []
            args = [cls.convert(a) for a in argsyms]
            ret_sz = _bits_to_size(sym.width) if hasattr(sym, 'width') else hint_sz
            return cls._callexpr(callee, args, ret_sz)

        # SymbolikEffects (side-effects) - extract address expression
        from vivisect.symboliks.effects import (
            ReadMemory, WriteMemory, SetVariable,
            CallFunction, ConstrainPath,
        )
        if isinstance(sym, SetVariable):
            return cls.convert(sym.symobj, hint_sz)
        if isinstance(sym, ReadMemory):
            addr = cls.convert(sym.symaddr, hint_sz)
            return cls._memref(addr, cls._const(0, -1), 1, _bytes_to_size(sym.symsize.value))
        if isinstance(sym, WriteMemory):
            addr = cls.convert(sym.symaddr, hint_sz)
            return cls._memref(addr, cls._const(0, -1), 1, _bytes_to_size(sym.symsize.value))
        if isinstance(sym, CallFunction):
            callee = cls.convert(sym.funcsym)
            arg_s = getattr(sym, 'argsyms', None) or []
            args = [cls.convert(a) for a in arg_s]
            ret_sz = _bits_to_size(sym.width) if hasattr(sym, 'width') else -1
            return cls._callexpr(callee, args, ret_sz)
        if isinstance(sym, ConstrainPath):
            return cls.convert(sym.cons, hint_sz)
        if cn == 'DebugEffect':
            return cls._const(0, hint_sz)

        # fudge - last-ditch attribute sweep
        if hasattr(sym, 'value'):
            return cls._const(int(sym.value), _bits_to_size(getattr(sym, 'width', 8)))
        if hasattr(sym, 'name'):
            return cls._var(str(sym.name), _bits_to_size(getattr(sym, 'width', 8)))

        logger.debug("Unrecognized symbolik %s: %s", cn, sym)
        return cls._const(0, hint_sz)

    # ── IR constructor helpers ── ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─

    @classmethod
    def _make_expr(cls) -> Any:
        """Lazily import IR expression classes."""
        from dec_engine.dec_impl.ir.expression import (
            Const, Var, MemRef, BinOp, UnOp, CallExpr, OpType, Size,
        )
        return {
            'Const': Const, 'Var': Var, 'MemRef': MemRef,
            'BinOp': BinOp, 'UnOp': UnOp, 'CallExpr': CallExpr,
            'OpType': OpType, 'Size': Size,
        }

    @classmethod
    def _const(cls, value: int, sz: int = -1) -> Any:
        from dec_engine.dec_impl.ir.expression import Const, Size
        s = Size(sz * 8) if sz in (1, 2, 4, 8) else Size.AUTO
        return Const(value, size=s)

    @classmethod
    def _var(cls, name: str, sz: int = -1) -> Any:
        from dec_engine.dec_impl.ir.expression import Var, Size
        s = Size(sz * 8) if sz in (1, 2, 4, 8) else Size.AUTO
        return Var(name, size=s)

    @classmethod
    def _binop(cls, op: Any, left: Any, right: Any, sz: int = -1) -> Any:
        from dec_engine.dec_impl.ir.expression import BinOp, Size
        s = Size(sz * 8) if sz in (1, 2, 4, 8) else Size.AUTO
        return BinOp(op, left, right, size=s)

    @classmethod
    def _unop(cls, op: Any, operand: Any, sz: int = -1) -> Any:
        from dec_engine.dec_impl.ir.expression import UnOp, Size
        s = Size(sz * 8) if sz in (1, 2, 4, 8) else Size.AUTO
        return UnOp(op, operand, size=s)

    @classmethod
    def _memref(cls, base: Any, offset: Any, scale: int, sz: int = -1) -> Any:
        from dec_engine.dec_impl.ir.expression import MemRef, Size
        s = Size(sz * 8) if sz in (1, 2, 4, 8) else Size.AUTO
        return MemRef(base, offset, scale, s)

    @classmethod
    def _callexpr(cls, callee: Any, args: list, ret_sz: int = -1) -> Any:
        from dec_engine.dec_impl.ir.expression import CallExpr, Size
        s = Size(ret_sz * 8) if ret_sz in (1, 2, 4, 8) else Size.AUTO
        return CallExpr(callee, args, s)

    @classmethod
    def _op_type(cls, name: str) -> Any:
        from dec_engine.dec_impl.ir.expression import OpType
        mapping = {
            'o_add': OpType.ADD, 'o_sub': OpType.SUB, 'o_mul': OpType.MUL,
            'o_div': OpType.DIV, 'o_mod': OpType.MOD,
            'o_and': OpType.AND, 'o_or': OpType.OR, 'o_xor': OpType.XOR,
            'o_not': OpType.NOT,
            'o_lshift': OpType.SHL, 'o_rshift': OpType.SHR,
            'o_eq': OpType.EQ, 'o_ne': OpType.NE,
            'o_lt': OpType.LT, 'o_gt': OpType.GT,
            'o_le': OpType.LE, 'o_ge': OpType.GE,
            'o_pow': OpType.PTR_ADD, 'o_sextend': OpType.SIGN_EXTEND,
        }
        return mapping.get(name, OpType.MEMORY)


# ── Effects builder ── ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─

class EffectsBuilder:
    """3-pass IR builder: node effects -> edge constraints -> BlockGraph."""

    def __init__(self, funcva: int):
        self.funcva = funcva
        self.blocks: list = []
        self.addr_bb: dict[int, Any] = {}

    # ── public entry ──

    def build(self, graph: Any, func_name: str = "") -> Any:
        """Build BlockGraph from a Vivisect symbolik HierGraph."""
        from dec_engine.dec_impl.ir.block import BlockGraph
        from dec_engine.dec_impl.ir.block import BasicBlock

        instrs: dict[int, list] = {}

        # pass-1: nodes
        for va, ninfo in graph.getNodes():
            bb = BasicBlock(
                addr=va, label=f"bb_{va:x}",
                is_entry=(va == self.funcva),
            )
            self.blocks.append(bb)
            self.addr_bb[va] = bb
            effs = ninfo.get('symbolik_effects')
            if effs and hasattr(effs, '__iter__'):
                bl = self._process_effects(effs)
                if bl:
                    instrs[va] = bl

        # pass-2: edge wiring
        self._wire_edges(graph, instrs)

        # pass-3: assign instructions
        for bb in self.blocks:
            bb.instructions = instrs.get(bb.addr, [])

        # Determine entry block
        entry = next((b for b in self.blocks if b.addr == self.funcva), None)
        if entry is None and self.blocks:
            entry = min(self.blocks, key=lambda b: b.addr)
            entry.is_entry = True
            self.funcva = entry.addr

        return BlockGraph(
            entry_block=entry or self.blocks[0] if self.blocks else None,
            blocks={b.addr: b for b in self.blocks},
            name=func_name or f"func_{self.funcva:x}",
        )

    # ── effects processing ──

    def _process_effects(self, effs: list) -> list:
        """Convert a list of Vivisect SymbolikEffects to IR Instructions."""
        out = []

        for eff in effs:
            if eff is None:
                continue
            cn = eff.__class__.__name__

            # SetVariable: reg = value
            if cn == 'SetVariable':
                dst = self._var(eff.varname)
                src = SymbolikAdaptor.convert(eff.symobj)
                out.append(self._assignment(dst, src, getattr(eff, 'va', 0)))

            elif cn == 'WriteMemory':
                addr = SymbolikAdaptor.convert(eff.symaddr)
                dst = self._memref(addr)
                src = SymbolikAdaptor.convert(eff.symval)
                out.append(self._assignment(dst, src, getattr(eff, 'va', 0)))

            elif cn == 'ReadMemory':
                addr = SymbolikAdaptor.convert(eff.symaddr)
                tmp = self._var(f"$_t_{eff.va:x}")
                mem = self._memref(addr)
                out.append(self._assignment(tmp, mem, getattr(eff, 'va', 0)))

            elif cn == 'CallFunction':
                callee = SymbolikAdaptor.convert(eff.funcsym)
                args = [SymbolikAdaptor.convert(a) for a in (eff.argsyms or [])]
                out.append(self._call(callee, args, getattr(eff, 'va', 0)))

            elif cn == 'ConstrainPath':
                cond = SymbolikAdaptor.convert(eff.cons)
                tgt_va = int(eff.addrsym.value) if hasattr(eff.addrsym, 'value') else 0
                tgt_bb = self.addr_bb.get(tgt_va)
                if tgt_bb:
                    out.append(self._branch(cond, tgt_bb, getattr(eff, 'va', 0)))

            elif cn == 'DebugEffect':
                logger.debug("DebugEffect @ 0x%08x: %s", getattr(eff, 'va', 0),
                             getattr(eff, 'msg', ''))

            else:
                logger.warning("Unhandled effect %s @ 0x%08x", cn, getattr(eff, 'va', 0))

        return out

    # ── edge wiring ──

    def _wire_edges(self, graph: Any, instrs: dict) -> None:
        """Wire successors/predecessors and add Branch instructions from edge constraints.

        Visgraph HierGraph API:
          getNodes() -> iterator of (va, info_dict)
          getNode(va) -> (nid, info_tuple)
          getRefsFrom((va, nid, info)) -> iterator of einfo dicts with 'to_id', 'from_id'
          getRefsTo((va, nid, info)) -> iterator of einfo dicts
        """
        # Collect all nodes with their VAs and nids
        node_map: dict[int, int] = {}
        nodes_list: list[Any] = []
        for va, ninfo in graph.getNodes():
            node_info = graph.getNode(va)
            if node_info and len(node_info) >= 2:
                nid = node_info[0]
            else:
                nid = va
            node_map[va] = nid
            nodes_list.append((va, nid, ninfo))

        # Iterate outgoing edges from each node
        for src_va, src_nid, src_ninfo in nodes_list:
            src_bb = self.addr_bb.get(src_va)
            if not src_bb:
                continue

            try:
                # getRefsFrom expects a node tuple (va, nid, info)
                node_tuple = (src_va, src_nid, src_ninfo)
                refs = graph.getRefsFrom(node_tuple)
            except Exception:
                continue
            if not refs:
                continue

            for einfo in refs:
                # Extract target node id from edge info
                dst_nid = einfo.get('to_id')
                if dst_nid is None:
                    # einfo might be dict-like with different key
                    if hasattr(einfo, 'to_id'):
                        dst_nid = einfo.to_id
                    else:
                        # try unpacking if it's tuple-like
                        try:
                            dst_nid = tuple(einfo)[0] if einfo else None
                        except Exception:
                            continue

                if dst_nid is None:
                    continue

                # Resolve target VA: getRefsFrom may give us the nid OR the target va as 'to_addr'
                tgt_va = einfo.get('to_addr')
                if tgt_va is None and hasattr(einfo, 'to_addr'):
                    tgt_va = einfo.to_addr
                    
                if tgt_va is not None and tgt_va != 0:
                    pass  # use the to_addr directly
                else:
                    # look up target va from node_map by nid
                    tgt_va = None
                    for v, n in node_map.items():
                        if n == dst_nid:
                            tgt_va = v
                            break
                    if tgt_va is None:
                        # fallback: try getNode on dst_nid
                        node_res = graph.getNode(dst_nid) if isinstance(dst_nid, int) else None
                        if node_res and len(node_res) >= 2:
                            tgt_va = node_res[0] if isinstance(node_res[0], int) else None

                if tgt_va is None:
                    continue
                if src_va == tgt_va:
                    continue  # self-loop

                # Find target block by VA
                tgt_bb = self.addr_bb.get(tgt_va)
                if not tgt_bb:
                    # Also check if tgt_va maps to a VA in the graph
                    for v, n in node_map.items():
                        if n == dst_nid:
                            tgt_bb = self.addr_bb.get(v)
                            break

                if not tgt_bb:
                    tgt_bb = self.addr_bb.get(tgt_va)

                if not tgt_bb:
                    # create it if it exists in the graph but not in addr_bb
                    tgt_node = graph.getNode(dst_nid) if isinstance(dst_nid, int) else None
                    if tgt_node:
                        actual_va, actual_ninfo = tgt_node[0], tgt_node[1]
                        tgt_bb = self.addr_bb.get(actual_va)
                    if tgt_bb:
                        pass
                    else:
                        continue

                # wire graph links
                if tgt_bb not in src_bb.successors:
                    src_bb.successors.append(tgt_bb)
                if src_bb not in tgt_bb.predecessors:
                    tgt_bb.predecessors.append(src_bb)

                # Extract constraint from edge info
                cons_list = einfo.get('symbolik_constraints', None)
                if cons_list is None and hasattr(einfo, 'symbolik_constraints'):
                    cons_list = einfo.symbolik_constraints
                
                if cons_list and hasattr(cons_list, '__iter__') and cons_list is not True:
                    for cons in cons_list:
                        if cons is None:
                            continue
                        cond_expr = SymbolikAdaptor.convert(cons)
                        # resolve target from constraint's addrsym if available
                        if hasattr(cons, 'addrsym') and hasattr(cons.addrsym, 'value'):
                            resolved_va = int(cons.addrsym.value)
                            resolved_bb = self.addr_bb.get(resolved_va) or tgt_bb
                        else:
                            resolved_bb = tgt_bb
                        instrs[src_va] = list(instrs.get(src_va, [])) + [
                            self._branch(cond_expr, resolved_bb, src_va),
                        ]
                else:
                    # Unconditional jump
                    instrs[src_va] = list(instrs.get(src_va, [])) + [
                        self._branch(None, tgt_bb, src_va),
                    ]

    # ── IR construction helpers ──

    def _var(self, name: str, size: int = -1) -> Any:
        from dec_engine.dec_impl.ir.expression import Var, Size
        s = Size(size) if size in (1, 2, 4, 8) else Size.AUTO
        return Var(name, size=s)

    def _const(self, value: int, size: int = -1) -> Any:
        from dec_engine.dec_impl.ir.expression import Const, Size
        s = Size(size) if size in (1, 2, 4, 8) else Size.AUTO
        return Const(value, size=s)

    def _memref(self, base: Any, offset: Any = None) -> Any:
        from dec_engine.dec_impl.ir.expression import MemRef, Size
        if offset is None:
            offset = self._const(0)
        return MemRef(base, offset, 1, Size.AUTO)

    def _assignment(self, dst: Any, src: Any, addr: int) -> Any:
        from dec_engine.dec_impl.ir.effects import Assignment
        return Assignment(destination=dst, source=src, address=addr)

    def _call(self, callee: Any, args: list, addr: int) -> Any:
        from dec_engine.dec_impl.ir.effects import Call
        return Call(callee=callee, args=args, address=addr)

    def _branch(self, condition: Any, true_target: Any, addr: int) -> Any:
        from dec_engine.dec_impl.ir.effects import Branch
        return Branch(condition=condition, true_target=true_target, address=addr)
