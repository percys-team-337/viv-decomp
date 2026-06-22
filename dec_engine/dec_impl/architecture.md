# Vivisect Decompiler: Reko-Inspired Architecture

## Overview

This architecture document outlines the design of a pluggable, multi-stage decompiler pipeline for Vivisect, inspired by Reko's layered architecture pattern. The goal is to produce production-grade C pseudocode from x86/x64 binaries with high accuracy.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    FRONTEND LAYER (Pluggable)                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐  ┌──────────────────┐  │
│  │ CLI (CLI  │ │ GTK GUI  │ │ Qt Graph │  │ MCP/Ghidra API   │  │
│  │ Entry)   │ │  Backend │  │  Viewer  │  │ (future source)  │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘  └────────┬─────────┘  │
│       └────────────┴────────────┴───────────────────┘            │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CORE ENGINE LAYER (Pluggable)                 │
│                                                                  │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────┐  │
│  │ CFG Builder │→│ Symbolik     │→│ SSA/Rename   │→│ Struct │──│
│  │ / Lifter    │  │ Graph Builder│  │ Engine       │  │       │  │
│  │             │  │              │  │              │  │       │  │
│  │ - Vivisect  │  │ - Amd64/     │  │ - Braun's    │  │ - SMT │  │
│  │ - Ghidra    │  │   I386/ARM   │  │   algorithm  │  │ /    │  │
│  │ - Raw      │  │              │  │              │  │   Z3  │  │
│  └─────────────┘ └──────────────┘ └──────────────┘ └────────┘  │
│                                                                  │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────┐  │
│  │ Memory      │→│ Type         │→│ Control Flow │→│ Quality │──│
│  │ Model       │  │ Inference    │  │ Structuring  │  │ Eval  │  │
│  │             │  │ (Lattice-    │  │              │  │       │  │
│  │ - Heap      │  │  based)     │  │ - Schema     │  │ - CI  │  │
│  │ - Stack     │  │              │  │   / SMT      │  │       │  │
│  │ - Pointer   │  │ - Dataflow   │  │   / Pattern│  │       │  │
│  │   Tracking  │  │   /          │  │   Based     │  │       │  │
│  └─────────────┘ └──────────────┘ └──────────────┘ └────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     BACKEND LAYER (Pluggable)                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐  ┌──────────────────┐  │
│  │ C Output │ │ JSON     │ │ LLVM IR  │  │ HTML Report      │  │
│  │ (pretty) │ │ Metadata │ │ (future) │  │ / GraphViz       │  │
│  └──────────┘ └──────────┘ └──────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Layer Responsibilities

### Frontend Layer (Pluggable)
Each frontend is independent and communicates with the core engine via a standard API.

| Component | Description |
|-----------|-------------|
| **CLI** | Command-line decompiler: `viv_decomp -f <func> <binary>` |
| **GTK Backend** | Desktop GUI with function tree, code view, call graph |
| **Qt Graph Viewer** | Interactive graph viewer for CFG visualization |
| **MCP/Ghidra** | Pluggable source: load from Ghidra database via MCP |
| **REST API** | HTTP server for remote decompilation requests |

**Frontend contracts:**
```
- load(binary_path: str) → workspace handle
- decompile(func_addr: int, workspace) → DecompilationResult
- get_functions(workspace) → list[FunctionInfo]
```

### Core Engine Layer (Pluggable)

#### CFG Builder / Lifter
- **Vivisect backend**: Uses `vivisect.VivWorkspace` + `Amd64SymbolikAnalysisContext`
- **Ghidra backend**: Uses Ghidra MCP to fetch function graphs
- **Raw backend**: Uses angr/keystone for bare-metal analysis

#### Symbolik Graph Builder
- Architecture-specific effect extraction
- Maps Write/Load/Store/Branch/Call effects to IR nodes
- Handles symbolik operand conversion with correct size semantics

#### SSA/Rename Engine
- Braun's algorithm with per-block rename stacks
- Phi node insertion for cross-block dependencies
- Memory SSA for load/store analysis

#### Type Inference Engine
- Lattice-based type propagation (inspired by TIE paper)
- Pointer analysis with heap modeling
- Struct detection for stack frames

#### Control Flow Structuring
- Schema-based pattern matching (if/while/for/switch)
- SMT-assisted gotoless conversion
- Loop reduction heuristics

#### Memory Model
- Stack frame reconstruction via prologue/epilogue analysis
- Heap analysis for dynamic allocations
- Pointer alias analysis

#### Quality Evaluation
- Compilation fidelity metrics
- Expression size and readability scoring
- Symbol resolution accuracy

### Backend Layer (Pluggable)

| Component | Description |
|-----------|-------------|
| **C Output** | C-like pseudocode with type annotations |
| **JSON Metadata** | CFG graph, types, symbols, analysis results |
| **LLVM IR** | Future: output to LLVM for further optimization |
| **HTML Report** | Interactive web report with graphs and annotations |

## Data Flow

```
Binary → (Frontend Loader) → Workspace
Workspace → (CFG Builder) → CFG + Symbolik Graph
CFG → (Lifter) → IR (basic blocks, instructions)
IR → (SSA Engine) → SSA-form IR
SSA IR → (Type Inference) → Typed SSA IR
Typed SSA IR → (Control Structuring) → Structured IR
Structured IR → (Backend Formatter) → C Pseudocode + JSON
```

## Pluggability Design

All components use dependency injection with configurable backends:

```python
class Decompiler:
    def __init__(self, graph_source: str = 'vivisect'):
        self.cfg_builder = self._create_builder(graph_source)
        self.ssa_engine = BraunsAlgorithm()
        self.type_inf = LatticeTypeInference()
        self.structurer = SMTStructuringEngine()
        self.output = CFormatter()
    
    def _create_builder(self, source: str):
        if source == 'vivisect':
            return VivisectGraphBuilder()
        elif source == 'ghidra':
            return GhidraMcpGraphBuilder()
        elif source == 'raw':
            return RawAnalyzerBuilder()
        else:
            raise ValueError(f"Unknown source: {source}")
```

## Key Design Decisions

1. **Standalone over plugin**: Don't modify Vivisect core; interact via public APIs
2. **Layered architecture**: Frontend → Core Engine → Backend with clean interfaces
3. **Pluggable everything**: CFG builder, type inference, control flow structuring all interchangeable
4. **Symbolik first**: Real symbolik analysis drives correctness, not heuristics
5. **SSA as intermediate form**: Enables type inference and structured output
6. **Memory model separate**: Stack/heap analysis needs its own subsystem

## Future Extensibility

- **ARM/MIPS**: Add architecture translators in Symbolik Builder
- **LLVM backend**: Add LLVM IR code generation
- **Cross-function analysis**: Alias analysis across function boundaries
- **Binary patching support**: Generate patch diffs from decompiled code
- **Neural type inference**: Train ML model for type prediction
