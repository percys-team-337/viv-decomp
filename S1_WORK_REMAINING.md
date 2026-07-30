## S0 Phase Complete ✅ - Pipeline Breakers Fixed

### Bugs Fixed (2026-07-03)

| Bug | Location | Fix Status | Impact |
|-----|----------|------------|--------|
| **BUG-1** | `decompiler.py:113-148` | ✅ Fixed | Both fallback paths now populate `blocks={addr: entry}` so PrettyPrinter can find entry block |
| **BUG-2** | `pretty.py:283` | ✅ Fixed | Closing brace moved inside `if entry:` block - no more double braces on empty graphs |
| **BUG-3** | `pretty.py:139` | ✅ Fixed | `_entry_addr()` returns `Optional[int]`, `None` for empty instead of invalid `0` |

### Test Results
```
316 passed in 0.39s (all green, updated test_pretty.py line 152 to expect None)
```

### Pipeline Output Example
The decompiler now produces output for real functions:

```c
// Function: func_2004000
int
func_2004000() {
  // allocate stack frame
    rsp = (rsp -  0x8);
    rax = ((uint64_t*)0x201ffd0);
    if (eflags_eq)
    {
        rsp = (rsp +  0x8);
        rip = ((uint64_t*)rsp);
        rsp = (rsp +  0x8);
    }
    else
    {
        rax();
        goto L_33570838
    }
}
```

---

## S1 Work Remaining (2-3h)

### Current Output Issues
| Issue | Root Cause | Fix Needed Location |
|-------|------------|---------------------|
| `eflags_eq` in condition, not proper comparison like `(rsp != 0)` | Vivisect stores eflags state in Var nodes, Condition extraction incomplete | `pretty.py:430-432`, condition resolution logic |
| Mnemonic at end of assignments: `rax = ...; rax();` | Assignment formatter strips but Branch code still prints full line with mnemonic | `pretty.py:451-467`, `_format_assignment_instr` |
| Call target named `rax()` instead of function name (e.g., `exit()`) | PLT stub resolution not hooked to Vivisect symbol table | `formatter.py:_fmt_call`, `_resolve_call_target() hook in pretty.py` |

### S1 Tasks

#### 1. Call Target Resolution (30 min)
**Goal:** Resolve `rax() → exit()` for known PLT addresses  
**Location:** Override formatter's `_fmt_call()` or add pre-processing step to resolve callee address to Vivisect symbol name

```python
# In pretty.py constructor, store workspace reference (already done at line 246)
self._workspace = workspace  # For vw.getName(va) lookups

# In _format_call_instr:
if isinstance(callee, Const) and hasattr(self._workspace, 'getName'):
    callee_name = self._workspace.getName(callee.value)
    if callee_name:
        return f"{callee_name}({args})"  # Replace addr with name
```

#### 2. EFLAGS Condition Resolution (1-2h)
**Goal:** Convert `if (eflags_eq)` → `if (some_reg != 0)`  
**Challenge:** Vivisect's symbolik analysis separates flag computation from comparison logic

Options:
- **A:** Extract eflags state tracking from graph node metadata
- **B:** Pattern match common prologue patterns (`push rbp; mov rbp, rsp` → skip, `cmp rax, 0`)  
- **C:** Pass through with comment `[eflags condition not resolved]`

Recommendation: Option B first for prologue cleanup (common pattern), C as fallback.

#### 3. Mnemonic Stripping Cleanup (30 min)  
**Goal:** Remove trailing `; rax();` from assignment lines like `rsp = (rsp - 0x8); rax() = ...`

Current code at line 451-467 already strips dead `_t_` temps and eflags vars at **instruction filtering level**, but Branch handling still appends full instruction text. Fix: ensure all instruction formatting paths use filtered output.

---

## Next Actions
1. Hook PLT name resolution (quick win, 30min)  
2. Implement Prologue pattern skipping (common setup/teardown) (30min)  
3. Document eflags limitation for S2 control-flow phase (15 min)

**Total remaining S1 effort:** ~2-3 hours.
