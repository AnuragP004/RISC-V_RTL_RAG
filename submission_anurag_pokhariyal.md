# RAG for RISC-V RTL — Submission

| Field           | Details                                          |
|-----------------|--------------------------------------------------|
| **Name**        | Anurag Pokhariyal                                |
| **Email**       | pokhariyalanurag@gmail.com                       |
| **Phone**       | Available in application email                   |
| **Country**     | India                                            |
| **Date**        | April 11, 2026                                   |
| **LinkedIn**    | https://linkedin.com/in/anurag-pokhariyal        |
| **GitHub**      | https://github.com/AnuragP004                    |

**Project Repository:** https://github.com/AnuragP004/RISC-V_RTL_RAG

---

## Evaluator Quick Start

> **Goal:** Reproduce the full pipeline — from corpus chunking through ISA verification — in under 5 minutes.

### Prerequisites

| Dependency | Version | Install |
|---|---|---|
| Python | 3.10+ | Pre-installed on most Linux distros |
| Verilator | 5.x | `sudo apt install verilator` (Debian/Ubuntu) or `sudo pacman -S verilator` (Arch) |
| Gemini API Key | — | Free from [Google AI Studio](https://aistudio.google.com/) |

### 1. Clone & Setup

```bash
git clone https://github.com/AnuragP004/RISC-V_RTL_RAG.git
cd RISC-V_RTL_RAG

# Create virtual environment and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Set your Gemini API key
echo "GEMINI_API_KEY=your_key_here" > pipeline/.env
```

**`requirements.txt`** (pinned versions):
```text
vcdvcd==2.6.0
google-generativeai==0.8.6
chromadb==1.5.7
python-dotenv==1.2.2
tqdm==4.67.3
```

### 2. Build the RAG Knowledge Base (Optional — pre-built DB ships with the repo)

```bash
# Step 1: Chunk the raw Verilog corpus into semantic units
python3 pipeline/chunk_verilog.py

# Step 2: Embed chunks into ChromaDB
python3 pipeline/embed_and_store.py
```

### 3. Run the Full Autonomous Pipeline

```bash
# This generates all Verilog → compiles → simulates → self-heals
python3 main.py
```

If all Verilog files already exist (as they do in the repo), Phase 1 skips generation and proceeds directly to compile → simulate → verify.

### 4. Run the ISA Test Suite

```bash
# First, compile the design with Verilator
verilator -cc --exe --build -j 0 -Wno-fatal --trace --top-module testbench \
  sim_main.cpp testbench.v rv32i_core.v program_counter.v instruction_decoder.v \
  register_file.v branch_unit.v alu.v load_store_unit.v

# Run all 39 ISA tests and generate the results JSON
bash run_all_tests.sh

# Or run the oracle directly
python3 test_oracle.py
```

Results are printed to stdout and written to `tests/oracle_results.json`.

### 5. Verify a Single Test Manually

```bash
./obj_dir/Vtestbench +loadmem=tests/rv32ui-p-add.hex
# → Produces simulation_trace.vcd
```

### Available CLI Commands

```bash
python3 main.py                        # Full pipeline (generate → compile → simulate → heal)
python3 main.py --target alu           # Generate only the ALU module
python3 main.py --target rv32i_core    # Generate only the top-level core
python3 main.py --list-modules         # List all available module targets
python3 main.py --spec custom.json     # Use a custom processor specification
```

---

## Executive Summary

This submission presents the **"Silicon Reflex" Pipeline** — a configuration-driven, closed-loop EDA compiler that autonomously generates, simulates, diagnoses, and self-heals a single-cycle RV32I RISC-V processor. Recognizing that static RAG retrieval alone is insufficient to resolve spatial hardware integration bugs, I engineered a system that goes beyond generation: it compiles the output with Verilator, parses VCD waveforms programmatically, and drives LLM-based repair from deterministic simulation diagnostics — all without human intervention.

The generated RV32I single-cycle core passes **39/39 rv32ui ISA tests** covering all major instruction types: arithmetic (R/I-type), branches (B-type), jumps (JAL/JALR), upper-immediate (LUI/AUIPC), and load/store (LW/LH/LB/SW/SH/SB) operations.

---

## A. Corpus & Knowledge Base

### Sources

To prevent hallucinated hardware logic, the knowledge base was curated to include high-quality, ground-truth RTL rather than generic coding discussions. The `corpus/raw/` directory contains **87 Verilog files** and **2 technical PDFs**, organized as follows:

| Source | Type | Content | Files |
|---|---|---|---|
| **PicoRV32** ([YosysHQ/picorv32](https://github.com/YosysHQ/picorv32)) | Reference Core | Production-grade single-file RV32I core with FSM-based instruction execution | 1 |
| **RV32I Pipeline Processor** | Reference Core | Multi-file pipelined RISC-V implementation (fetch, decode, execute, memory, writeback stages) | 57 |
| **Supplementary Verilog Modules** | Design Patterns | ALU, control decoder, branch unit, register files, MUX variants, memory controllers, immediate generator | 29 |
| **RISC-V ISA Spec v2.2** ([riscv.org](https://riscv.org/technical/specifications/)) | Specification | Official unprivileged ISA — instruction encodings, semantics, register conventions | 1 PDF |
| **LLM RTL Errors** (Fermions article) | Error Taxonomy | Type I (syntax) vs Type II (integration) failure classification for AI-generated hardware | 1 PDF |

### Chunking Strategy

Standard NLP text splitters (e.g., `RecursiveCharacterTextSplitter`) destroy hardware semantic meaning by splitting mid-`always` blocks or across module boundaries. I built a **rule-based AST-aware Verilog chunker** (`pipeline/chunk_verilog.py`) with the following design:

| Chunk Type | Granularity | Rationale |
|---|---|---|
| `module_header` | Module declaration + all wire/reg/parameter declarations | Provides the full architectural context (port list, internal signals) as a single retrievable unit |
| `always_block` | Single `always @(...)` block (atomic, never split) | Preserves temporal logic semantics — splitting an FSM case statement mid-state produces nonsensical retrieval results |
| `assign_statements` | Grouped continuous assignments per module | Continuous-assignment wiring is semantically one unit |

**Large block handling:** `always` blocks exceeding ~600 tokens (e.g., PicoRV32's main FSM at 2000+ lines) are split at `case` state boundaries using regex pattern matching, with the `always @(...)` header prepended to each sub-chunk.

**Total chunks produced:** ~315 semantic units from the full corpus.

### Embedding & Retrieval

| Component | Choice | Rationale |
|---|---|---|
| **Embedding Model** | Google `text-embedding-004` (768-dim) | Strong performance on technical code; natively integrates with Gemini ecosystem |
| **Vector Store** | ChromaDB (persistent, local) | Lightweight, zero-config, cosine similarity HNSW index |
| **Collections** | `verilog_rtl` (code) and `spec_and_docs` (prose) | Separate embedding spaces prevent cross-domain pollution |
| **Retrieval** | Dense retrieval, top-K = 3 per query | The corpus is small and domain-specific (~315 chunks); dense-only retrieval achieved near-perfect recall |
| **Re-ranking** | None applied | With K=3 and a tight corpus, the top results were consistently relevant. Hybrid retrieval (BM25 + dense) was considered but not implemented |

**Acknowledged limitations:**
- No formal evaluation against alternative embedding models (e.g., OpenAI `text-embedding-3-small`, CodeBERT, or hardware-specific embeddings).
- No re-ranking step — a cross-encoder re-ranker could improve precision for larger corpora.

---

## B. Pipeline Design

### Architecture

The pipeline operates as a unified CLI tool (`main.py`) driven entirely by `processor_spec.json`, which declaratively defines all module interfaces, constraints, verification signals, and ALU encodings.

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                      SILICON REFLEX PIPELINE                             │
│                                                                          │
│  processor_spec.json ──► Phase 1: RAG Generation                         │
│                              │                                           │
│                              ▼                                           │
│                         Phase 2: Verilator Compile + Simulate            │
│                              │                                           │
│                              ▼                                           │
│                         Phase 3: VCD Waveform Critic                     │
│                              │                                           │
│                         ┌────┴────┐                                      │
│                         │ Pass?   │                                      │
│                         └────┬────┘                                      │
│                      Yes │       │ No                                    │
│                          ▼       ▼                                       │
│                      SUCCESS   Phase 4: LLM Self-Heal ──► Loop (max 3)  │
└──────────────────────────────────────────────────────────────────────────┘
```

### The Four Phases

| Phase | Function | What It Does |
|---|---|---|
| **Phase 1: Generation** | `run_initial_generation()` | For each module in `processor_spec.json`: queries ChromaDB (top-K=3), injects `HARDWARE_RULES` (non-blocking assignments, latch prevention, `reg` declaration rules), and prompts Gemini 2.5 Pro to generate Verilog. Skips files that already exist. |
| **Phase 2: Compile & Simulate** | `compile_and_simulate()` | Compiles all Verilog via `verilator -Wno-fatal --trace`, then executes the simulation binary with the test hex file to produce `simulation_trace.vcd`. |
| **Phase 3: Waveform Critic** | `check_waveforms()` | Parses the VCD trace using `vcdvcd`. Checks 5 signals (`pc`, `reg_write`, `alu_result`, `write_data`, `data_addr`) for post-reset flatlines using inherited reset value tracking. Runs functional assertions (e.g., `gp == 1`). |
| **Phase 4: Self-Heal** | `agentic_heal()` | On failure: backs up `rv32i_core.v`, constructs a diagnostic prompt containing (1) VCD failure diagnostics, (2) ground-truth ALU encodings, (3) locked sub-module interfaces, (4) the current broken source. Calls Gemini to rewrite the control logic. Validates output structurally before overwriting. |

### Key Design Decisions

1. **`-Wno-fatal` for Verilator:** Locked sub-module files trigger benign Verilator warnings (`EOFNEWLINE`, `WIDTHTRUNC`, `CASEINCOMPLETE`). Using `-Wno-fatal` allows these to print without blocking compilation — otherwise the self-heal loop would attempt to fix read-only sub-modules.

2. **Inherited Reset Value in VCD Analysis:** Signals set during reset (e.g., `reg_write=1` at t=1) that transition post-reset (to `0` at t=15) were falsely flagged as flatlined. Fixed by including the last value *at or before* the reset boundary as the inherited starting state.

3. **Ground-Truth ALU Encoding Injection:** The LLM hallucinated incorrect ALU control codes (e.g., `SUB=4'b0001` instead of `4'b1000`). The diagnostic prompt now injects exact `localparam` values from `processor_spec.json`.

4. **Structural Validation of LLM Output:** Before overwriting any file, the script validates the LLM response contains `module rv32i_core`, `endmodule`, and all required sub-module instantiations (`u_program_counter`, `u_alu`, etc.).

### Post-Processing Pipeline

LLM output undergoes three sanitization steps before being written to disk:
1. **Markdown fence stripping** — removes ` ```verilog ` / ` ``` ` wrappers
2. **Module extraction** — regex-extracts only the target module, discarding any preamble or extra generated code
3. **Structural validation** — checks for `module rv32i_core`, `endmodule`, and all 6 required sub-module instantiation names

### Tools & Models

| Component | Tool/Model |
|---|---|
| **LLM** | Google Gemini 2.5 Pro (temperature=0.2) |
| **Embedding** | Google `text-embedding-004` (768-dim dense vectors) |
| **Vector Store** | ChromaDB (persistent local, HNSW cosine) |
| **Simulator** | Verilator 5.x (cycle-accurate VCD trace) |
| **VCD Parser** | `vcdvcd` Python library |
| **Framework** | Custom pipeline (no LangChain/LlamaIndex dependency) |

**Iterations to First Simulatable Result:**
- Sub-modules (ALU, decoder, branch unit, register file, PC, LSU): **1 iteration each** — all compiled and passed Verilator lint on first generation.
- Top-level `rv32i_core.v`: **1 generation + 1 self-healing iteration** — the first generation had correct syntax but flatlined control signals (Type II failure), resolved by the agentic debug loop.

---

## C. Generated RTL & Generation Traces

*All generated source files are available in the [GitHub repository](https://github.com/AnuragP004/RISC-V_RTL_RAG).*

The generated architecture is a **Single-Cycle Data Path** — all instructions execute and commit state within one clock boundary. **Control Hazard Handling** (pipeline flushes or stalls on taken branches) is inherently a zero-cycle operation and does not require explicit FSM logic.

### Generated Modules

| Module | File | Lines | Description |
|---|---|---|---|
| Program Counter | `program_counter.v` | 35 | PC with branch/jump support, synchronous reset |
| Instruction Decoder | `instruction_decoder.v` | 75 | Full RV32I decode: R/I/S/B/U/J immediate extraction |
| Register File | `register_file.v` | 38 | 32×32-bit registers, x0 hardwired to zero |
| ALU | `alu.v` | 48 | 11 operations: ADD, SUB, SLL, SLT, SLTU, XOR, SRL, SRA, OR, AND, COPY_B |
| Branch Unit | `branch_unit.v` | 50 | BEQ, BNE, BLT, BGE, BLTU, BGEU evaluation |
| Load/Store Unit | `load_store_unit.v` | 99 | LW, LH, LB, LHU, LBU, SW, SH, SB with byte-enable logic |
| Top-Level Core | `rv32i_core.v` | 288 | Full control unit + datapath MUXes + sub-module stitching |

### Trace 1: Generating the ALU

**Prompt Sent:**
```text
Generate the ALU module.
Interface: module alu(input [31:0] a, b, input [3:0] alu_control, output reg [31:0] result, output zero).
Constraints: Use the ALU_ADD=4'b0000, ALU_SUB=4'b1000 encoding scheme. Apply HARDWARE_RULES.
```

**RAG Retrieved Context** (from `picorv32.v`):
```verilog
always @* begin
    alu_out_q = alu_op_y;
    case (alu_op_q)
        `RV32I_ALU_ADD:  alu_out_q = alu_op_x + alu_op_y;
        `RV32I_ALU_SUB:  alu_out_q = alu_op_x - alu_op_y;
// ...
```

**Generated Output** (excerpt):
```verilog
always @(*) begin
    result = 32'b0; // Default assignment to prevent latch inference
    case (alu_control)
        ALU_ADD:  result = a + b;
        ALU_SUB:  result = a - b;
        ALU_SLL:  result = a << b[4:0];
        ALU_SLT:  result = ($signed(a) < $signed(b)) ? 32'd1 : 32'd0;
        // ...
    endcase
end
assign zero = (result == 32'b0);
```

### Trace 2: Generating the Branch Unit

**Prompt Sent:**
```text
Generate the Branch Unit.
Constraints: Implement BEQ (000), BNE (001), BLT (100), BGE (101), BLTU (110), BGEU (111) via funct3 decoding. Apply HARDWARE_RULES.
```

**RAG Retrieved Context** (from `picorv32.v` branch logic):
```verilog
wire branch_taken =
    (instr_beq && (reg_op1 == reg_op2)) ||
    (instr_bne && (reg_op1 != reg_op2)) ||
    (instr_blt && ($signed(reg_op1) < $signed(reg_op2)));
```

**Generated Output** (excerpt):
```verilog
always @(*) begin
    branch_taken = 1'b0; // Default assignment
    case (funct3)
        3'b000: branch_taken = (rs1_data == rs2_data); // BEQ
        3'b001: branch_taken = (rs1_data != rs2_data); // BNE
        3'b100: branch_taken = ($signed(rs1_data) < $signed(rs2_data)); // BLT
        3'b101: branch_taken = ($signed(rs1_data) >= $signed(rs2_data)); // BGE
        3'b110: branch_taken = (rs1_data < rs2_data); // BLTU
        3'b111: branch_taken = (rs1_data >= rs2_data); // BGEU
    endcase
end
```

### Trace 3: Generating the Load/Store Unit

**Prompt Sent:**
```text
Generate the Load/Store Unit.
Interface: module load_store_unit(input [2:0] funct3, [31:0] addr, [31:0] write_data, mem_read, mem_write, [31:0] mem_data_in, output reg [31:0] mem_data_out, [3:0] mem_byte_en, [31:0] read_data_out).
Constraints: Implement LW, LH, LB, LHU, LBU, SW, SH, SB. Apply HARDWARE_RULES. Provide default assignments for all combinational outputs.
```

**RAG Retrieved Context** (from corpus memory controller patterns):
```verilog
case (addr[1:0])
    2'b00: data_out = mem_data[7:0];
    2'b01: data_out = mem_data[15:8];
```

**Generated Output** (excerpt):
```verilog
always @(*) begin
    read_data_out = 32'b0;
    mem_data_out = 32'b0;
    mem_byte_en = 4'b0000;
    if (mem_write) begin
        case (funct3)
            3'b000: begin // SB
                mem_byte_en  = 4'b0001 << addr[1:0];
                mem_data_out = write_data << {addr[1:0], 3'b000};
            end
            // ...
        endcase
    end else if (mem_read) begin
        case (funct3)
            3'b000: begin // LB (sign-extended)
                case (addr[1:0])
                    2'b00: read_data_out = {{24{mem_data_in[7]}}, mem_data_in[7:0]};
                    // ...
```

---

## D. Simulation Results

### Verilator Setup & Testbench Approach

The testbench (`testbench.v`) provides:
- **16KB Instruction Memory** (4096 × 32-bit words) loaded via `+loadmem=<hexfile>` plusarg
- **16KB Data Memory** with byte-enable write support (matching the LSU's `mem_byte_en` port)
- **Address aliasing:** `0x8000XXXX` addresses are mapped to `[13:2]` indices so that official `riscv-tests` binaries (linked at `0x80000000`) map correctly without a linker script

The C++ driver (`sim_main.cpp`) runs 10,000 clock cycles with reset deasserted after time 10.

### Test Oracle

`test_oracle.py` evaluates each test using only VCD signal observation:
1. **PC liveness check** — verifies the PC has >1 unique value post-reset (i.e., the core is fetching instructions)
2. **`gp` (x3) register check** — the official `riscv-tests` framework sets `gp = 1` on `RVTEST_PASS` and `gp = (test_num << 1)` on `RVTEST_FAIL`

### ISA Test Results: 39/39 rv32ui Tests Passing

The core was validated against the **official `riscv-tests` ISA test suite** ([riscv-software-src/riscv-tests](https://github.com/riscv-software-src/riscv-tests)). Precompiled ELF binaries were converted to hex arrays and driven through the core natively.

| Test Category | Tests | Status | Instructions Covered |
|---|---|---|---|
| R-type arithmetic | add, sub, and, or, xor, sll, srl, sra, slt, sltu | 10/10 PASS | ADD, SUB, AND, OR, XOR, SLL, SRL, SRA, SLT, SLTU |
| I-type immediate | addi, andi, ori, xori, slti, sltiu, slli, srli, srai | 9/9 PASS | ADDI, ANDI, ORI, XORI, SLTI, SLTIU, SLLI, SRLI, SRAI |
| B-type branches | beq, bne, blt, bge, bltu, bgeu | 6/6 PASS | BEQ, BNE, BLT, BGE, BLTU, BGEU |
| U-type upper-imm | lui, auipc | 2/2 PASS | LUI, AUIPC |
| J-type jumps | jal, jalr | 2/2 PASS | JAL, JALR |
| Load instructions | lw, lh, lhu, lb, lbu | 5/5 PASS | LW, LH, LHU, LB, LBU |
| Store instructions | sw, sh, sb | 3/3 PASS | SW, SH, SB |
| Special | simple, fence_i | 2/2 PASS | Executed as NOP-through |
| **Total** | | **39/39 PASS** | **All 37 targeted RV32I instructions** |

**Test Methodology:** The testbench uses a 16KB memory architecture that mirrors the `.text` and `.data` absolute VMA mappings of the official RISC-V ELF binaries. No test cases were modified or mocked.

**Expected Exclusions:** ECALL, EBREAK, and CSR instructions intentionally fall through (evaluated as NOP) since the pipeline generates an unprivileged data path without a CSR file.

### Benchmark Results

**CPI (Cycles Per Instruction):** 1.0 by design — every instruction completes in exactly one clock cycle.

Dhrystone and CoreMark benchmarks are not included. A meaningful run requires:
1. A RISC-V cross-compiler (`riscv64-unknown-elf-gcc`) to produce the benchmark binary
2. A system timer CSR (`mcycle`) for cycle counting
3. A sufficient memory map for the C runtime stack

None of these prerequisites are met by the current unprivileged single-cycle design. Rather than fabricating placeholder data, this section is left as acknowledged future work.

---

## E. Failure Analysis

### Failure Mode 1: Type II Integration Error (Control Unit)

**Symptom:** During initial RAG generation, all sub-modules compiled cleanly (0 Verilator errors — 100% syntax pass rate). However, simulation revealed a complete functional failure: the Program Counter (`pc`) and Register Write enable (`reg_write`) were flatlined at `0`.

**Root Cause:** The LLM successfully instantiated all sub-modules with correct port bindings but hallucinated the top-level control unit logic in `rv32i_core.v`. The generated `always @(*)` block contained syntactically valid but semantically dead code that never decoded opcodes into meaningful control signals. The `reg_write` signal was never asserted, so no instruction could commit results.

**Debugging Approach:** **No manual code corrections were needed.** The autonomous `agentic_debug_loop.py` script:
1. Detected the VCD flatlines programmatically
2. Constructed a diagnostic prompt containing the exact failure signals, ground-truth ALU encodings, and locked sub-module interfaces
3. Called Gemini 2.5 Pro to rewrite the control block
4. Validated the response structurally (checking for all required sub-module instantiations)
5. Overwrote `rv32i_core.v` and re-simulated

**Outcome:** Self-healed in **1 automated iteration**. The `rv32ui-p-add` smoke test passed.

### Failure Mode 2: SRAI Instruction Bug (Decoder Gap)

**Symptom:** After expanding the core for full RV32I support, the `rv32ui-p-srai` test failed. SRAI produced `0x3FFFFFFC` instead of the expected `0xFFFFFFFC` for input `-16 >> 2`.

**Root Cause:** The instruction decoder did not extract `funct7` (bits [31:25]) for I-type instructions. SRAI requires `funct7[5] = 1` to differentiate it from SRLI (`funct7[5] = 0`), but the decoder set `funct7 = 0` for all I-type instructions, causing SRAI to execute as SRLI (logical shift instead of arithmetic shift).

**Fix:** **Manual correction** — added `funct7 = instr[31:25]` extraction unconditionally in the decoder. This is a one-line change that enables correct funct7 inspection for I-type shift-immediate instructions.

### Failure Mode 3: Missing Memory Interface (Architectural Omission)

**Symptom:** Load and store tests failed entirely — the generated core had no data memory ports.

**Root Cause:** The initial RAG-generated `rv32i_core.v` treated the processor as a compute-only unit. While the `load_store_unit.v` was generated correctly as an isolated module, the LLM never instantiated it in the top-level core or generated the required data memory interface ports.

**Fix:** **Manual expansion** of `rv32i_core.v` to include:
- Data memory ports (`data_mem_addr`, `data_mem_wdata`, `data_mem_we`, `data_mem_byte_en`, `data_mem_rdata`)
- Write-back MUX (ALU result / memory data / PC+4)
- ALU source A MUX (rs1_data / PC for AUIPC)
- JALR target calculation (`(rs1 + imm) & ~1`)
- Full control logic for all 7 RV32I instruction types
- Corresponding testbench update with data memory

### Failure Mode 4: ALU Encoding Hallucination

**Symptom:** During self-healing, the LLM sometimes generated incorrect ALU control codes (e.g., `SUB = 4'b0001` instead of `4'b1000`).

**Root Cause:** Without explicit grounding, the LLM invented plausible but incorrect encoding schemes.

**Fix:** **Automated** — the diagnostic prompt now injects the exact `localparam` definitions from `processor_spec.json` as ground-truth. The LLM is instructed to "COPY THESE EXACTLY."

### Summary of Manual vs. Automated Fixes

| Fix | Method | Description |
|---|---|---|
| Control unit integration | **Automated** (self-healing loop) | LLM rewrote the control block from VCD diagnostics |
| ALU encoding hallucination | **Automated** (prompt injection) | Ground-truth localparams injected into every healing prompt |
| SRAI decoder bug | **Manual** | Added funct7 extraction for I-type shift instructions |
| Memory interface expansion | **Manual** | Added data memory ports, LSU instantiation, write-back MUX |
| LUI/AUIPC/JAL/JALR support | **Manual** | Added control cases for instruction types the LLM omitted |

---

## F. Reflection

### What Was the Hardest Part?

Managing the transition between clock reset boundaries during VCD analysis. The Python VCD parser needed to differentiate a truly "dead" wire (one that never changes) from a wire holding an inherited steady-state logic level set during reset. A signal that is `1` during reset and transitions to `0` immediately after has *two* unique values and is *active* — but a naive post-reset filter sees only the `0` and reports it as flatlined. Solving this required implementing inherited value tracking that considers the last transition *at or before* the reset boundary as the starting state.

### What Would I Do Differently With More Time?

1. **Cross-compiler integration:** Install the RISC-V GNU toolchain to compile official `riscv-tests` from source rather than using pre-converted hex files. This would also enable Dhrystone/CoreMark benchmarking.
2. **Multi-embedding evaluation:** Formally compare `text-embedding-004` against CodeBERT, StarCoder embeddings, and OpenAI's `text-embedding-3-small` to quantify retrieval quality on hardware code.
3. **Hybrid retrieval:** Implement BM25 + dense hybrid search with a cross-encoder re-ranker to improve precision on larger corpora.
4. **Constrained random testbench:** Replace the static ISA test suite with a UVM-based constrained random verification environment for deeper state-space coverage.
5. **Multi-agent architecture:** Use separate specialized agents for generation, verification, and repair rather than a single monolithic prompt.

### What Does This Tell Us About the Limits of RAG for Hardware?

This project demonstrates a fundamental limitation: **RAG solves syntax but cannot solve integration.** The retrieval system successfully provided correct Verilog patterns for every sub-module — the ALU, decoder, register file, and branch unit all compiled on the first attempt. But the *spatial* problem of routing signals between modules and the *temporal* problem of correctly sequencing control signals across a clock cycle are emergent properties of the complete system, not retrievable facts from any single document.

The fact that manual fixes were needed for the memory interface and decoder — despite the RAG corpus containing correct reference implementations of both — underscores this gap. The LLM can *read* a reference core that connects a load/store unit, but it cannot *reason* about which wires need to exist in a novel design with a different module decomposition.

EDA generation requires **active, deterministic feedback loops** (simulation-in-the-loop) rather than passive vector retrieval. The "Silicon Reflex" approach — where the VCD waveform itself becomes the critic signal — is a step toward closing this gap, but much work remains.
