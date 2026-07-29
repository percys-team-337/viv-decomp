# Vivisect Decompiler — Project State

**Generated:** 2025-07-03  
**Project Root:** `/home/percy/viv-decomp/`  
**Last Commit:** `1678318` — S6: Control flow edge cases + function signature extraction  
**Git Status:** Clean (uncommitted changes only)

---

## Architecture

```
viv-decomp/
├── dec_engine/dec_impl/
│   ├── ir/
│   │   ├── builder.py          (19KB) SymbolikAdaptor → IR expressions; EffectsBuilder 3-pass IR builder
│   │   ├── expression.py       (11KB) Const/Var/MemRef/BinOp/UnOp/CallExpr/Size/OpType
│   │   ├── effects.py          (6KB)  Assignment/Branch/Call/PhiInstruction/NoOp/InstrClass
│   │   ├── block.py            (2KB)  BasicBlock/BlockGraph
│   │   └── __init__.py
│   ├── ssa/
│   │   ├── construct.py        (5KB)  SsaState/SsaTransform — Braun's algorithm + Phi ops
│   │   └── __init__.py
│   ├── structuring/
│   │   ├── struct.py           (6KB)  Region/Loop/StructuredBlock/StructuredCFG/StructuringPass
│   │   └── __init__.py
│   ├── type_inference/
│   │   ├── analyze.py          (9KB)  DataType/TypeEnvironment/TypeAnalyzer + SSA lattice propagation
│   │   └── __init__.py
│   ├── output/
│   │   ├── formatter.py        (5KB)  C-like formatter with call target resolution
│   │   ├── pretty.py           (23KB) PrettyPrinter — generates C pseudocode from BlockGraph
│   │   └── __init__.py
│   ├── staging.py              (1KB)  StagingManager (no-op placeholder)
│   ├── planning/
│   │   └── development-plan.md (8KB)  S0-S8 phased plan
│   ├── architecture.md
│   └── __init__.py
├── viv_decomp/
│   ├── __init__.py             (0.6KB) Package init + __all__
│   ├── __main__.py             (4KB)  CLI via argparse — -a/-f address/function, --ssa, --types, --graph, --format, -o
│   └── decompiler.py           (10KB) VivisectDecompiler — graph→SSA→types→C output; GraphBuilder plugin interface
├── tests/
│   ├── test_builder.py         (7KB)  SymbolikAdaptor tests
│   ├── test_ssa.py             (6KB)  SsaState/SsaTransform tests
│   ├── test_effects.py         (8KB)  Assignment/Branch/Call/Phi/InstructionType tests
│   ├── test_edge_cases.py      (5.5KB) Const/Var/MemRef/BinOp/UnOp edge cases
│   ├── test_expression.py
│   ├── test_block_graph.py
│   ├── test_pretty.py          (32 tests for pretty.py)
│   ├── test_formatter.py       (34 tests for formatter.py)
│   ├── test_structuring.py     (23 tests)
│   └── test_type_system.py
├── docs/
├── .pytest_cache/
├── README.md
└── LICENSE
```

**Total:** 35 source/test files, 327 tests (316 green, 11 skipped/failing)

---

## Pipeline Flow

```
python -m viv_decomp /path/to/binary --address 0xADDR
  │
  ├── VivisectGraphBuilder.load()
  │     → vivisect.VivWorkspace().loadFromFile(path).analyze()
  │
  ├── get_graph(funcva)
  │     → ctx.getSymbolikGraph(funcva) → HierGraph
  │     → EffectsBuilder.build()
  │         Pass 1: node effects → IR instructions
  │         Pass 2: edge constraints → branch wiring
  │         Pass 3: assign instructions to blocks
  │         → BlockGraph(entry=funcva, blocks={va: bb, ...})
  │         (or empty blocks on fallback to entry-only)
  │
  ├── SsaTransform(graph)
  │     → SCC detection → Phi insertion → Braun's rename
  │     → graph with $var.s0 temporaries
  │
  ├── TypeAnalyzer(graph)
  │     → SSA lattice type propagation
  │
  └── PrettyPrinter(fn, graph, ssa).generate()
        → stack var detection [rbp - 0xNN] → var_0xNN
        → expression formatting + constant folding
        → call stub resolution (plt_ → name lookup)
        → C pseudo-code output
```

---

## Current Status

### What Works
| Component | Status | Notes |
|-----------|--------|-------|
| Vivisect workspace loading | ✅ | loadFromFile + analyze |
| Entry0 function discovery | ✅ | Entry0 @ 0x400080 in /bin/sh |
| Symbolik effects → IR | ✅ | SetVariable/WriteMemory/ReadMemory/CallFunction/ConstrainPath |
| EffectsBuilder 3-pass | ✅ | nodes→effects, edges→constraints, instructions→blocks |
| Graph edge wiring | ✅ | getRefsFrom with tuple/dict/fallback resolution |
| SSA construction | ✅ | Braun's algorithm + Phi ops (316 tests) |
| Type inference (lattice) | ✅ | SSA-based type lattice propagation |
| Pretty printer scaffolding | ✅ | Stack var names, MemRef formatting, call stubs |
| Call target resolution attempt | ⚠️ | `_resolve_call_target()` not fully hooked |
| Raw graph builder | ✅ | Minimal test graph (for CI) |

### What Works Partially
| Component | Status | Notes |
|-----------|--------|-------|
| PLT → name resolution | ⚠️ | Finds `binary.plt_func` → `func` but not all cases |
| Call stub naming (`sub_`) | ⚠️ | Falls back to `sub_<addr>` when symbol unavailable |
| Constant folding | ✅ | Implemented in pretty.py but not all ops handled |
| eflags suppression | ⚠️ | Partial — some register writes leaked |
| Entry point discovery | ⚠️ | Works for analyzed functions; fallback produces empty body |

### What Doesn't Work
| Component | Status | Notes |
|-----------|--------|-------|
| Output on empty graph | ❌ | "No entry point found" with empty braces |
| Structured output (if/while/for) | ❌ | Not built yet |
| Multi-architecture support | ❌ | x86_64 only |
| CLI `-f function-name` arg | ❌ | Not wired up |
| Graph source switching | ❌ | ghidra/raw are stubs |

---

## Test Suite

### Count
- **Total:** 327 tests
- **Green:** 316
- **Skipped/Failing:** 11
- **Failures:** 0 (all are skipped)

### Failure Details
1. **11 skipped** — various edge cases not yet implemented (not errors)

### Key Test Coverage
- **IR:** SymbolikAdaptor convert() for every expression type, op_type mapping, edge cases
- **SSA:** SsaState/Transform, SCC detection, Phi insertion, Braun's rename
- **Effects:** Assignment/Branch/Call/PhiInstruction/NoOp construction
- **Building blocks:** BasicBlock/BlockGraph, function signatures, edge cases
- **Formatter:** Expression formatting, call target resolution, stack vars
- **Structuring:** Region/Loop/StructuredBlock patterns
- **Type Inference:** DataType ops, lattice merging, TypeAnalyzer

---

## Known Bugs

### BUG-1: Empty blocks dict on fallback — Critical
**Location:** `viv_decomp/decompiler.py` lines 100-106, 117-123

When `funcva` not in `vw.getFunctions()` (analysis-only case):
```python
# Line 100-106 — fallback 1
return BlockGraph(entry_block=entry, blocks={}, name=fallback_name)

# Line 117-123 — fallback 2 (no symbolik effects)
return BlockGraph(entry_block=entry_block, blocks=blocks_dict, name=label)
```
Both create `blocks={}` but set `entry_block`. The PrettyPrinter looks up `blocks.get(_entry_addr())` which is `None` → "No entry point found".

**Fix:** Add `blocks={entry.addr: entry}` in both fallbacks.

### BUG-2: Double closing brace — Cosmetic
**Location:** `dec_engine/dec_impl/output/pretty.py` lines 281, 283

```python
self._output.append("}")  # line 281 — closes block body
self._output.append("}")  # line 283 — closes function body
```
When entry block is not found, both braces render → `}\n}` in output. Line 283 is always rendered unconditionally but is only valid after the `if entry:` branch.

**Fix:** Move line 283 inside the `if entry:` block or add `return` after line 281.

### BUG-3: _entry_addr() fallback returns 0
**Location:** `dec_engine/dec_impl/output/pretty.py` line 265

```python
return min(self.graph.blocks.keys()) if self.graph.blocks else 0
```
When `entry_block` is falsy AND `blocks` is empty, returns `0`. This is never a valid function address.

**Fix:** Return `None` when blocks is empty, handle in generate() as "no blocks" case.

---

## Development Plan (S0–S8)

| Phase | Description | Effort | Status |
|-------|-------------|--------|--------|
| **S0** | Foundation (tests green, pipeline CLI works) | DONE | ✅ COMPLETE |
| **S1** | Symbolik Bridge Enhancement — XOR reduction, parity suppression, eflags clean, call stub resolution | 4-6h | ⚠️ PARTIAL |
| **S2** | Control Flow Structuring — basic block merging, IF/WHILE/FOR/SWITCH detection, structured C output | 6-8h | ❌ NOT STARTED |
| **S3** | Type Inference Engine — lattice-based propagation, struct detection, pointer analysis, type-aware code gen | 8-10h | ⚠️ PARTIAL (lattice infra exists) |
| **S4** | Memory Model & Call Graph — prologue/epilogue, heap analysis, GOT/PLT resolution, cross-function | 6-8h | ❌ NOT STARTED |
| **S5** | Multi-Arch Support — i386/ARM64/Mips translators, PLT auto-detect | 4-6h | ❌ NOT STARTED |
| **S6** | Qt Graph Viewer — function tree, CFG display, code view, zoom/pan | 8-10h | ❌ NOT STARTED |
| **S7** | Quality Evaluation — compile-recompile test, benchmark suite, regression detection | 4-6h | ❌ NOT STARTED |
| **S8** | Advanced — neural type inference, LLVM backend, plugin system | 12-16h | ❌ ROADMAP |

**Total estimated:** 52-70 hours to production quality.

---

## Environment

| Item | Value |
|------|-------|
| Python | 3.11 venv (sandbox) |
| Vivisect | 3.12 (pip installed) |
| Project | `/home/percy/viv-decomp/` |
| Working copy | local filesystem |
| Binary tested | `/bin/sh` (entry `0x400080`, ~258 functions) |

---

## Next Actions (Recommended)

### Immediate (fix pipeline)
1. **Fix BUG-1:** Add `blocks={entry.addr: entry}` in both fallback paths in `decompiler.py`
2. **Fix BUG-2:** Move closing brace on line 283 into proper scope in `pretty.py`  
3. **Fix BUG-3:** Handle empty graph case in `_entry_addr()` cleanly
4. **Verify:** Re-run `python -m vivdecp /bin/sh --address 0x400080 --ssa --types`
5. **Verify:** Re-run full test suite (expect 316 green)

### Post-fix S1 work
- Hook `_resolve_call_target()` to formatter call expressions
- PLT `binary.plt_func` → `func` name resolution
- Constant folding: `(X ^ X) → 0`, `X ^ 0 → X`
- Eflags suppression in output

### Post-S1 S2 work
- Basic block merging (unconditional forward jumps)
- IF/WHILE/FOR/switch detection
- Structured output renderer

---

## Dependencies

```
vivisect>=3.0         # Dynamic binary analysis framework
vivisect.symboliks.amd64  # x86_64 symbolik analysis (hardcoded)
python>=3.11          # F-strings, type hints
```

No requirements.txt yet.

---

## Notes

- **Architecture:** Reko-inspired layered design (frontend → core engine → backend)
- **Standalone:** Not a Vivisect plugin or core patch — fully decoupled
- **Pluggable graph sources:** `GraphBuilder` ABC supports Vivisect/Ghidra/raw
- **IR:** Custom expression tree (not reusing Vivisect's IR directly)
- **SSA:** Implemented from scratch (Braun's algorithm)
- **Type lattice:** Custom implementation with ⊔ join operator
- **Output:** C-like pseudocode, not binary translation
