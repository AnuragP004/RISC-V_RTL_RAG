# Fermions-RAG: Complete Project Summary

## 📂 Directory Structure
```text
fermions-rag/
├── main.py                         # ★ Unified Push-Button Compiler (Phase 1–4)
├── agentic_debug_loop.py           # Standalone Silicon Reflex debug script
├── sim_main.cpp                    # C++ Verilator simulation driver
├── rv32ui-p-add.hex                # RISC-V test payload (x3 = 5 + 7 = 12)
├── simulation_trace.vcd            # Generated VCD waveform dump
├── project_codebase_summary.md     # ← This file
├── agentic_debug_loop_summary.md   # Design notes for the debug loop
│
├── pipeline/                       # RAG integration layer
│   ├── .env                        # API keys (GEMINI_API_KEY, VOYAGE_API_KEY)
│   ├── chunk_verilog.py            # AST-aware Verilog chunker
│   ├── embed_and_store.py          # ChromaDB vector store builder
│   └── generate_rtl.py             # RAG-driven Verilog generation
│
├── backups/                        # Auto-generated snapshots during healing
│   └── rv32i_core.v.iter_*         # Timestamped pre-patch backups
│
├── [Verilog Core Modules]
│   ├── rv32i_core.v                # Top-level stitcher (auto-healed target)
│   ├── alu.v                       # Arithmetic Logic Unit
│   ├── branch_unit.v               # Branch condition evaluator
│   ├── instruction_decoder.v       # RV32I instruction decoder
│   ├── program_counter.v           # PC with branch support
│   ├── register_file.v             # 32-register file
│   └── testbench.v                 # Simulation harness
│
├── obj_dir/                        # Verilator build artifacts
├── data/                           # ChromaDB persistent storage
├── corpus/                         # Raw + chunked Verilog corpus
└── venv/                           # Python virtual environment
```

---

## 🚀 How to Run

```bash
cd /home/thearagun/competitions/projects/fermions-rag
source venv/bin/activate
python3 main.py
```

---

## 📝 Script Breakdown

### `main.py` — Push-Button Compiler
The unified entry point that orchestrates the entire pipeline autonomously:

| Phase | Function | What It Does |
|-------|----------|--------------|
| **Phase 1** | `run_initial_generation()` | Imports `pipeline.generate_rtl` and generates all 6 Verilog modules via RAG + Gemini. Skips any file that already exists. |
| **Phase 2** | `compile_and_simulate()` | Runs Verilator (`-Wno-fatal`) to compile all sources, then executes the simulation binary to produce `simulation_trace.vcd`. |
| **Phase 3** | `check_waveforms()` | Parses the VCD trace with `vcdvcd`. Checks 4 signals (`pc`, `reg_write`, `alu_result`, `write_data`) for post-reset flatlines, accounting for inherited reset boundary values. Verifies `x3 = 12` functionally. |
| **Phase 4** | `agentic_heal()` | On failure: backs up `rv32i_core.v`, constructs a diagnostic prompt with ground-truth ALU encodings + locked interfaces, calls Gemini 2.5 Pro to rewrite the control unit, validates the output, and overwrites. |
| **Loop** | `main()` | Runs Phase 1 once, then iterates Phase 2→3→4 up to 3 times until SUCCESS or exhaustion. |

### `agentic_debug_loop.py` — Standalone Debugger
The original standalone Silicon Reflex script (~895 lines). More feature-rich with detailed per-signal diagnostics and richer logging. `main.py` is the streamlined production version.

### `pipeline/chunk_verilog.py` — Verilog Chunker
AST-aware chunker that splits Verilog files along module and `always` block boundaries. Treats `always` blocks as atomic units. Handles FSM state splitting for large blocks exceeding ~600 tokens.

### `pipeline/embed_and_store.py` — Vector Store Builder
Embeds chunked Verilog into ChromaDB using either Gemini embeddings or local `sentence-transformers`. Maintains separate collections for `verilog_rtl` and `spec_and_docs`.

### `pipeline/generate_rtl.py` — RAG Generator
Retrieves relevant Verilog chunks from ChromaDB, injects strict hardware rules (non-blocking assignments, latch prevention), and prompts Gemini 2.5 Pro to generate each component.

---

## 🔧 Key Technical Decisions

### 1. `-Wno-fatal` for Verilator
The locked sub-module files trigger cosmetic warnings (`EOFNEWLINE`, `DECLFILENAME`, `WIDTHTRUNC`, `CASEINCOMPLETE`). Using `-Wno-fatal` allows these to print without blocking compilation.

### 2. Inherited Reset Value in VCD Analysis
Signals set during reset (e.g., `reg_write=1` at t=1) that transition post-reset (to `0` at t=15) were falsely flagged as flatlined. Fixed by including the last value AT or BEFORE the reset boundary as the inherited starting state.

### 3. Ground-Truth ALU Encoding Injection
The LLM was hallucinating ALU control codes (e.g., SUB=`4'b0001` instead of `4'b1000`). The prompt now injects the exact `localparam` values from `alu.v` to prevent this.

### 4. Structural Validation of LLM Output
Before overwriting `rv32i_core.v`, the script validates that the LLM output contains `module rv32i_core`, `endmodule`, and all required sub-module instantiations (`u_program_counter`, `u_alu`, etc.).

---

## ✅ Final Verified Output

```
╔════════════════════════════════════════════════════════════════════════════╗
║                       🎉  SUCCESS — CORE VERIFIED  🎉                        ║
╚════════════════════════════════════════════════════════════════════════════╝

  Iteration        : 1
  Test             : ADD (5 + 7 = 12) PASSED
  All signals      : ACTIVE
    🟢 pc             → ACTIVE
    🟢 reg_write      → ACTIVE
    🟢 alu_result     → ACTIVE
    🟢 write_data     → ACTIVE
    ✓ x3 = 12        → ADD test PASSED ✅
```

---

## 📦 Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `vcdvcd` | 2.6.0 | VCD waveform parsing |
| `google-generativeai` | latest | Gemini LLM API |
| `chromadb` | latest | Vector database for RAG |
| `python-dotenv` | latest | Environment variable loading |
| `verilator` | 5.046 | Verilog → C++ simulation |
