"""
Tests for dec_impl/ssa/construct.py — Braun's SSA construction algorithm.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from vivisect.dec_impl.ssa.construct import SsaState, SsaTransform
from vivisect.dec_impl.ir.expression import Const, Var, Size
from vivisect.dec_impl.ir.block import BasicBlock, BlockGraph


class TestSsaState:
    """Tests for SsaState."""

    def test_construct(self):
        s = SsaState()
        assert s._next_ssa_num == 0
        assert s._var_def == {}
        assert s.def_set == set()
        assert s.phi_defs == []


    def test_new_ssa_name(self):
        s = SsaState()
        v1 = s.new_ssa_name(Var("x", Size.SIZE_32))
        v2 = s.new_ssa_name(Var("x", Size.SIZE_32))
        # Each call should increment the version number
        assert "x.s0" in v1.name
        assert "x.s1" in v2.name
        assert v1 != v2


    def test_new_ssa_name_different_bases(self):
        s = SsaState()
        v1 = s.new_ssa_name(Var("x", Size.SIZE_32))
        v2 = s.new_ssa_name(Var("y", Size.SIZE_32))
        assert "x.s0" in v1.name
        assert "y.s1" in v2.name


    def test_assign(self):
        s = SsaState()
        base = Var("eax", Size.SIZE_32)
        value = Var("eax.s0", Size.SIZE_32)
        s.assign(base, value)
        assert value in s.def_set
        assert s._var_def[base] == value


    def test_get_definitions(self):
        s = SsaState()
        # Define same base var 3 times
        for i in range(3):
            base = Var("x", Size.SIZE_32)
            value = s.new_ssa_name(base)
            s.assign(base, value)
        result = s.get_definitions()
        # Should have one group for "x"
        assert len(result) == 1
        base_name, defs = result[0]
        assert base_name == "x"
        assert len(defs) == 3


    def test_get_definitions_multiple_vars(self):
        s = SsaState()
        base1 = Var("x", Size.SIZE_32)
        s.assign(base1, Var("x.s0", Size.SIZE_32))
        base2 = Var("y", Size.SIZE_32)
        s.assign(base2, Var("y.s1", Size.SIZE_32))
        result = s.get_definitions()
        assert len(result) == 2


    def test_lookup_definition_found(self):
        s = SsaState()
        base = Var("x", Size.SIZE_32)
        value = Var("x.s0", Size.SIZE_32)
        s.assign(base, value)
        found = s.lookup_definition("x")
        assert found is not None
        assert found == value


    def test_lookup_definition_not_found(self):
        s = SsaState()
        found = s.lookup_definition("nonexistent")
        assert found is None


class TestSsaTransform:
    """Tests for SsaTransform."""

    def test_construct(self):
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        g = BlockGraph(entry_block=b1)
        transform = SsaTransform(g)
        assert transform.graph is g
        assert transform.states == {}


    def test_analyze_graph_simple_linear(self):
        """Test analyze_graph on a simple linear graph."""
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        b2 = BasicBlock(addr=0x1010)
        b1.successors = [b2]
        b2.predecessors = [b1]
        g = BlockGraph(entry_block=b1, blocks={0x1000: b1, 0x1010: b2})
        transform = SsaTransform(g)
        result = transform.analyze_graph()
        # Returns the same graph (modified in place)
        assert result is g
        # Should have created SSA states for each block
        assert len(transform.states) > 0


    def test_find_sccs_simple_linear(self):
        """Test SCC detection on a simple linear graph (2 blocks, no cycle)."""
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        b2 = BasicBlock(addr=0x1010)
        b1.successors = [b2]
        b2.predecessors = [b1]
        g = BlockGraph(entry_block=b1, blocks={0x1000: b1, 0x1010: b2})
        transform = SsaTransform(g)
        sccs = transform._find_sccs()
        # Linear graph: each block is its own SCC
        assert len(sccs) == 2


    def test_find_sccs_cyclic(self):
        """Test SCC detection on a cyclic graph (single SCC of size 2)."""
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        b2 = BasicBlock(addr=0x1010)
        b1.successors = [b2]
        b2.successors = [b1]  # cycle
        g = BlockGraph(entry_block=b1, blocks={0x1000: b1, 0x1010: b2})
        transform = SsaTransform(g)
        sccs = transform._find_sccs()
        # The whole thing should be one SCC
        assert len(sccs) == 1
        assert len(sccs[0]) == 2


    def test_process_scc(self):
        """Test processing an SCC creates states."""
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        b2 = BasicBlock(addr=0x1010)
        g = BlockGraph(entry_block=b1, blocks={0x1000: b1})
        transform = SsaTransform(g)
        scc = [b1]
        transform._process_scc(scc)
        assert b1 in transform.states
        assert isinstance(transform.states[b1], SsaState)


    def test_insert_phis_no_joins(self):
        """Test phi insertion on a linear graph (no joins = no phis added)."""
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        b2 = BasicBlock(addr=0x1010)
        b1.successors = [b2]
        b2.predecessors = [b1]
        g = BlockGraph(entry_block=b1, blocks={0x1000: b1, 0x1010: b2})
        transform = SsaTransform(g)
        # Process the graph first to populate SCC-related state
        transform.analyze_graph()
        # _insert_phis should not raise
        transform._insert_phis()
        assert transform is not None


    def test_find_def_in_block(self):
        """Test finding definitions within a block."""
        b1 = BasicBlock(addr=0x1000, is_entry=True)
        b2 = BasicBlock(addr=0x1010)
        b1.successors = [b2]
        b2.predecessors = [b1]
        g = BlockGraph(entry_block=b1, blocks={0x1000: b1, 0x1010: b2})
        transform = SsaTransform(g)
        # Empty search should return None
        result = transform._find_def_in_block(b1, "nonexistent")
        assert result is None
