# 🧬 Silicon Reflex — LLM-Driven Self-Healing RISC-V Compiler

> A closed-loop agentic RAG pipeline that autonomously generates, simulates, diagnoses, and self-heals a single-cycle RV32I RISC-V processor using Gemini 2.5 Pro and Verilator.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
![Verilog](https://img.shields.io/badge/HDL-Verilog-orange)
![Verilator](https://img.shields.io/badge/Simulator-Verilator%205-green)
![Gemini](https://img.shields.io/badge/LLM-Gemini%202.5%20Pro-4285F4?logo=google)
![ChromaDB](https://img.shields.io/badge/VectorDB-ChromaDB-purple)

---

## Overview

This project implements a **push-button compiler** that takes a processor specification (`processor_spec.json`) and autonomously:

1. **Generates** all Verilog sub-modules via RAG (Retrieval-Augmented Generation) using a ChromaDB knowledge base of reference RISC-V cores.
2. **Compiles & Simulates** the full design using Verilator to produce cycle-accurate VCD waveform traces.
3. **Critiques** the simulation output by programmatically parsing the `.vcd` file to detect control signal flatlines and functional assertion failures.
4. **Self-Heals** the top-level stitcher (`rv32i_core.v`) by constructing a diagnostic prompt with ground-truth ALU encodings and locked sub-module interfaces, then calling Gemini to rewrite the broken control logic — all without human intervention.

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SILICON REFLEX PIPELINE                           │
│                                                                     │
│  processor_spec.json ──► Phase 1: RAG Generation                    │
│                              │                                      │
│                              ▼                                      │
│                         Phase 2: Verilator Compile + Simulate       │
│                              │                                      │
│                              ▼                                      │
│                         Phase 3: VCD Waveform Critic                │
│                              │                                      │
│                         ┌────┴────┐                                 │
│                         │ Pass?   │                                  │
│                         └────┬────┘                                 │
│                      Yes │       │ No                               │
│                          ▼       ▼                                  │
│                      SUCCESS   Phase 4: LLM Self-Heal ──► Loop     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- **Python 3.10+**
- **Verilator 5.x** — `sudo pacman -S verilator` (Arch) or `sudo apt install verilator` (Debian/Ubuntu)
- **Gemini API Key** — Get one free from [Google AI Studio](https://aistudio.google.com/)

### Setup

```bash
git clone https://github.com/AnuragP004/RISC-V_RTL_RAG.git
cd RISC-V_RTL_RAG

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install vcdvcd google-generativeai chromadb python-dotenv tqdm

# Set your API key
echo "GEMINI_API_KEY=your_key_here" > pipeline/.env
```

### Run

```bash
# Full autonomous pipeline: generate → compile → simulate → heal
python3 main.py

# Generate a single module only (no simulation)
python3 main.py --target alu

# List all available modules
python3 main.py --list-modules

# Use a custom processor specification
python3 main.py --spec my_custom_spec.json
```

---

## Architecture

### Directory Structure

```
RISC-V_RTL_RAG/
├── main.py                      # ★ Unified push-button compiler (CLI)
├── processor_spec.json          # Configuration-driven module definitions
├── agentic_debug_loop.py        # Standalone Silicon Reflex debug script
├── sim_main.cpp                 # C++ Verilator simulation driver
├── rv32ui-p-add.hex             # RISC-V ADD test payload (x3 = 5+7 = 12)
│
├── pipeline/                    # RAG integration layer
│   ├── .env                     # API keys (not committed)
│   ├── chunk_verilog.py         # AST-aware Verilog chunker
│   ├── embed_and_store.py       # ChromaDB vector store builder
│   └── generate_rtl.py          # RAG-driven Verilog generation
│
├── [Verilog Core]
│   ├── rv32i_core.v             # Top-level stitcher (auto-heal target)
│   ├── alu.v                    # Arithmetic Logic Unit
│   ├── branch_unit.v            # Branch condition evaluator
│   ├── instruction_decoder.v    # RV32I instruction decoder
│   ├── program_counter.v        # PC with branch support
│   ├── register_file.v          # 32x32 register file
│   └── testbench.v              # Simulation harness
│
├── corpus/                      # Reference Verilog corpus for RAG
├── backups/                     # Auto-generated pre-patch snapshots
└── obj_dir/                     # Verilator build artifacts (generated)
```

### The Four Phases

| Phase | Module | What It Does |
|-------|--------|-------------|
| **Phase 1** | `run_initial_generation()` | Reads `processor_spec.json`, retrieves relevant Verilog chunks from ChromaDB, and prompts Gemini to generate each module with strict hardware rules. |
| **Phase 2** | `compile_and_simulate()` | Compiles all Verilog via `verilator -Wno-fatal --trace`, then executes the simulation binary to produce `simulation_trace.vcd`. |
| **Phase 3** | `check_waveforms()` | Parses the VCD trace using `vcdvcd`. Checks 4 signals for post-reset flatlines (with inherited reset value tracking). Verifies `x3 = 12` functionally. |
| **Phase 4** | `agentic_heal()` | On failure: backs up `rv32i_core.v`, injects ground-truth ALU encodings + locked interfaces into a diagnostic prompt, calls Gemini, validates the output, and overwrites. |

### Configuration-Driven Design

All module interfaces, constraints, verification signals, and ALU encodings live in `processor_spec.json`:

```json
{
  "modules": {
    "alu": {
      "file": "alu.v",
      "interface": "module alu (...);",
      "constraints": "Use ALU_ADD=4'b0000 encoding..."
    }
  },
  "verification": {
    "monitored_signals": { "pc": "TOP.testbench.dut.u_program_counter.pc[31:0]" },
    "functional_checks": [{ "signal": "...", "expected_value": 12 }]
  }
}
```

---

## Key Technical Decisions

### 1. `-Wno-fatal` for Verilator
The locked sub-module files trigger cosmetic warnings (`EOFNEWLINE`, `WIDTHTRUNC`, `CASEINCOMPLETE`). Using `-Wno-fatal` allows these to print without blocking compilation.

### 2. Inherited Reset Value in VCD Analysis
Signals set during reset (e.g., `reg_write=1` at t=1) that transition post-reset were falsely flagged as flatlined. Fixed by including the last value **at or before** the reset boundary as the inherited starting state.

### 3. Ground-Truth ALU Encoding Injection
The LLM hallucinated incorrect ALU control codes (e.g., `SUB=4'b0001` instead of `4'b1000`). The diagnostic prompt now injects the exact `localparam` values extracted from `alu.v`.

### 4. Structural Validation of LLM Output
Before overwriting any file, the script validates that the LLM response contains `module rv32i_core`, `endmodule`, and all required sub-module instantiations.

---

## RAG Pipeline

The knowledge base is built from a corpus of reference RISC-V Verilog implementations:

```bash
# 1. Chunk raw Verilog files into semantic units
python3 pipeline/chunk_verilog.py

# 2. Embed chunks into ChromaDB
python3 pipeline/embed_and_store.py
```

The chunker (`chunk_verilog.py`) is AST-aware — it splits along module boundaries and treats `always` blocks as atomic units, never splitting them mid-logic.

---

## Example Output

```
╔════════════════════════════════════════════════════════════════════════════╗
║                SILICON REFLEX — Push-Button RV32I Compiler                 ║
╚════════════════════════════════════════════════════════════════════════════╝

  Phase 1: All Verilog source files verified ✔

  Phase 2: Verilator compilation succeeded
           Simulation completed — VCD trace written

  Phase 3: VCD Waveform Critic
    🟢 pc                → ACTIVE
    🟢 reg_write         → ACTIVE
    🟢 alu_result        → ACTIVE
    🟢 write_data        → ACTIVE
    ✓ ADD test: x3 = 5 + 7 = 12 — PASSED ✅

╔════════════════════════════════════════════════════════════════════════════╗
║                       🎉  SUCCESS — CORE VERIFIED  🎉                        ║
╚════════════════════════════════════════════════════════════════════════════╝
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `vcdvcd` | VCD waveform parsing |
| `google-generativeai` | Gemini LLM API |
| `chromadb` | Vector database for RAG retrieval |
| `python-dotenv` | Environment variable loading |
| `tqdm` | Progress bars for embedding |
| **Verilator 5.x** | Verilog → C++ simulation |

---

## License

This project is for educational and competition use.
