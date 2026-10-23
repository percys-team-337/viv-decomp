# viv-decomp — Project State (S1–S8 progress)

Handoff doc for resuming work on the decompiler. Last updated after the S8
live-workspace symbolik lift + real-binary validation.

## Active branch & git state
- **Current branch:** `s8-real-benchmark` (last work: .viv workspace cache)
- Test suite: **505/505 passing**
- PR#17 (open): real-corpus benchmark + .viv cache; PR#18 (open): neural types

## Branch map / PRs
| Branch | Contents | PR |
|--------|----------|----|
| `phase0-ir-layer` | IR + symbolik layer | #1 merged |
| `phase2-control-flow` | S2 loop reconstruction + S3 graph-aware types | #3 merged |
| `s4-memory-model` | S4 memory: stack-frame + call graph | #4 merged |
| `s5-multi-arch` / `s5-extended-arch` | S5 arch selection + aliases/CLI | #5, #7 merged |
| `s7-quality-gate` / `s7-benchmark` / `s7-loop-harden` | S7 quality + benchmark + robustness | #6, #8, #9 merged |
| `s6-qt-viewer` / `s6-qt-gui` / `s6-qt-integrate` | S6 headless export + Qt viewer + app | #10, #11, #12 merged |
| `s8-plugin-system` | S8 plugin system (passes + formatters) | #13 merged |
| `s8-binary-patch` | S8 binary patching (diff/apply/regression) | #14 merged |
| `s8-vivisect-ext` | VivisectExtension (viv_extension.py, live-vw builder) | #15 merged |
| `s8-symbolik-live` | live-vw symbolik lift + real-binary tests | #16 merged |
| `s8-real-benchmark` | real-corpus benchmark + .viv workspace cache | **#17 open** |
| `s8-neural-types` | neural type inference (dependency-free ML) | **#18 open** |

## What's done (S1–S8 foundation)
- **S0/S1** IR layer, builder, formatter, SSA.
- **S2** Structured control flow: `while(cond){body}` reconstruction in `PrettyPrinter`.
  Fixed a real idom bug (min→max) that blocked loop-header detection.
- **S3** `TypeAnalyzer.analyze_graph()` — graph-aware type propagation over the CFG.
- **S4** `StackFrameAnalyzer` + `CallGraphBuilder`.
- **S5** `ArchSelector` (amd64/i386 + arm/mips/ppc aliases + `--arch` CLI).
- **S6** Headless graph export (JSON/SVG/DOT) + PyQt6 graph viewer + interactive
  `DecompilerApp` (`--view` CLI). Headless via `QT_QPA_PLATFORM=offscreen`.
- **S7** Quality metrics + gate + benchmark suite (loop/diamond/call corpus) +
  loop-hang hardening fix.
- **S8** `PluginRegistry` for analysis passes + output formatters, discovery via
  entry_point decorators, wired into `VivisectDecompiler` (passes + formatter).
- **S8** Binary patching (diff/apply/regression) as a plugin.
- **S8** Vivisect extension (`viv_extension.py`) + live-workspace graph builder
  (`WorkspaceGraphBuilder`, graph_source="workspace").
- **S8** Live-vw symbolik lift — real per-instruction IR via `getSymbolikGraph`
  → `EffectsBuilder`.

## Key files
- `dec_engine/dec_impl/output/pretty.py` — structured CFG walker
- `dec_engine/dec_impl/structuring/domtree.py` — dominators + back-edges (hardened)
- `dec_engine/dec_impl/type_inference/analyze.py` — TypeAnalyzer
- `dec_engine/dec_impl/memory/stack.py`, `memory/callgraph.py` — memory model
- `dec_engine/dec_impl/arch/selector.py` — ArchSelector
- `dec_engine/dec_impl/quality/metrics.py`, `quality/benchmark.py` — quality
- `dec_engine/dec_impl/export/graph.py` — JSON/SVG/DOT export
- `dec_engine/dec_impl/plugin/registry.py` — plugin system (S8)
- `viv_decomp/qt_viewer.py`, `viv_decomp/qt_app.py` — Qt viewer/app
- `viv_decomp/decompiler.py` — pipeline orchestration

## Vivisect note (IMPORTANT — corrected)
Vivisect's ELF `analyzePLT` raises `Invalid File: None` during `vw.analyze()`.
This is **benign and internal** — Vivisect catches it and continues analysis.
**Real-binary validation WORKS**: `/usr/bin/true` loads + analyzes to 50
functions (arch amd64) and decompiles end-to-end via
`VivisectDecompiler.from_workspace(vw)`.
(Confirmed: vivisect 1.3.2; `VivWorkspace` here has NO `getArchitecture` /
`addFunction` — arch is read via `getMeta('Architecture')`.)

## IR MemRef shapes (for the stack analyzer)
1. `MemRef(base=Var('rbp'|'rsp'), offset=Const(signed), size=...)` — Vivisect style
2. `MemRef(base=BinOp(SUB/ADD, Var(base), Const(k)), offset=Const(0), size=...)` — IR style
`_frame_offset()` in `stack.py` converts both to `(base_reg, signed_offset)`.

## Pipeline entry points
- `VivisectDecompiler.decompile_address(funcva, name)` → `DecompOutput` (incl. `quality` verdict)
- `VivisectDecompiler.export_graph(funcva, fmt)` → JSON/SVG/DOT string
- `VivisectDecompiler(..., plugin_registry=reg, passes=[...], formatter=...)`
- `PluginRegistry().discover_from([path])` → merge decorated plugins
- `python -m viv_decomp BIN --view` → interactive Qt app
- `python tests/benchmarks/run_benchmark.py` → CI quality gate

## Real corpus benchmark + .viv cache (PR#17)
`dec_engine/dec_impl/quality/real_benchmark.py` + `viv_decomp/vivcache.py`,
`vivgen.py`. **55/55 real funcs decompiled+passed** (small GNU ELFs).
`.viv` cache: generate once (vivbin -B / `python -m viv_decomp.vivgen BIN`),
load ~0.25s thereafter. 11MB rust bins now feasible via one-time background
generation (`--timeout 3600`).

## Remaining phases / TODOs
- **Neural type inference (PR#18)** — dependency-free ML in `dec_engine/dec_impl/ml/`.
  Next: SymbolikEmulator applied effects; train on real-corpus features.
- **Plugin GUI interactivity** — easy interactivity with Vivisect plugin GUI.
- **Naming & Comments** — function names + comments in decompiled output.
- **LLVM backend** — IR-only, roadmap.

## GitHub workflow convention
Fork → apply to fork branch → PR against upstream `atlas0fd00m/viv-decomp`.
gh CLI unauthenticated: use curl + GITHUB_TOKEN. PR `--head` must be
`<fork-owner>:<branch>`.
