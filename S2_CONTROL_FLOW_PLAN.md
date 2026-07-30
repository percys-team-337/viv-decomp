# S2 Plan: Structured Control Flow

## Current State (Post-S1)

Output uses `goto` and label-based control flow:
```c
if (*) { ... } else { goto L_...; }
```

**Problems:**
- No structured constructs (`if/else`, `while`, `for`, `switch`)  
- Blocks are just sequential statements with gotos
- Hard to read complex logic

---

## S2 Objectives

### 1. Structured Output Transformation
Convert flat CFG + goto style into nested C constructs:

| Pattern | Current Output | Target Output |
|---------|---------------|---------------|
| **if/else** | `if (*) { A } else { goto L; }` | `if (*) { A } else { B }` |
| **while** | `L1: if (cond) { body; goto L1; } else { fallthrough; }` | `while (cond) { body }` |
| **do-while** | Do block + back-edge jump to condition check | `do { body } while (cond);` |
| **for** | Init; L: if (cond) { body; update; goto L; } | `for (; cond; update) { body }` |
| **switch** | Jump table + case labels via gotos | `switch (x) { case 0: ... break; default: ... }` |

---

## Implementation Approach

### Phase S2.1: Dominator Tree Construction
**Goal:** Identify structured control flow patterns by analyzing block dominance.

```python
def compute_dominators(graph):
    """Build dominator tree from BlockGraph.
    
    Returns: dict mapping each block to its immediate dominator (idom).
    Uses Cooper's iterative algorithm (simple, works on small graphs).
    """
```

**Why:** Structured constructs have specific dominance patterns:
- `if/else`: Both successors dominated by branch block  
- `while`: Single back-edge forming a natural loop (header dominates all in loop)
- `switch`: Multi-way branch from single condition with common successor

---

### Phase S2.2: Natural Loop Detection
**Goal:** Identify while/do-while loops via back-edges.

```python
def find_natural_loops(graph, dominators):
    """Find loops where header dominates all block in loop (natural loop).
    
    Back-edge detection: edge src → dst where dst dominates src.
    Loop body = all nodes that can reach src without going through dst + dst itself.
    """
```

**Output:** List of `{header, back_edges, body_blocks}` for each loop.

---

### Phase S2.3: Structured Block Merging (Unconditional Jumps)
**Goal:** Merge blocks connected by unconditional forward jumps.

Pattern: `A: ...; goto B;` where A has single successor B and B is not a jump target from elsewhere → merge A+B into one block.

```python
def collapse_uncond_jumps(graph):
    """Merge blocks joined by unconditional forwards-only jumps."""
```

---

### Phase S2.4: Conditional Branch Structuring
**Goal:** Convert `if (cond) { A } else { goto L; }` patterns to proper if/else or single-branch structures.

Detect two patterns:
1. **if/else**: Both true/false successors converge to common successor after blocks  
2. **if-only**: True branch, false falls through to next block

Detection logic:
```python
def analyze_branch_pattern(block, graph):
    """Determine if a conditional branch is:
    - if-only (false falls through)
    - if-else (both branches exist and converge)  
    - if-then-goto (one branch jumps out of sequence)
    """
```

---

### Phase S2.5: Switch Statement Detection
**Goal:** Identify switch/case from jump tables.

Pattern:
1. Load table address from instruction  
2. Compute index from register/value  
3. Jump to `cases[i]` via computed address  

Detection:
- Check for indirect branch through computed address (not direct label)
- Look for sequential block addresses = case labels
- Common successor after all cases = switch exit

---

## Implementation Order

1. **S2.0**: Block merging (unconditional jumps) — 30 min  
   - Simplifies CFG, makes patterns clearer  
   - Low risk (doesn't affect semantics)

2. **S2.1**: Dominator computation — 45 min  
   - Needed for loop detection  
   - Straightforward iterative algorithm

3. **S2.2**: Loop identification (natural loops) — 1h  
   - Back-edge analysis  
   - Emit `while(header_condition) { body }` structure  

4. **S2.3**: If/else structuring — 1h  
   - Convergence-point detection  
   - Convert flat gotos to nested if/else

5. **S2.4**: Switch detection (optional in S2, can move to S4) — 2-3h  
   - Complex pattern matching  
   - Deferred if basic loops/if/else work

**Total S2 effort:** ~4-5 hours (excluding testing)

---

## Testing Strategy

For each phase:
1. Generate test binaries with known control flow patterns
   - Simple `if/else` functions
   - `while(i < n)` loops  
   - Nested if/loops
   - For-loops (which are whiles + update)

2. Compare output structure (not exact text match)
   - Check for presence of keywords (`while`, `for`) vs missing
   - Verify no dangling gotos in structured regions

3. Round-trip test (bonus):
   - Compile test function to assembly → decompile → compile again  
   - Verify identical machine code (semantic equivalence)

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| CFG too complex for naive analysis | Structuring fails, output same as before | Add fallback: emit labels+goto when cannot structure |
| Spaghetti code (no natural loops) | Cannot detect structured patterns | Accept unstructured output for such cases + add comment |
| Back-edge misidentification | Infinite loop in decompiler | Verify forward progress via dominator tree property |

---

## Success Criteria (S2 Done) ✅

- [ ] Simple while-loops emit as `while (...) { ... }`  
- [ ] Nested if/else preserve structure without extra gotos
- [ ] Block merging reduces average blocks/function by 30%
- [ ] All existing tests still pass (backwards compatible)
- [ ] Output for sample functions is human-readable (no goto spaghetti)

---

## Post-S2: S3 Preview (Type Inference)

Once structured control flow works, S3 focuses on:
1. **Stack variable typing:** Infer `int`, `char*`, `struct Foo*` from usage patterns  
2. **Pointer dereferences:** Convert `(*(uint64_t*)x)` → clearer access  
3. **Cast insertion:** Add explicit casts where type mismatch detected  
4. **Field extraction:** Recognize struct field accesses (e.g., `obj->field`)

**S3 depends on S2:** Structured loops make induction variable analysis tractable.