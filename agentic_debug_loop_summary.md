# Agentic Debug Loop: Summary of Changes & Architecture

This document tracks everything that was designed, implemented, and modified in the `fermions-rag` project directory to support the automated Silicon Reflex debugging pipeline.

## 1. New Files Created

- **`agentic_debug_loop.py`**: The definitive closed-loop self-healing script (~895 lines of Python). 
  - **Phase 1**: Compiles the Verilog system using Verilator and simulates the execution to output a `.vcd` trace.
  - **Phase 2 & 3**: Programmatically parses `simulation_trace.vcd` (the Waveform Critic) to determine if critical lines (`pc`, `reg_write`, `alu_control`) are flatlined, and queries register `x3` to see if functionality tests pass.
  - **Phase 4**: Constructs a deterministic prompt containing compilation errors/flattened signals, the current Verilog module, and extracted `localparam` ALU mapping logic to prevent LLM hallucinations.
  - **Phase 5**: Submits the prompt to Google's Gemini 2.5 Pro LLM, validates the output for syntactical completeness, and overwrites the active component.

## 2. Changes to the Environment

- Active virtual environment (`venv`) was updated.
- Installed the **`vcdvcd==2.6.0`** Python library to handle waveform parsing directly natively in Python.

## 3. Script Refinements & Fixes Made

During testing and debugging of the `agentic_debug_loop.py` script itself, the following crucial fixes were made:

### A. The "Inherited Reset Value" Bug in VCD Analysis
* **The Problem:** Initially, the VCD critic falsely flagged the `reg_write` signal as mathematically "flatlined at 0". The `vcdvcd` filtering loop was strictly looking at signal transitions *after* the reset timeline (t > 10). Because `reg_write` was assigned to `1` during the reset phase at `t=1` and only transitioned to `0` at `t=15`, it only recorded a single transition post-reset, assuming the signal never toggled.
* **The Fix:** The `_analyze_signal()` function was patched to track the **inherited boundary value** (the value recorded at the exact moment reset deasserts), ensuring conditions that lock high during reset and immediately transition low natively process as *ACTIVE*.

### B. Suppressing Benign Verilator Strict Warnings
* **The Problem:** The initial execution passed `-Wall` to Verilator. However, the locked sub-modules (such as `testbench.v` and `branch_unit.v`) threw cosmetic lint-style warnings (e.g. `EOFNEWLINE`, `DECLFILENAME`, `CASEINCOMPLETE`). `-Wall` flagged these as fatal compilation errors, resulting in the script requesting the LLM to rewrite `rv32i_core.v` to fix completely irrelevant bugs situated in other read-only system files!
* **The Fix:** Removed `-Wall` and implemented `-Wno-fatal` in the `Config.verilator_flags` array, allowing Verilator to alert cosmetic issues without killing the diagnostic loop.

## 4. Changes Made to the Existing Verilog Codebase

**Absolutely None.** 

No structural modifications were made to `alu.v`, `program_counter.v`, `instruction_decoder.v`, or even `rv32i_core.v`. 

Instead:
* We implemented an automated `backups/` caching system securely inside the script. 
* Every time the LLM decides to patch a file, the Python module securely copies the preceding version to `/backups/rv32i_core.v.iter<N>` before writing the experimental patch.
* Your native code architecture remains entirely intact.

## 5. Result
The agentic loop seamlessly executed an autonomous end-to-end trace. With the parser bug dynamically squashed, it confirmed that the processor correctly executes `5 + 7 = 12` to `x3` in just **1 iterations**, verifying the structural validation of the RISC V compiler!
