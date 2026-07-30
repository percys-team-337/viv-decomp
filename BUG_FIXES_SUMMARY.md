# Viv-Decomp Bug Fixes Summary

## Date: 2026-07-03
## Issue: Pipeline crashes when function has no symbolik effects

### Bugs Fixed (S0.5 Phase)

#### BUG-1: Empty blocks dict on fallback — CRITICAL
**Location:** `viv_decomp/decompiler.py` lines 113-116, 142-148  
**Symptom:** `PrettyPrinter` looks up `blocks.get(_entry_addr())` which returns `None` → "No entry point found"

**Fix Applied:**
- Line 116: Changed `blocks={}` to `blocks={funcva: entry}` in first fallback path (function not discovered)  
- Line 146: Added `blocks_dict[funcva] = entry_block` before returning in second fallback path (no symbolik effects)

#### BUG-2: Double closing brace — COSMETIC
**Location:** `dec_engine/dec_impl/output/pretty.py` line 283  
**Symptom:** Extra `}` rendered unconditionally when no entry found  

**Fix Applied:**
- Moved line 283 closing brace inside the `if entry:` block (now at line 277)

#### BUG-3: `_entry_addr()` returns invalid address — LOGIC ERROR
**Location:** `dec_engine/dec_impl/output/pretty.py` line 139  
**Symptom:** Returns `0` for empty graphs, which is never a valid function address

**Fix Applied:**
- Changed return type from `int` to `Optional[int]`
- Updated fallback from `0` to `None` when blocks dict is empty

#### Test Updates
**File:** `tests/test_pretty.py` line 152  
**Change:** Updated assertion from `== 0` to `is None` to match new behavior  

---

## Verification

### Tests: All 316 pass ✅

```bash
$ cd /home/percy/viv-decomp && python -m pytest tests/ -v --tb=short
# Result: 316 passed in 0.39s
```

### Pipeline Test

The decompiler now runs without crashing on `/bin/sh`:

```bash
$ python -m viv_decomp /bin/sh --address 0x400080 --ssa yes --types yes
# Output: Valid JSON + C scaffolding (empty function body)
{ "func_name": "func_400080", "num_blocks": 1, ... }
// Function: func_400080
int
func_400080() {
  // allocate stack frame
 L_4194432:
}
```

---

## Remaining Phase S1 Work (Not Started)

| Task | Status | Impact |
|------|--------|--------|
| Hook `_resolve_call_target()` to formatter | ❌ | PLT stubs `binary.plt_func → func` still unresolved |
| Constant folding (`X^X→0`, `X^0→X`) | ❌ | Output has unsimplified expressions |
| EFLAGS suppression in output | ❌ | tcc/eflags noise leaks into pseudocode |

---

## Next Recommended Actions (S1 Completion — 2-3h)

1. **Review call target handling** in `pretty.py`: Find where call expressions reference PLT stubs  
2. **Implement constant folding logic** in `formatter.py` for XOR and identity ops  
3. **Map eflags registers** to suppress writes like `_t_XXX = reg_eflags`  

---

**Files Modified:**
- `viv_decomp/decompiler.py` (2 hunks)
- `dec_engine/dec_impl/output/pretty.py` (3 hunks: function signature + brace logic)  
- `tests/test_pretty.py` (1 hunk: test assertion update)
