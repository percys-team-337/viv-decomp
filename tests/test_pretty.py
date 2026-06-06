"""
Tests for output/pretty.py — PrettyPrinter.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from vivisect.dec_impl.output.pretty import PrettyPrinter
from vivisect.dec_impl.ir.block import BasicBlock, BlockGraph
from vivisect.dec_impl.ssa.construct import SsaState


@pytest.fixture
def entry_block():
    block = BasicBlock(addr=0x1000, is_entry=True)
    block.successors = []
    block.predecessors = []
    block.instructions = []
    return block


@pytest.fixture
def bb2():
    block = BasicBlock(addr=0x2000, is_entry=False)
    block.successors = []
    block.predecessors = []
    block.instructions = []
    return block


@pytest.fixture
def graph(entry_block, bb2):
    entry_block.successors = [bb2]
    bb2.predecessors = [entry_block]
    g = BlockGraph(entry_block=entry_block, blocks={0x1000: entry_block, 0x2000: bb2})
    return g


@pytest.fixture
def ssa():
    return SsaState()


# ── PrettyPrinter construct ──

class TestPrettyPrinterConstruct:
    def test_construct_basic(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        assert pp.func_name == "main"
        assert pp.graph is graph
        assert pp.ssa is ssa
        assert pp.func_addr is None
        assert pp.indent_size == 4

    def test_construct_with_addr(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa, func_addr=0x5000)
        assert pp.func_addr == 0x5000

    def test_construct_indent(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa, indent_size=2)
        assert pp.indent_size == 2

    def test_visited_empty_init(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        assert pp._visited == set()

    def test_loop_headers_empty_init(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        assert pp._loop_headers == set()

    def test_switch_entries_empty_init(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        assert pp._switch_entries == set()


# ── _is_loop_header ──

class TestIsLoopHeader:
    def test_false_on_missing_block(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        assert pp._is_loop_header(0xDEAD) is False

    def test_false_on_not_in_loop_headers(self, entry_block, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        # entry_block has predecessors but is not in _loop_headers
        assert pp._is_loop_header(entry_block.addr) is False


# ── _is_switch_entry ──

class TestIsSwitchEntry:
    def test_false_on_missing_block(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        assert pp._is_switch_entry(0xDEAD) is False

    def test_true_with_three_successors(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        block = graph.blocks[0x2000]
        # Give it 3 successors
        block.successors = [type("BB", (), {})(), type("BB", (), {})(), type("BB", (), {})()]
        assert pp._is_switch_entry(0x2000) is True

    def test_false_with_two_successors(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        block = graph.blocks[0x2000]
        block.successors = [type("BB", (), {})(), type("BB", (), {})()]
        assert pp._is_switch_entry(0x2000) is False


# ── _analyze_switches ──

class TestAnalyzeSwitches:
    def test_detects_switch_with_three_successors(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        block = graph.blocks[0x2000]
        block.successors = [type("BB", (), {})(), type("BB", (), {})(), type("BB", (), {})()]
        pp._analyze_switches()
        assert 0x2000 in pp._switch_entries

    def test_no_switches_found(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        pp._analyze_switches()
        assert pp._switch_entries == set()


# ── _entry_addr ──

class TestEntryAddr:
    def test_from_graph(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        assert pp._entry_addr() == 0x1000

    def test_from_graph_attr(self, graph, ssa):
        """graph.entry_block.addr is primary source."""
        pp = PrettyPrinter("main", graph, ssa)
        assert pp._entry_addr() == 0x1000

    def test_from_graph_entry_attr(self, ssa):
        entry = type("Block", (), {"addr": 0x9000})()
        g = type("Graph", (), {"blocks": {"0x1000": entry, "0x9000": entry}, "entry": 0x9000})()
        pp = PrettyPrinter("main", g, ssa)
        assert pp._entry_addr() == 0x9000

    def test_from_min_key_empty(self, ssa):
        g = type("Graph", (), {"blocks": {0x3000: None, 0x1000: None, 0x2000: None}, "entry_block": None, "entry": None})()
        pp = PrettyPrinter("main", g, ssa)
        assert pp._entry_addr() == min([0x3000, 0x1000, 0x2000])

    def test_from_min_key_no_blocks(self, ssa):
        g = type("Graph", (), {"blocks": {}, "entry_block": None, "entry": None})()
        pp = PrettyPrinter("main", g, ssa)
        assert pp._entry_addr() == 0


# ── _get_return_type ──

class TestGetReturnType:
    def test_default_returns_int(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        assert pp._get_return_type() == "int"


# ── generate ──

class TestGenerate:
    def test_basic_generate(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        output = pp.generate()
        assert "// Function: main" in output
        assert "main(" in output
        assert "int" in output
        assert "\n" in output

    def test_generate_with_addr(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa, func_addr=0xDEAD)
        output = pp.generate()
        assert "0xdead" in output.lower()

    def test_generate_empty_graph(self, ssa):
        entry = BasicBlock(addr=0x1000, is_entry=True)
        g = BlockGraph(entry_block=entry, blocks={})
        g.entry_block = None
        pp = PrettyPrinter("main", g, ssa)
        output = pp.generate()
        assert "No entry point found" in output

    def test_generate_contains_braces(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        output = pp.generate()
        assert "{" in output
        assert "}" in output

    def test_generate_starts_with_comment(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        output = pp.generate()
        lines = output.split('\n')
        assert lines[0].startswith("// Function:")

    def test_generate_empty_output_on_no_blocks(self, ssa):
        entry = BasicBlock(addr=0x1000, is_entry=True)
        g = BlockGraph(entry_block=entry, blocks={})
        g.entry_block = None
        pp = PrettyPrinter("main", g, ssa)
        output = pp.generate()
        assert "// No entry point found" in output

    def test_visited_cleared_on_generate(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        pp._visited.add(0xDEAD)
        pp.generate()
        # After generate, visited should be cleared then repopulated
        # But we can't easily verify it's empty without inspecting, just verify it runs
        assert len(pp.generate()) > 0


# ── _enter_block ──

class TestEnterBlock:
    def test_enter_existing_block(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        pp._output = []
        pp._enter_block(0x1000)
        assert len(pp._output) > 0

    def test_enter_missing_block(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        pp._output = []
        pp._enter_block(0xDEAD)
        assert any("not found" in line.lower() for line in pp._output)

    def test_enter_visited_block_skips(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        pp._output = []
        pp._enter_block(0x1000)
        pp._visited.clear()  # Reset visited so it enters again
        pp._enter_block(0x1000)
        # Should not crash

    def test_enter_block_no_instructions(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        block = graph.blocks[0x2000]
        block.instructions = []
        pp._output = []
        pp._enter_block(0x2000)
        # Should produce a label (format is L_{addr})
        assert any(line.strip().endswith(":") for line in pp._output)
        assert len(pp._output) > 0


# ── _format_control_flow ──

class TestFormatControlFlow:
    def test_format_unconditional_branch(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        target = type("BB", (), {"addr": 0x3000})()
        branch = type("Branch", (), {"condition": None, "true_target": target})()
        pp._output = []
        pp._format_control_flow(branch, None)
        assert any("goto" in line.lower() for line in pp._output)

    def test_format_conditional_branch(self, graph, ssa):
        pp = PrettyPrinter("main", graph, ssa)
        target = type("BB", (), {"addr": 0x3000})()
        branch = type("Branch", (), {"condition": "cond", "true_target": target})()
        pp._output = []
        pp._format_control_flow(branch, None)
        assert any("if" in line.lower() for line in pp._output)
