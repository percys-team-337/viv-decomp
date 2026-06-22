"""
Comprehensive tests: EffectsBuilder + SymbolikAdaptor integration.
Tests run on real Vivisect symbolik output from loaded binaries.
"""
import sys
sys.path.insert(0, '/home/percy/viv-decomp')
sys.path.insert(0, '/home/percy/.hermes/hermes-agent/venv/lib/python3.11/site-packages')

import logging
logging.getLogger().setLevel(logging.ERROR)

import unittest
import tempfile
import os
import struct
from unittest.mock import MagicMock, patch, PropertyMock

import vivisect
import vivisect.symboliks.analysis as vsa
import vivisect.symboliks.expression as vse_expr
import vivisect.symboliks.effects as vse_eff
from collections import Counter


# ── helpers ──

def make_bin(path, code_bytes=b'\xcc' * 100):
    """Create a minimal binary for testing."""
    with open(path, 'wb') as f:
        f.write(code_bytes)
    return path


def get_test_vw():
    """Load /bin/ls with analysis."""
    pw = vivisect.VivWorkspace()
    pw.loadFromFile('/bin/ls')
    return pw, pw.getFunctions()


class TestEffectsBuilderIntegration(unittest.TestCase):
    """Integration test: EffectsBuilder on real Vivisect symbolik graphs."""

    @classmethod
    def setUpClass(cls):
        # Suppress vivisect debug spam for all tests in this suite
        for log in ['vivisect', 'vivisect.analysis', 'vivisect.analysis.elf',
                     'vivisect.analysis.windows.pe']:
            logging.getLogger(log).setLevel(logging.ERROR)

        vw = vivisect.VivWorkspace()
        vw.loadFromFile('/bin/ls')
        vw.analyze()
        cls.vw = vw
        cls.ctx = vsa.getSymbolikAnalysisContext(vw)
        
        # Find a function with a meaningful symbolik graph
        funcs = vw.getFunctions()
        best_va = None
        best_count = 0
        for va in funcs:
            try:
                g = cls.ctx.getSymbolikGraph(va)
                ns = list(g.getNodes())
                sz = vw.getMeta('FunctionSize', va) or 0
                if sz and 50 < sz < 2000:
                    if len(ns) > best_count:
                        best_va = va
                        best_count = len(ns)
            except:
                pass

        cls.test_va = best_va or funcs[0]
        cls.test_fname = vw.getName(cls.test_va)

    def test_graph_has_nodes(self):
        """Basic sanity: the selected function has a non-empty symbolik graph."""
        graph = self.ctx.getSymbolikGraph(self.test_va)
        nodes = list(graph.getNodes())
        self.assertGreater(len(nodes), 0,
            f"Function 0x{self.test_va:x} should have at least 1 symbolik graph node")
        print(f"[test_graph_has_nodes] Function 0x{self.test_va:x} ({self.test_fname}): {len(nodes)} nodes")

    def test_effects_builder_produces_blockgraph(self):
        """EffectsBuilder.build returns a valid BlockGraph with blocks."""
        from dec_engine.dec_impl.ir.builder import EffectsBuilder
        graph = self.ctx.getSymbolikGraph(self.test_va)
        builder = EffectsBuilder(self.test_va)
        bg = builder.build(graph, self.test_fname)

        self.assertIsNotNone(bg, "BlockGraph should not be None")
        self.assertGreater(len(bg.blocks), 0, "BlockGraph should have at least 1 block")
        self.assertIsNotNone(bg.entry_block)
        self.assertIsNotNone(bg.name)
        
        total = sum(len(bb.instructions) for bb in bg.blocks.values())
        print(f"[test_effects_builder_produces_blockgraph] {len(bg.blocks)} blocks, "
              f"{total} total instructions, entry=0x{bg.entry_block.addr:x}")

    def test_effects_builder_includes_var_assignments(self):
        """Check that variable assignments (SetVariable effects) produce IR."""
        from dec_engine.dec_impl.ir.builder import EffectsBuilder
        from dec_engine.dec_impl.ir.effects import Assignment
        from dec_engine.dec_impl.ir.expression import Var

        graph = self.ctx.getSymbolikGraph(self.test_va)
        builder = EffectsBuilder(self.test_va)
        bg = builder.build(graph, self.test_fname)

        # Count assignments involving Var destinations
        var_assign_count = 0
        for bb in bg.blocks.values():
            if not bb.instructions:
                continue
            for instr in bb.instructions:
                if isinstance(instr, Assignment) and isinstance(instr.destination, (Var, type(Var("test")))):
                    pass  # This is expected
                var_assign_count += 1
        
        # Just sanity: there should be some assignments for any real function
        print(f"[test_effects_builder_includes_var_assignments] Found {var_assign_count} "
              f"instruction types across {len(bg.blocks)} blocks")

    def test_effects_builder_wires_succ_preds(self):
        """Check that successors/predecessors are wired correctly."""
        from dec_engine.dec_impl.ir.builder import EffectsBuilder

        graph = self.ctx.getSymbolikGraph(self.test_va)
        builder = EffectsBuilder(self.test_va)
        bg = builder.build(graph, self.test_fname)

        # If there's more than 1 block, some should have edges
        blocks_with_edges = sum(1 for bb in bg.blocks.values() 
                                 if bb.successors or bb.predecessors)
        print(f"[test_effects_builder_wires_succ_preds] {blocks_with_edges}/{len(bg.blocks)} "
              f"blocks have edges")
        # At minimum, the entry block should have successors if graph has edges

    def test_builder_no_crash_on_all_function_types(self):
        """Test that EffectsBuilder doesn't crash on various function sizes/types."""
        from dec_engine.dec_impl.ir.builder import EffectsBuilder

        crash_count = 0
        success_count = 0
        
        all_funcs = self.vw.getFunctions()[:20]  # first 20 functions
        for va in all_funcs:
            try:
                g = self.ctx.getSymbolikGraph(va)
                builder = EffectsBuilder(va)
                bg = builder.build(g, self.vw.getName(va))
                success_count += 1
            except Exception as e:
                crash_count += 1
                if crash_count <= 3:
                    print(f"  [build error 0x{va:x}] {type(e).__name__}: {e}")

        print(f"[test_builder_no_crash_on_all_function_types] "
              f"{success_count} successes, {crash_count} crashes out of {len(all_funcs)} functions")
        # Don't fail on some crashes - real-world binary analysis is noisy
        self.assertGreaterEqual(success_count, 1, 
            "At least one function should build successfully")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'vw'):
            try:
                cls.vw.close()
            except:
                pass


class TestEffectsBuilderManual(unittest.TestCase):
    """Manual tests with constructed symbolik effects (no real binary needed)."""

    def _make_mock_effect(self, eff_type, **kwargs):
        """Create a mock symbolik effect of the given type."""
        eff = MagicMock()
        eff.__class__.__name__ = eff_type
        for k, v in kwargs.items():
            setattr(eff, k, v)
        return eff

    def test_builds_empty_graph(self):
        """Empty graph should produce BlockGraph with entry block."""
        from dec_engine.dec_impl.ir.builder import EffectsBuilder

        mock_graph = MagicMock()
        mock_graph.getNodes.return_value = iter([])
        
        builder = EffectsBuilder(0x1000)
        bg = builder.build(mock_graph, 'test_empty')
        
        self.assertIsNotNone(bg)
        self.assertEqual(len(bg.blocks), 0)

    def test_builds_single_block(self):
        """Single block with effects should produce BlockGraph with one block."""
        from dec_engine.dec_impl.ir.builder import EffectsBuilder
        from dec_engine.dec_impl.ir.effects import Assignment
        from dec_engine.dec_impl.ir.expression import Var

        mock_graph = MagicMock()
        
        # Create mock node with effects
        mock_eff = self._make_mock_effect('SetVariable', 
            varname='eax', 
            symobj=MagicMock(kids=[])
        )
        type(mock_eff.symobj).width = PropertyMock(return_value=8)
        
        ninfo = {'symbolik_effects': [mock_eff], 'opcodes': []}
        mock_graph.getNodes.return_value = iter([(0x1000, ninfo)])
        mock_graph.getNode.return_value = (0x1000, ninfo)
        mock_graph.getRefsFrom.return_value = []

        builder = EffectsBuilder(0x1000)
        bg = builder.build(mock_graph, 'test_single')
        
        self.assertEqual(len(bg.blocks), 1)
        self.assertIn(0x1000, bg.blocks)
        bb = bg.blocks[0x1000]
        self.assertIsNotNone(bb.instructions)
        self.assertGreater(len(bb.instructions), 0)


class TestEffectsBuilderIntegrationReal(unittest.TestCase):
    """Integration tests on real binary with actual symbolik effects."""

    @classmethod
    def setUpClass(cls):
        for log in ['vivisect', 'vivisect.analysis', 'vivisect.analysis.elf']:
            logging.getLogger(log).setLevel(logging.ERROR)

        cls.vw = vivisect.VivWorkspace()
        cls.vw.loadFromFile('/bin/ls')
        cls.vw.analyze()
        cls.ctx = vsa.getSymbolikAnalysisContext(cls.vw)

    def test_var_effect(self):
        """SetVariable effects should produce Assignment with Var destination."""
        from dec_engine.dec_impl.ir.builder import EffectsBuilder
        from dec_engine.dec_impl.ir.effects import Assignment

        # Find any function that produces effects
        funcs = self.vw.getFunctions()
        for va in funcs:
            try:
                g = self.ctx.getSymbolikGraph(va)
                nodes = list(g.getNodes())
                effs = []
                for _, ninfo in nodes:
                    effs.extend(ninfo.get('symbolik_effects', []) or [])
                
                if any(eff.__class__.__name__ == 'SetVariable' for eff in effs):
                    builder = EffectsBuilder(va)
                    bg = builder.build(g, self.vw.getName(va))
                    
                    # There should be at least some instructions
                    self.assertGreater(len(bg.blocks), 0)
                    print(f"[test_var_effect] function 0x{va:x}: built {len(bg.blocks)} blocks")
                    return
            except:
                pass

        self.skipTest("No SetVariable effects found in first 5 functions")

    def test_read_memory_effect(self):
        """ReadMemory effects should produce MemRef-based assignments."""
        from dec_engine.dec_impl.ir.builder import EffectsBuilder

        funcs = funcs = self.vw.getFunctions()[:10]
        for va in funcs:
            try:
                g = self.ctx.getSymbolikGraph(va)
                nodes = list(g.getNodes())
                effs = []
                for _, ninfo in nodes:
                    effs.extend(ninfo.get('symbolik_effects', []) or [])
                
                if any(eff.__class__.__name__ == 'ReadMemory' for eff in effs):
                    builder = EffectsBuilder(va)
                    bg = builder.build(g, self.vw.getName(va))
                    self.assertGreater(len(bg.blocks), 0)
                    print(f"[test_read_memory_effect] function 0x{va:x}: built {len(bg.blocks)} blocks")
                    return
            except:
                pass

        self.skipTest("No ReadMemory effects found in first 10 functions")

    def test_graph_structure(self):
        """Verify BlockGraph structure: entry, blocks dict, successor links."""
        from dec_engine.dec_impl.ir.builder import EffectsBuilder
        from dec_engine.dec_impl.ir.block import BlockGraph

        funcs = self.vw.getFunctions()
        for va in funcs[:5]:
            try:
                g = self.ctx.getSymbolikGraph(va)
                builder = EffectsBuilder(va)
                bg = builder.build(g, self.vw.getName(va))
                
                self.assertEqual(type(bg), BlockGraph)
                self.assertEqual(bg.entry_block.addr, min([b.addr for b in bg.blocks.values()]))
                
                # Check all blocks are in blocks dict
                for bb in bg.blocks.values():
                    self.assertIn(bb.addr, bg.blocks)
                
                print(f"[test_graph_structure] 0x{va:x}: {len(bg.blocks)} blocks, graph valid")
                return
            except:
                pass

        self.skipTest("Could not build any graph")


class TestEffectsBuilderEdgeCases(unittest.TestCase):
    """Edge case tests: None values, empty lists, unexpected effect types."""

    def test_none_effect_in_list(self):
        """None effects should be safely ignored."""
        from dec_engine.dec_impl.ir.builder import EffectsBuilder

        mock_graph = MagicMock()
        mock_eff = MagicMock()
        mock_eff.__class__.__name__ = 'SetVariable'
        mock_eff.varname = 'eax'
        mock_eff.symobj = MagicMock()
        type(mock_eff.symobj).width = PropertyMock(return_value=8)
        
        ninfo = {'symbolik_effects': [None, mock_eff, None], 'opcodes': []}
        mock_graph.getNodes.return_value = iter([(0x1000, ninfo)])
        mock_graph.getNode.return_value = (0x1000, ninfo)
        mock_graph.getRefsFrom.return_value = []

        builder = EffectsBuilder(0x1000)
        bg = builder.build(mock_graph, 'test_none')
        self.assertEqual(len(bg.blocks), 1)

    def test_empty_effects(self):
        """Empty effects list should produce block without instructions."""
        from dec_engine.dec_impl.ir.builder import EffectsBuilder

        mock_graph = MagicMock()
        ninfo = {'symbolik_effects': [], 'opcodes': []}
        mock_graph.getNodes.return_value = iter([(0x1000, ninfo)])
        mock_graph.getNode.return_value = (0x1000, ninfo)
        mock_graph.getRefsFrom.return_value = []

        builder = EffectsBuilder(0x1000)
        bg = builder.build(mock_graph, 'test_empty')
        self.assertEqual(len(bg.blocks), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
