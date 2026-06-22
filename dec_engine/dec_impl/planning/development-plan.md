# Vivisect Decompiler: Multi-Stage Development Plan

**Inspired by:** Reko's layered architecture (frontend → core engine → backend)  
**Reference:** compiliation.wiki fundamentals (CFG, Type Recovery, Structuring, Quality)  
**Current state:** 316 tests passing, basic pipeline works on `/bin/sh`

---

## Phase S0: Foundation (STABLE BASELINE)

### Goals
- All 316 tests green ✓
- Working end-to-end on `/bin/sh` ✓
- `viv-decomp/` project structure stable ✓

### Status: COMPLETE

---

## Phase S1: Symbolik Bridge Enhancement

**Priority: P0 (Critical)**

### Scope
1. Fix expression simplification in formatter
   - XOR reduction: `(X ^ X) → 0`
   - Zero propagation: `(X ^ 0) → X`
   - Parity chain suppression: detect and replace parity trees with `# parity(a)`
   - Dead code removal: strip `(X & 0xffffffff) ^ (X & 0xffffffff) → 0`

2. Memory reference improvement
   - `MemRef` syntax: `(addr)` → `*(uint64_t*)addr`
   - Scale factor display: `*4`, `*8` for indexed addressing

3. eflags suppression
   - Strip all `eflags_*` intermediate writes
   - Keep only actual register writes and memory stores

4. Symbolic call target resolution
   - Map `0x2004610()` → `__stack_chk_fail()` using vivisect symbol table
   - PLT stub → imported function name mapping
   - Global offset table (GOT) symbol resolution

### Deliverables
- `formatter.py`: Enhanced expression simplification
- `decompiler.py`: Symbol resolution pass
- Test suite update with new simplification tests
- **Target: `/bin/sh` C output with readable functions**

### Effort: ~4-6 hours

---

## Phase S2: Control Flow Structuring

**Priority: P1 (High)**

### Scope
1. **Basic block merging**
   - Unconditional forward jumps: merge `jmp L2` → inline target
   - Single-entry single-exit blocks: collapse chains
   - Common tail detection and elimination

2. **Control flow detection**
   - IF detection: `cmp X, Y → je L_true → jmp L_false → L_true`
   - WHILE detection: back-edge CFG + condition check
   - FOR detection: init → test → inc → back-edge pattern
   - SWITCH detection: indirect jump table via computed address

3. **Structured output representation**
   - `If(stmt, then_body, else_body)`
   - `While(cond, body)`
   - `For(init, cond, inc, body)`
   - `Switch(expr, cases, default)`
   - Nested structure representation

4. **Pretty printer rewrite**
   - Replace raw block iteration with structured traversal
   - Indentation based on nesting level
   - Curly brace formatting based on structure type

### Deliverables
- `dec_engine/dec_impl/structuring/`: New structuring module
- `StructuredBlock` dataclass + tree builder
- Pretty printer update for structured output
- **Target: `/bin/sh` with proper if/while/for reconstruction**

### Effort: ~6-8 hours

---

## Phase S3: Type Inference Engine

**Priority: P1 (High)**

### Scope
1. **Lattice-based type propagation**
   - Dataflow analysis across CFG
   - Join operators: `⊔` for type merging
   - Meet-semilattice for type hierarchies
   - Fixpoint iteration algorithm

2. **Pointer analysis**
   - Must-alias vs may-alias tracking
   - Heap vs stack pointer discrimination
   - Struct field offset analysis (based on offsets like `rbp - 0x48`)
   - Null pointer analysis for safety checks

3. **Struct detection**
   - Stack frame layout: find push/pop/alloc patterns
   - Function signatures: arg count, register vs stack params
   - Struct field offset matching: `rbp ± offset` patterns
   - Global variable typing: ELF data section analysis

4. **Type-aware code generation**
   - C types in output: `uint32_t`, `int64_t`, `void*`
   - Struct definitions: `struct { ... } varname;`
   - Pointer arithmetic in typed form: `ptr + offset`

### Deliverables
- `dec_engine/dec_impl/type_lattice/`: New lattice types
- Type inference pass in pipeline
- **Target: Functions with typed variables and struct detection**

### Effort: ~8-10 hours

---

## Phase S4: Memory Model & Call Graph Analysis

**Priority: P2 (Medium)**

### Scope
1. **Stack analysis**
   - Prologue/epilogue pattern detection
   - Frame pointer establishment: `push rbp; mov rbp, rsp`
   - Stack pointer adjustment: `sub rsp, N`
   - Local variable access: `[rbp - offset]` patterns

2. **Heap analysis**
   - `malloc`/`free` pattern recognition
   - Heap pointer flow tracking
   - Use-after-free detection (basic)

3. **Global symbol analysis**
   - Data section type resolution
   - GOT/PLT table resolution
   - Symbol versioning and overloading

4. **Cross-function analysis**
   - Call graph construction
   - Export/import function mapping
   - Inline function detection

### Deliverables
- `dec_engine/dec_impl/memory/`: Memory model
- Enhanced call graph visualization
- **Target: `/lib/x86-64-linux-gnu/libc.so.6` decompilation**

### Effort: ~6-8 hours

---

## Phase S5: Multi-Architecture Support

**Priority: P2 (Medium)**

### Scope
1. **Architecture translators**
   - Current: `Amd64SymbolikAnalysisContext` (x86_64)
   - Add: `I386SymbolikAnalysisContext`
   - Add: `Arm64SymbolikAnalysisContext`
   - Add: `MipsSymbolikAnalysisContext`

2. **Architecture-specific instruction encoding**
   - Instruction set decoding per target architecture
   - Register mapping per architecture
   - Calling convention per architecture

3. **Pluggable backend selection**
   - Architecture auto-detection via file headers
   - Architecture override CLI flag
   - Mixed-architecture binary support (e.g., x86_64 with i386 compat)

### Deliverables
- `dec_engine/dec_impl/arch/`: Architecture module
- Architecture detection in loader
- **Target: ARM binary decompilation**

### Effort: ~4-6 hours

---

## Phase S6: Frontend Layer — Qt Graph Viewer

**Priority: P3 (Nice-to-have)**

### Scope
1. **Qt/PyQt integration**
   - Main window with function tree
   - Graph view (CFG displayed as directed graph)
   - Code view (pseudocode display)
   - Call graph view

2. **Interactive features**
   - Click function to view code
   - Hover to see type info
   - Click edge to see analysis info
   - Zoom/pan in graph view

3. **Export features**
   - PNG/SVG export of graphs
   - JSON export of analysis results
   - PDF report generation

### Deliverables
- `viv_decomp/frontend/`: Qt frontend module
- **Target: Desktop GUI for decompiler**

### Effort: ~8-10 hours

---

## Phase S7: Quality Evaluation & Benchmarking

**Priority: P2 (Medium)**

### Scope
1. **Compilation fidelity metrics**
   - Compile-recompile test: decompile → compile → compare
   - Symbolic execution equivalence checking
   - Expression tree comparison

2. **Structured output assessment**
   - Readability scoring (based on complexity metrics)
   - Symbol resolution accuracy (%)
   - Type inference accuracy (%)

3. **Benchmark suite**
   - Test suite on known binaries: `/bin/sh`, `/bin/ls`, `libstdc++.so`
   - Expected output comparison (ground truth where available)
   - Degradation detection for regression testing

4. **Continuous integration hooks**
   - Automated test pipeline
   - Quality threshold enforcement
   - Performance regression tracking

### Deliverables
- `tests/benchmarks/`: Benchmark suite
- Quality evaluation metrics
- **Target: Automated quality gate in CI**

### Effort: ~4-6 hours

---

## Phase S8: Advanced Features

**Priority: P3 (Long-term)**

### Scope
1. **Neural type inference**
   - Train model on known binary type patterns
   - ML-assisted type prediction for ambiguous cases
   - Cross-binary type consistency checking

2. **Binary patching support**
   - Patch diff generation from decompiled code
   - Patch application to original binary
   - Patch regression detection

3. **LLVM backend**
   - LLVM IR code generation
   - Optimization pipeline integration
   - Native code generation from decompiled code

4. **Plugin system**
   - Custom analysis passes
   - Custom output formatters
   - Shared plugin marketplace

### Effort: ~12-16 hours

---

## Project Timeline

| Phase | Duration | Total |
|-------|----------|-------|
| S0: Foundation | DONE | DONE |
| S1: Symbolik | 4-6h | 4-6h |
| S2: Structuring | 6-8h | 10-14h |
| S3: Type Inference | 8-10h | 18-24h |
| S4: Memory Model | 6-8h | 24-32h |
| S5: Multi-arch | 4-6h | 28-38h |
| S6: Qt Viewer | 8-10h | 36-48h |
| S7: Quality | 4-6h | 40-54h |
| S8: Advanced | 12-16h | 52-70h |

**Total estimated effort: 40-70 hours to production quality**

---

## Implementation Priorities

1. **S1** → Immediate (fixes critical output quality)
2. **S2** → Next (structural C output)
3. **S3** → Third (type accuracy)
4. **S7** → Parallel (quality gate)
5. **S4** → After S2/S3 (completes core pipeline)
6. **S5** → After core pipeline stable
7. **S6** → Nice-to-have (GUI)
8. **S8** → Roadmap (ML/IrLVM)
