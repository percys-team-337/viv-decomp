"""
Tests for ir/block.py — BasicBlock, BlockGraph.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from vivisect.dec_impl.ir.block import BasicBlock, BlockGraph


class TestBasicBlock:
    """Tests for BasicBlock dataclass."""

    def test_construct_default(self):
        b = BasicBlock(addr=0x1000)
        assert b.addr == 0x1000
        assert b.instructions == []
        assert b.predecessors == []
        assert b.successors == []
        assert b.label == ""
        assert b.is_entry is False
        assert b.is_exit is False
        assert b.metadata == {}

    def test_construct_with_args(self):
        b = BasicBlock(addr=0x1000, label="entry")
        assert b.addr == 0x1000
        assert b.label == "entry"
        assert b.is_entry is False

    def test_add_predecessor(self):
        b1 = BasicBlock(addr=0x1000)
        b2 = BasicBlock(addr=0x1010)
        b1.add_predecessor(b2)
        assert b1.predecessors == [b2]
        assert b2.successors == [b1]

    def test_add_predecessor_duplicate_ignored(self):
        b1 = BasicBlock(addr=0x1000)
        b2 = BasicBlock(addr=0x1010)
        b1.add_predecessor(b2)
        b1.add_predecessor(b2)
        assert len(b1.predecessors) == 1

    def test_repr(self):
        b = BasicBlock(addr=0x1000)
        assert "0x1000" in repr(b)

    def test_is_entry_setter(self):
        b = BasicBlock(addr=0x1000, is_entry=True)
        assert b.is_entry is True

    def test_is_exit_setter(self):
        b = BasicBlock(addr=0x1000, is_exit=True)
        assert b.is_exit is True


class TestBlockGraph:
    """Tests for BlockGraph dataclass."""

    def test_construct_minimal(self):
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        g = BlockGraph(entry_block=b1)
        assert g.entry_block is b1
        assert g.blocks == {}
        assert g.name == ""

    def test_construct_with_blocks(self):
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        b2 = BasicBlock(addr=0x1010)
        g = BlockGraph(entry_block=b1, blocks={0x1000: b1, 0x1010: b2})
        assert 0x1000 in g.blocks
        assert 0x1010 in g.blocks

    def test_name_setter(self):
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        g = BlockGraph(entry_block=b1)
        g.name = "my_func"
        assert g.name == "my_func"

    def test_find_block_by_addr_found(self):
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        g = BlockGraph(entry_block=b1, blocks={0x1000: b1})
        result = g.find_block_by_addr(0x1000)
        assert result is b1

    def test_find_block_by_addr_not_found(self):
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        g = BlockGraph(entry_block=b1)
        result = g.find_block_by_addr(0x9999)
        assert result is None

    def test_blocks_dict_mutable(self):
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        b2 = BasicBlock(addr=0x1010)
        g = BlockGraph(entry_block=b1, blocks={0x1000: b1})
        g.blocks[0x1010] = b2
        assert 0x1010 in g.blocks

    def test_str_with_blocks(self):
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        b2 = BasicBlock(addr=0x1010)
        g = BlockGraph(entry_block=b1, blocks={0x1000: b1, 0x1010: b2})
        assert "0x1000" in str(g)
        assert "0x1010" in str(g)

    def test_dominators(self):
        """Test dominator computation on a simple linear graph."""
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        b2 = BasicBlock(addr=0x1010)
        b1.add_predecessor(b1)  # b1 pred of b2
        b1.add_predecessor(b1)
        b1.add_predecessor(b1)

    def test_dominators_simple_graph(self):
        """Test dominator computation on a simple graph."""
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        b2 = BasicBlock(addr=0x1010)
        b1.successors = [b2]
        b2.predecessors = [b1]
        g = BlockGraph(entry_block=b1, blocks={0x1000: b1, 0x1010: b2})
        doms = g.dominators()
        # Entry should dominate itself
        assert b1 in doms
        assert b1 in doms[b1]

    def test_back_edges_on_acyclic_graph(self):
        """A linear graph has no back edges."""
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        b2 = BasicBlock(addr=0x1010)
        b1.successors = [b2]
        b2.predecessors = [b1]
        g = BlockGraph(entry_block=b1, blocks={0x1000: b1, 0x1010: b2})
        back = g.back_edges()
        assert len(back) == 0

    def test_back_edges_on_cyclic_graph(self):
        """A cyclic graph should have back edges."""
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        b2 = BasicBlock(addr=0x1010)
        b1.successors = [b2]
        b2.successors = [b1]  # cycle
        g = BlockGraph(entry_block=b1, blocks={0x1000: b1, 0x1010: b2})
        back = g.back_edges()
        assert len(back) >= 1


    def test_strongly_connected_components_acyclic(self):
        """An acyclic graph has SCCs of size 1."""
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        b2 = BasicBlock(addr=0x1010)
        b1.successors = [b2]
        b2.predecessors = [b1]
        g = BlockGraph(entry_block=b1, blocks={0x1000: b1, 0x1010: b2})
        sccs = g.get_strongly_connected_components()
        assert len(sccs) == 2
        # Each SCC should contain exactly one block
        all_blocks = set()
        for scc in sccs:
            for b in scc:
                assert b not in all_blocks
                all_blocks.add(b)
        assert len(all_blocks) == 2

    def test_strongly_connected_components_cyclic(self):
        """A cyclic graph should have one SCC of size 2."""
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        b2 = BasicBlock(addr=0x1010)
        b1.successors = [b2]
        b2.successors = [b1]  # cycle
        g = BlockGraph(entry_block=b1, blocks={0x1000: b1, 0x1010: b2})
        sccs = g.get_strongly_connected_components()
        assert len(sccs) == 1
        assert len(sccs[0]) == 2

    def test_post_dominators_empty_graph(self):
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        g = BlockGraph(entry_block=b1)
        post_doms = g.post_dominators()
        assert post_doms == {}

    def test_post_dominators_single_block(self):
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        g = BlockGraph(entry_block=b1, blocks={0x1000: b1})
        post_doms = g.post_dominators()
        # Entry dominates everything
        assert len(post_doms) == 1

    def test_predecessors_empty_by_default(self):
        b = BasicBlock(addr=0x1000)
        assert b.predecessors == []

    def test_successors_empty_by_default(self):
        b = BasicBlock(addr=0x1000)
        assert b.successors == []

    def test_metadata_default_empty(self):
        b = BasicBlock(addr=0x1000)
        assert b.metadata == {}

    def test_can_modify_metadata(self):
        b = BasicBlock(addr=0x1000)
        b.metadata["flag"] = True
        assert b.metadata["flag"] is True
