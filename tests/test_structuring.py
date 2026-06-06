"""
Tests for ir/structuring/struct.py — Region, Loop, StructuredBlock, StructuredCFG, StructuringPass.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from vivisect.dec_impl.structuring.struct import (
    Region,
    Loop,
    StructuredBlock,
    StructuredCFG,
    StructuringPass,
)
from vivisect.dec_impl.ir.block import BasicBlock, BlockGraph
from vivisect.dec_impl.ir.expression import Const, BinOp, Size, OpType


# ── Fixtures ──

@pytest.fixture
def entry_block():
    return BasicBlock(addr=0x1000, is_entry=True)


@pytest.fixture
def bb0x2000():
    return BasicBlock(addr=0x2000)


@pytest.fixture
def simple_graph(entry_block, bb0x2000):
    entry_block.successors = [bb0x2000]
    bb0x2000.predecessors = [entry_block]
    return BlockGraph(entry_block=entry_block, blocks={0x1000: entry_block, 0x2000: bb0x2000})


# ── Region ──

class TestRegion:
    def test_construct(self, entry_block):
        r = Region(header=entry_block)
        assert r.header is entry_block
        assert r.blocks == [entry_block]
        assert r.children == []

    def test_size_single(self, entry_block):
        r = Region(header=entry_block)
        assert r.size == 1

    def test_size_multiple(self, entry_block, bb0x2000):
        r = Region(header=entry_block)
        r.blocks.append(bb0x2000)
        assert r.size == 2

    def test_size_empty(self, entry_block):
        r = Region(header=entry_block)
        r.blocks = []
        assert r.size == 0


# ── Loop ──

class TestLoop:
    def test_construct_header_only(self, entry_block):
        loop = Loop(header=entry_block)
        assert loop.header is entry_block
        assert loop.back_edges == []
        assert loop.body == []
        assert loop.body_set == set()
        assert loop.is_nested is False

    def test_construct_with_back_edge(self, entry_block, bb0x2000):
        loop = Loop(header=entry_block, back_edge_src=bb0x2000)
        assert len(loop.back_edges) == 1

    def test_add_back_edge_append(self, entry_block, bb0x2000):
        loop = Loop(header=entry_block)
        loop.add_back_edge(bb0x2000)
        loop.add_back_edge(bb0x2000)  # append, not dedupe
        assert len(loop.back_edges) == 2

    def test_add_body_dedup(self, entry_block, bb0x2000):
        loop = Loop(header=entry_block)
        loop.add_body(bb0x2000)
        loop.add_body(bb0x2000)
        assert len(loop.body) == 1
        assert len(loop.body_set) == 1

    def test_is_nested_true(self, entry_block):
        loop = Loop(header=entry_block)
        loop.add_body(BasicBlock(addr=0x5000))
        loop.add_body(BasicBlock(addr=0x6000))
        assert loop.is_nested is True

    def test_is_nested_false(self, entry_block):
        loop = Loop(header=entry_block)
        assert loop.is_nested is False

    def test_repr(self, entry_block):
        loop = Loop(header=entry_block)
        r = repr(loop)
        assert "Loop(header" in r


# ── StructuredBlock ──

class TestStructuredBlock:
    def test_construct_defaults(self):
        sb = StructuredBlock(addr=0x1000, kind="if")
        assert sb.addr == 0x1000
        assert sb.kind == "if"
        assert sb.condition is None
        assert sb.children == []
        assert sb.then_body == []
        assert sb.else_body == []

    def test_construct_with_condition(self):
        cond = BinOp(OpType.EQ, Const(0, Size.SIZE_32), Const(1, Size.SIZE_32), Size.SIZE_32)
        sb = StructuredBlock(addr=0x1100, kind="if", condition=cond)
        assert sb.condition is cond

    def test_add_child_dedup(self):
        sb = StructuredBlock(addr=0x1000, kind="if")
        child = StructuredBlock(addr=0x1200, kind="then")
        sb.add_child(child)
        sb.add_child(child)
        assert len(sb.children) == 1

    def test_add_child_unique(self):
        sb = StructuredBlock(addr=0x1000, kind="if")
        child1 = StructuredBlock(addr=0x1200, kind="a")
        child2 = StructuredBlock(addr=0x1300, kind="b")
        sb.add_child(child1)
        sb.add_child(child2)
        assert len(sb.children) == 2

    def test_repr(self):
        sb = StructuredBlock(addr=0xDEAD, kind="loop")
        r = repr(sb)
        assert "dead" in r.lower()
        assert "loop" in r


# ── StructuredCFG ──

class TestStructuredCFG:
    def test_construct(self, entry_block):
        cfg = StructuredCFG(entry_block)
        assert cfg.entry_block is entry_block
        assert cfg.regions == []
        assert cfg.loops == []
        assert cfg.root is None

    def test_block_count_empty(self, entry_block):
        cfg = StructuredCFG(entry_block)
        assert cfg.block_count == 0

    def test_enter_region_blocks_empty(self, entry_block):
        cfg = StructuredCFG(entry_block)
        assert cfg.enter_region_blocks() == []

    def test_enter_loop_bodies_empty(self, entry_block):
        cfg = StructuredCFG(entry_block)
        assert cfg.enter_loop_bodies() == []


# ── StructuringPass ──

class TestStructuringPass:
    def test_construct(self, simple_graph):
        sp = StructuringPass(simple_graph)
        assert sp.graph is simple_graph
        assert sp.regions == []
        assert sp.loops == []
        assert sp.structured_cfg.entry_block is simple_graph.entry_block

    def test_regions_filled_after_run(self, simple_graph):
        sp = StructuringPass(simple_graph)
        sp.run()
        assert len(sp.regions) >= 2  # Each block should be in its own region

    def test_loops_empty_on_acyclic(self, simple_graph):
        sp = StructuringPass(simple_graph)
        sp.run()
        assert len(sp.loops) == 0

    def test_loops_detected_on_cyclic(self):
        entry = BasicBlock(addr=0x1000, is_entry=True)
        bb1 = BasicBlock(addr=0x2000)
        entry.successors = [bb1]
        bb1.predecessors = [entry]
        bb1.successors = [entry]  # back edge
        entry.predecessors = [bb1]
        g = BlockGraph(entry_block=entry, blocks={0x1000: entry, 0x2000: bb1})
        sp = StructuringPass(g)
        sp.run()
        assert len(sp.loops) >= 1

    def test_dom_blocks(self, simple_graph):
        sp = StructuringPass(simple_graph)
        entry = simple_graph.entry_block
        sp.run()
        dominated = sp.get_dominated_blocks(entry)
        assert entry in dominated

    def test_loop_body_empty(self, simple_graph):
        sp = StructuringPass(simple_graph)
        sp.run()
        bodies = sp.enter_loop_body()
        assert isinstance(bodies, list)

    def test_empty_graph(self):
        entry = BasicBlock(addr=0x1000, is_entry=True)
        g = BlockGraph(entry_block=entry, blocks={})
        sp = StructuringPass(g)
        sp.run()
        assert sp.regions == []
        assert sp.loops == []

    def test_empty_graph_no_entry(self):
        entry = BasicBlock(addr=0x0, is_entry=True)
        g = BlockGraph(entry_block=entry)
        g.entry_block = None
        sp = StructuringPass(g)
        sp.run()
        assert sp.regions == []

    def test_structure_body_returns_list(self, simple_graph):
        sp = StructuringPass(simple_graph)
        sp.run()
        bodies = sp.enter_loop_bodies()
        assert isinstance(bodies, list)

    def test_structured_cfg_lazy(self, simple_graph):
        sp = StructuringPass(simple_graph)
        cfg1 = sp.structured_cfg
        cfg2 = sp.structured_cfg
        assert cfg1 is cfg2

    def test_structured_cfg_root_initially_none(self, simple_graph):
        sp = StructuringPass(simple_graph)
        assert sp._structured_cfg is None
