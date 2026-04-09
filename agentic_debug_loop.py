#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                      SILICON REFLEX — Agentic Debug Loop                    ║
║                                                                              ║
║  Closed-loop self-healing pipeline for RV32I processor integration.          ║
║  Uses VCD waveform traces as a deterministic critic signal to drive          ║
║  LLM-based repair of the top-level stitcher (rv32i_core.v).                 ║
║                                                                              ║
║  Author : Fermions RAG Pipeline                                             ║
║  Target : RV32I Single-Cycle Core (RV32I subset)                            ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import re
import shutil
import subprocess
import textwrap
import time
import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

import google.generativeai as genai
from vcdvcd import VCDVCD

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Config:
    """All tunable parameters for the agentic loop."""

    # --- Paths ---
    project_root: Path = Path(__file__).parent.resolve()
    core_verilog: Path = field(default=None)
    testbench_verilog: Path = field(default=None)
    sim_main_cpp: Path = field(default=None)
    vcd_file: Path = field(default=None)
    alu_verilog: Path = field(default=None)
    hex_file: str = "rv32ui-p-add.hex"
    obj_dir: Path = field(default=None)
    backup_dir: Path = field(default=None)

    # --- Verilator ---
    verilator_bin: str = "verilator"
    verilator_flags: list = field(default_factory=lambda: [
        "--cc", "--trace", "--exe", "--build",
        "-Wno-fatal",
    ])
    top_module: str = "testbench"

    # --- VCD Signal Paths (verified from actual trace) ---
    sig_pc: str = "TOP.testbench.dut.u_program_counter.pc[31:0]"
    sig_reg_write: str = "TOP.testbench.dut.reg_write"
    sig_alu_result: str = "TOP.testbench.dut.alu_result[31:0]"
    sig_opcode: str = "TOP.testbench.dut.opcode[6:0]"
    sig_write_data: str = "TOP.testbench.dut.write_data[31:0]"
    sig_reset: str = "TOP.testbench.reset"
    sig_alu_control: str = "TOP.testbench.dut.alu_control[3:0]"

    # --- LLM ---
    gemini_model: str = "gemini-2.5-pro"
    max_iterations: int = 5
    temperature: float = 0.2  # Low temp for deterministic code generation

    # --- Test Program (rv32ui-p-add.hex) ---
    # ADDI x1, x0, 5    -> 00500093
    # ADDI x2, x0, 7    -> 00700113
    # ADD  x3, x1, x2   -> 002081b3
    # JAL  x0, 0 (loop) -> 0000006f
    expected_final_x3: int = 12  # 5 + 7

    # --- Timing ---
    reset_deassert_time: int = 10  # sim_main.cpp deasserts reset after time 10

    def __post_init__(self):
        self.core_verilog = self.project_root / "rv32i_core.v"
        self.testbench_verilog = self.project_root / "testbench.v"
        self.sim_main_cpp = self.project_root / "sim_main.cpp"
        self.vcd_file = self.project_root / "simulation_trace.vcd"
        self.alu_verilog = self.project_root / "alu.v"
        self.obj_dir = self.project_root / "obj_dir"
        self.backup_dir = self.project_root / "backups"


# ═══════════════════════════════════════════════════════════════════════════════
# RICH TERMINAL OUTPUT
# ═══════════════════════════════════════════════════════════════════════════════

class Log:
    """Structured, color-coded terminal logging."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    DIM = "\033[2m"

    @staticmethod
    def banner(text: str):
        width = 78
        border = "═" * width
        print(f"\n{Log.CYAN}╔{border}╗{Log.RESET}")
        for line in text.split("\n"):
            padded = line.center(width)
            print(f"{Log.CYAN}║{Log.BOLD}{padded}{Log.RESET}{Log.CYAN}║{Log.RESET}")
        print(f"{Log.CYAN}╚{border}╝{Log.RESET}\n")

    @staticmethod
    def phase(icon: str, text: str):
        print(f"\n{Log.BOLD}{Log.BLUE}{'─'*60}{Log.RESET}")
        print(f"{Log.BOLD}{Log.BLUE}  {icon}  {text}{Log.RESET}")
        print(f"{Log.BOLD}{Log.BLUE}{'─'*60}{Log.RESET}")

    @staticmethod
    def ok(msg: str):
        print(f"  {Log.GREEN}✓{Log.RESET} {msg}")

    @staticmethod
    def fail(msg: str):
        print(f"  {Log.RED}✗{Log.RESET} {msg}")

    @staticmethod
    def warn(msg: str):
        print(f"  {Log.YELLOW}⚠{Log.RESET} {msg}")

    @staticmethod
    def info(msg: str):
        print(f"  {Log.DIM}ℹ{Log.RESET} {msg}")

    @staticmethod
    def signal(name: str, status: str, detail: str = ""):
        icon = "🟢" if status == "ACTIVE" else "🔴"
        color = Log.GREEN if status == "ACTIVE" else Log.RED
        extra = f" {Log.DIM}({detail}){Log.RESET}" if detail else ""
        print(f"    {icon} {color}{name:30s}{Log.RESET} → {status}{extra}")

    @staticmethod
    def iteration_header(n: int, max_n: int):
        Log.banner(f"ITERATION {n} / {max_n}\n{datetime.now().strftime('%H:%M:%S')}")


# ═══════════════════════════════════════════════════════════════════════════════
# DIAGNOSTIC DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SignalDiag:
    """Diagnostic for a single VCD signal."""
    name: str
    is_flatlined: bool
    flatline_value: Optional[str] = None
    num_transitions: int = 0
    unique_values: list = field(default_factory=list)
    sample_transitions: list = field(default_factory=list)  # first N (time, value) pairs

    @property
    def status(self) -> str:
        return "FLATLINED" if self.is_flatlined else "ACTIVE"


@dataclass
class VCDDiagnostic:
    """Aggregated diagnostic from VCD analysis."""
    pc: SignalDiag = None
    reg_write: SignalDiag = None
    alu_result: SignalDiag = None
    alu_control: SignalDiag = None
    write_data: SignalDiag = None

    @property
    def has_critical_failure(self) -> bool:
        """True if the core is fundamentally broken (PC or reg_write dead)."""
        return (self.pc and self.pc.is_flatlined) or \
               (self.reg_write and self.reg_write.is_flatlined)

    @property
    def all_signals_active(self) -> bool:
        """True if all monitored signals show activity."""
        signals = [self.pc, self.reg_write, self.alu_result]
        return all(s and not s.is_flatlined for s in signals)

    def summary(self) -> str:
        lines = []
        for sig in [self.pc, self.reg_write, self.alu_result, self.alu_control, self.write_data]:
            if sig:
                status = "FLATLINED" if sig.is_flatlined else "ACTIVE"
                lines.append(
                    f"  {sig.name}: {status} "
                    f"(transitions={sig.num_transitions}, "
                    f"unique_values={len(sig.unique_values)})"
                )
                if sig.sample_transitions:
                    for t, val in sig.sample_transitions[:5]:
                        lines.append(f"    t={t}: {val}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1: COMPILE & SIMULATE
# ═══════════════════════════════════════════════════════════════════════════════

def compile_and_simulate(cfg: Config) -> tuple[bool, str]:
    """
    Runs the full Verilator compile + simulation pipeline.

    Steps:
      1. Verilator: lint, compile to C++, and build the executable.
      2. Execute the simulation binary with +loadmem to load the hex test.

    Returns:
        (success: bool, log_output: str)
    """
    Log.phase("🔧", "PHASE 1: COMPILE & SIMULATE")

    all_verilog = [
        str(cfg.testbench_verilog),
        str(cfg.core_verilog),
        str(cfg.project_root / "program_counter.v"),
        str(cfg.project_root / "instruction_decoder.v"),
        str(cfg.project_root / "register_file.v"),
        str(cfg.project_root / "branch_unit.v"),
        str(cfg.project_root / "alu.v"),
    ]

    # --- Step 1: Verilator compilation ---
    verilator_cmd = [
        cfg.verilator_bin,
        *cfg.verilator_flags,
        f"--top-module", cfg.top_module,
        str(cfg.sim_main_cpp),
        *all_verilog,
    ]

    Log.info(f"Verilator command: {' '.join(verilator_cmd[:6])} ...")

    compile_result = subprocess.run(
        verilator_cmd,
        cwd=str(cfg.project_root),
        capture_output=True,
        text=True,
        timeout=120,
    )

    if compile_result.returncode != 0:
        error_log = compile_result.stderr + compile_result.stdout
        Log.fail("Verilator compilation FAILED")
        # Print only the first 30 lines to avoid flooding the terminal
        for line in error_log.strip().split("\n")[:30]:
            print(f"    {Log.RED}{line}{Log.RESET}")
        return False, error_log

    Log.ok("Verilator compilation succeeded")

    # --- Step 2: Run the simulation ---
    sim_binary = str(cfg.obj_dir / f"V{cfg.top_module}")
    sim_cmd = [sim_binary, "+loadmem"]

    Log.info(f"Running simulation: {' '.join(sim_cmd)}")

    sim_result = subprocess.run(
        sim_cmd,
        cwd=str(cfg.project_root),
        capture_output=True,
        text=True,
        timeout=30,
    )

    if sim_result.returncode != 0:
        error_log = sim_result.stderr + sim_result.stdout
        Log.fail("Simulation execution FAILED")
        for line in error_log.strip().split("\n")[:20]:
            print(f"    {Log.RED}{line}{Log.RESET}")
        return False, error_log

    Log.ok("Simulation completed — VCD trace written")

    combined_log = compile_result.stderr + compile_result.stdout + \
                   sim_result.stderr + sim_result.stdout
    return True, combined_log


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2: VCD WAVEFORM CRITIC
# ═══════════════════════════════════════════════════════════════════════════════

def _analyze_signal(vcd: VCDVCD, signal_name: str,
                    reset_time: int = 10) -> SignalDiag:
    """
    Analyze a single VCD signal for flatline behavior.

    A signal is considered 'flatlined' if it has ≤ 1 unique value
    during the post-reset execution window.

    Crucially, we include the *inherited* value at the reset boundary —
    i.e., the last transition before reset deasserts — since that value
    is still active during post-reset execution.
    """
    try:
        sig = vcd[signal_name]
    except KeyError:
        Log.warn(f"Signal '{signal_name}' not found in VCD")
        return SignalDiag(
            name=signal_name,
            is_flatlined=True,
            flatline_value="SIGNAL_NOT_FOUND",
            num_transitions=0,
        )

    all_tv = sig.tv
    if not all_tv:
        return SignalDiag(
            name=signal_name,
            is_flatlined=True,
            flatline_value="NO_DATA",
            num_transitions=0,
        )

    # Collect transitions strictly after reset
    post_reset = [(t, v) for (t, v) in all_tv if t > reset_time]

    # Find the inherited value: the last transition AT or BEFORE reset_time.
    # This is the value the signal holds when reset deasserts.
    inherited_value = None
    for t, v in all_tv:
        if t <= reset_time:
            inherited_value = v
        else:
            break

    # Build the complete set of values active during post-reset execution
    active_values = []
    if inherited_value is not None:
        active_values.append(inherited_value)
    active_values.extend(v for _, v in post_reset)

    # Include the inherited value as a synthetic "starting state" transition
    all_post_reset = []
    if inherited_value is not None:
        all_post_reset.append((reset_time, inherited_value))
    all_post_reset.extend(post_reset)

    if not active_values:
        return SignalDiag(
            name=signal_name,
            is_flatlined=True,
            flatline_value="NO_POST_RESET_DATA",
            num_transitions=0,
        )

    unique_vals = list(set(active_values))
    is_flat = len(unique_vals) <= 1

    return SignalDiag(
        name=signal_name,
        is_flatlined=is_flat,
        flatline_value=unique_vals[0] if is_flat else None,
        num_transitions=len(all_post_reset),
        unique_values=unique_vals[:20],
        sample_transitions=all_post_reset[:10],
    )


def analyze_vcd(cfg: Config) -> VCDDiagnostic:
    """
    Parse the simulation VCD trace and diagnose signal activity.

    Checks:
      - PC: Should increment by 4 each cycle after reset.
      - reg_write: Should assert (=1) for R-type/I-type instructions.
      - alu_result: Should show computation results.
      - alu_control: Should reflect decoded control signals.
      - write_data: Should carry ALU results to register file.
    """
    Log.phase("🔬", "PHASE 2: VCD WAVEFORM CRITIC")

    if not cfg.vcd_file.exists():
        Log.fail(f"VCD file not found: {cfg.vcd_file}")
        return VCDDiagnostic()

    vcd = VCDVCD(str(cfg.vcd_file))
    Log.ok(f"Parsed VCD: {len(vcd.signals)} signals")

    diag = VCDDiagnostic(
        pc=_analyze_signal(vcd, cfg.sig_pc, cfg.reset_deassert_time),
        reg_write=_analyze_signal(vcd, cfg.sig_reg_write, cfg.reset_deassert_time),
        alu_result=_analyze_signal(vcd, cfg.sig_alu_result, cfg.reset_deassert_time),
        alu_control=_analyze_signal(vcd, cfg.sig_alu_control, cfg.reset_deassert_time),
        write_data=_analyze_signal(vcd, cfg.sig_write_data, cfg.reset_deassert_time),
    )

    # Display results
    for sig in [diag.pc, diag.reg_write, diag.alu_result, diag.alu_control, diag.write_data]:
        if sig:
            detail = ""
            if sig.is_flatlined:
                detail = f"stuck at {sig.flatline_value}"
            else:
                detail = f"{sig.num_transitions} transitions, {len(sig.unique_values)} unique values"
            Log.signal(sig.name.split(".")[-1], sig.status, detail)

    # Overall verdict
    if diag.has_critical_failure:
        Log.fail("CRITICAL: Core has fundamental integration failure")
    elif diag.all_signals_active:
        Log.ok("All monitored signals are ACTIVE — core appears functional")
    else:
        Log.warn("Partial activity detected — some signals may need attention")

    return diag


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3: FUNCTIONAL VERIFICATION (REGISTER VALUE CHECK)
# ═══════════════════════════════════════════════════════════════════════════════

def verify_functional_correctness(cfg: Config) -> tuple[bool, str]:
    """
    Beyond just checking for signal activity, verify that the ADD test
    actually produces the correct result (x3 = 12) by reading the register
    file contents from the VCD.
    """
    Log.phase("🎯", "PHASE 3: FUNCTIONAL VERIFICATION")

    if not cfg.vcd_file.exists():
        return False, "VCD file missing"

    vcd = VCDVCD(str(cfg.vcd_file))

    # Check register x3 (rd=3 for ADD x3, x1, x2)
    reg3_sig = "TOP.testbench.dut.u_register_file.registers[3][31:0]"
    try:
        reg3 = vcd[reg3_sig]
        post_reset = [(t, v) for (t, v) in reg3.tv if t > cfg.reset_deassert_time]

        if not post_reset:
            Log.fail("Register x3 has no post-reset transitions")
            return False, "x3 never written"

        # Get the last value of x3
        final_val_bin = post_reset[-1][1]
        final_val = int(final_val_bin, 2)

        if final_val == cfg.expected_final_x3:
            Log.ok(f"x3 = {final_val} (expected {cfg.expected_final_x3}) — "
                   f"ADD test PASSED ✅")
            return True, f"x3={final_val}"
        else:
            Log.fail(f"x3 = {final_val} (expected {cfg.expected_final_x3}) — "
                     f"ADD test FAILED")
            return False, f"x3={final_val}, expected={cfg.expected_final_x3}"

    except KeyError:
        Log.warn(f"Signal '{reg3_sig}' not found in VCD")
        return False, "register signal not found in VCD"


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 4: DIAGNOSTIC PROMPT CONSTRUCTION
# ═══════════════════════════════════════════════════════════════════════════════

def _read_file(path: Path) -> str:
    """Safely read a file, return empty string on error."""
    try:
        return path.read_text()
    except Exception as e:
        Log.warn(f"Could not read {path}: {e}")
        return ""


def _extract_alu_encodings(alu_source: str) -> str:
    """Extract localparam ALU encodings from alu.v for the LLM prompt."""
    lines = []
    for line in alu_source.split("\n"):
        stripped = line.strip()
        if stripped.startswith("localparam ALU_"):
            lines.append(f"    {stripped}")
    if lines:
        return "\n".join(lines)
    return "    // Could not extract ALU encodings — refer to alu.v source"


def build_diagnostic_prompt(cfg: Config, diag: VCDDiagnostic,
                            compile_log: str,
                            iteration: int) -> str:
    """
    Build a richly-contextualized LLM prompt that includes:
      1. The exact diagnostic failure from VCD analysis
      2. The current rv32i_core.v source code
      3. The locked sub-module interfaces
      4. The ALU's control encodings (ground truth)
      5. Strict rewrite instructions
    """
    Log.phase("📝", "PHASE 4: CONSTRUCTING DIAGNOSTIC PROMPT")

    core_source = _read_file(cfg.core_verilog)
    alu_source = _read_file(cfg.alu_verilog)
    alu_encodings = _extract_alu_encodings(alu_source)

    # Build the failure description
    failures = []
    if diag.pc and diag.pc.is_flatlined:
        failures.append(
            f"CRITICAL: Program Counter (pc) is FLATLINED at "
            f"'{diag.pc.flatline_value}'. The PC never increments after reset, "
            f"meaning no instructions are being fetched. This indicates pc_sel "
            f"may be incorrectly driven, or reset is never properly deasserted "
            f"in your control logic."
        )
    if diag.reg_write and diag.reg_write.is_flatlined:
        val = diag.reg_write.flatline_value
        failures.append(
            f"CRITICAL: reg_write is FLATLINED at '{val}'. "
            f"{'It never asserts, so no instruction can write results to the register file. ' if val == '0' else 'It is stuck HIGH, which would cause every cycle to write — likely incorrect. '}"
            f"The control unit must decode the opcode and assert reg_write=1 "
            f"ONLY for R-type (0110011) and I-type (0010011) instructions."
        )
    if diag.alu_result and diag.alu_result.is_flatlined:
        failures.append(
            f"WARNING: alu_result is FLATLINED at '{diag.alu_result.flatline_value}'. "
            f"The ALU is not producing changing outputs. Check that alu_control "
            f"is being driven correctly and that ALU inputs (a, b) are connected."
        )
    if diag.alu_control and diag.alu_control.is_flatlined:
        failures.append(
            f"WARNING: alu_control is FLATLINED at '{diag.alu_control.flatline_value}'. "
            f"The control unit is not varying the ALU operation. Ensure funct3 "
            f"and funct7 are being decoded into the correct alu_control value."
        )

    if not failures:
        failures.append(
            "Signals show activity but the functional test (5+7=12 in x3) "
            "did not pass. Check the exact ALU control encoding mappings and "
            "register write-back path."
        )

    failure_text = "\n\n".join(f"  [{i+1}] {f}" for i, f in enumerate(failures))

    # Include VCD evidence
    vcd_evidence = diag.summary()

    prompt = f"""\
You are an expert hardware RTL engineer debugging a single-cycle RV32I RISC-V processor.

════════════════════════════════════════════════════════════════════
ITERATION {iteration} — AUTOMATED VCD WAVEFORM DIAGNOSTIC
════════════════════════════════════════════════════════════════════

The simulation was run with a test program that executes:
  ADDI x1, x0, 5    (hex: 00500093)
  ADDI x2, x0, 7    (hex: 00700113)
  ADD  x3, x1, x2   (hex: 002081b3)
  JAL  x0, 0        (hex: 0000006f)  ← infinite loop to halt

Expected result: Register x3 = 12 (decimal).

═══ FAILURES DETECTED FROM VCD WAVEFORM ANALYSIS ═══

{failure_text}

═══ RAW VCD SIGNAL EVIDENCE ═══

{vcd_evidence}

═══ CURRENT rv32i_core.v SOURCE CODE ═══

```verilog
{core_source}
```

═══ GROUND-TRUTH ALU CONTROL ENCODINGS (from alu.v — DO NOT CHANGE THESE) ═══

The ALU module uses these EXACT localparam encodings. Your control unit in
rv32i_core.v MUST drive alu_control with values that match THESE encodings:

{alu_encodings}

KEY MAPPING (alu.v localparams → 4-bit control values):
  ADD  = 4'b0000    SUB  = 4'b1000    SLL  = 4'b0001
  SLT  = 4'b0010    SLTU = 4'b0011    XOR  = 4'b0100
  SRL  = 4'b0101    SRA  = 4'b1101    OR   = 4'b0110
  AND  = 4'b0111

═══ LOCKED SUB-MODULE INTERFACES (DO NOT CHANGE PORT NAMES) ═══

1. program_counter: (input clk, reset, [31:0] branch_target, pc_sel,
                     output reg [31:0] pc)
   → pc_sel=0: PC increments by 4. pc_sel=1: PC jumps to branch_target.

2. decoder: (input [31:0] instr, output reg [6:0] opcode, [4:0] rd,
             [2:0] funct3, [4:0] rs1, [4:0] rs2, [6:0] funct7, [31:0] imm)

3. register_file: (input clk, [4:0] rs1, [4:0] rs2, [4:0] rd,
                   [31:0] write_data, reg_write,
                   output [31:0] rs1_data, [31:0] rs2_data)
   → Writes on posedge clk ONLY when reg_write=1.

4. branch_unit: (input [31:0] rs1_data, [31:0] rs2_data, [2:0] funct3,
                 output reg branch_taken)

5. alu: (input [31:0] a, [31:0] b, [3:0] alu_control,
         output reg [31:0] result, output zero)

═══ YOUR TASK ═══

Rewrite the COMPLETE rv32i_core.v module. You MUST:

1. Keep ALL sub-module instantiations with their EXACT port connections.
2. Keep ALL wire/reg declarations and datapath assignments (alu_a, alu_b,
   branch_target, write_data, instr_mem_addr).
3. REWRITE the combinational control unit block (the `always @(*)` block)
   to correctly decode RV32I opcodes and produce the correct control signals:
   - reg_write: Assert for R-type (7'b0110011) and I-type (7'b0010011)
   - pc_sel: Assert ONLY when branch is taken (opcode=7'b1100011 AND branch_taken)
   - alu_src_b: 0 for R-type (use rs2_data), 1 for I-type (use immediate)
   - alu_control: Map funct3/funct7 to the EXACT ALU encodings listed above

4. Use `always @(*)` (not `always_comb`) for the control block to match
   existing Verilator-compatible style.
5. Provide DEFAULT ASSIGNMENTS at the top of the always block to prevent
   latch inference.
6. Handle at minimum: R-type (0110011), I-type ALU (0010011), B-type (1100011).

OUTPUT ONLY THE COMPLETE VERILOG MODULE CODE.
Do NOT include markdown fences (```verilog), explanations, or commentary.
Start with `module rv32i_core` and end with `endmodule`.
"""

    Log.ok(f"Diagnostic prompt constructed ({len(prompt)} chars)")
    Log.info(f"Failures identified: {len(failures)}")

    return prompt


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 5: LLM CALL & CODE EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

def call_llm_and_heal(cfg: Config, prompt: str, iteration: int) -> bool:
    """
    Call Gemini to regenerate rv32i_core.v, validate the output,
    and overwrite the file.

    Returns True if a valid Verilog file was written.
    """
    Log.phase("🤖", "PHASE 5: LLM GENERATION & SELF-HEAL")

    # --- Backup current file ---
    cfg.backup_dir.mkdir(exist_ok=True)
    backup_path = cfg.backup_dir / f"rv32i_core.v.iter{iteration}"
    shutil.copy2(cfg.core_verilog, backup_path)
    Log.info(f"Backed up current code → {backup_path.name}")

    # --- Call Gemini ---
    Log.info(f"Calling {cfg.gemini_model} (temperature={cfg.temperature})...")
    t0 = time.time()

    try:
        model = genai.GenerativeModel(cfg.gemini_model)
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=cfg.temperature,
            ),
        )
        elapsed = time.time() - t0
        Log.ok(f"LLM responded in {elapsed:.1f}s")
    except Exception as e:
        Log.fail(f"LLM call failed: {e}")
        return False

    # --- Extract and clean the Verilog code ---
    raw_output = response.text

    # Strip markdown fences if present
    code = raw_output
    code = re.sub(r"```(?:verilog|systemverilog|sv)?\s*\n", "", code)
    code = re.sub(r"```\s*$", "", code, flags=re.MULTILINE)
    code = code.strip()

    # --- Validate basic structure ---
    if "module rv32i_core" not in code:
        Log.fail("LLM output missing 'module rv32i_core' — rejecting")
        Log.info("First 200 chars of output:")
        print(f"    {Log.DIM}{code[:200]}{Log.RESET}")
        return False

    if "endmodule" not in code:
        Log.fail("LLM output missing 'endmodule' — rejecting")
        return False

    # Ensure it ends cleanly at endmodule
    endmod_idx = code.rfind("endmodule")
    if endmod_idx >= 0:
        code = code[:endmod_idx + len("endmodule")]

    # Check that key sub-module instantiations are preserved
    required_instances = [
        "u_program_counter",
        "u_decoder",
        "u_register_file",
        "u_branch_unit",
        "u_alu",
    ]
    missing = [inst for inst in required_instances if inst not in code]
    if missing:
        Log.fail(f"LLM output missing sub-module instances: {missing}")
        return False

    # --- Write the healed file ---
    cfg.core_verilog.write_text(code + "\n")
    Log.ok(f"Wrote healed rv32i_core.v ({len(code)} bytes)")

    # Quick diff summary
    old_lines = backup_path.read_text().split("\n")
    new_lines = code.split("\n")
    Log.info(f"Lines: {len(old_lines)} → {len(new_lines)} "
             f"(delta: {len(new_lines) - len(old_lines):+d})")

    return True


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN AGENTIC LOOP
# ═══════════════════════════════════════════════════════════════════════════════

def run_agentic_loop(cfg: Config):
    """
    The Silicon Reflex: closed-loop compile → simulate → diagnose → heal → repeat.

    Termination conditions:
      1. All VCD signals active AND functional test passes → SUCCESS
      2. Max iterations reached → FAILURE (human takeover needed)
      3. Unrecoverable compilation error → ABORT
    """
    Log.banner(
        "SILICON REFLEX — Agentic Debug Loop\n"
        "Closed-Loop Self-Healing for RV32I Core\n"
        f"Max Iterations: {cfg.max_iterations}"
    )

    for iteration in range(1, cfg.max_iterations + 1):
        Log.iteration_header(iteration, cfg.max_iterations)

        # ── Step 1: Compile & Simulate ──
        compile_ok, compile_log = compile_and_simulate(cfg)

        if not compile_ok:
            if iteration == 1:
                # First iteration compile failure → the existing code is broken
                Log.warn("Compile failed on first iteration — "
                         "will attempt LLM repair of syntax errors")
                # Build a compile-error-focused prompt
                diag = VCDDiagnostic(
                    pc=SignalDiag("pc", True, "COMPILE_FAILED"),
                    reg_write=SignalDiag("reg_write", True, "COMPILE_FAILED"),
                )
                prompt = build_diagnostic_prompt(cfg, diag, compile_log, iteration)
                prompt += f"\n\nADDITIONAL: Verilator compilation errors:\n{compile_log[:3000]}\n"
                prompt += "\nFix ALL compilation errors while also fixing the control logic.\n"
            else:
                Log.fail("Compile failed after LLM patch — the LLM introduced syntax errors")
                diag = VCDDiagnostic(
                    pc=SignalDiag("pc", True, "COMPILE_FAILED"),
                    reg_write=SignalDiag("reg_write", True, "COMPILE_FAILED"),
                )
                prompt = build_diagnostic_prompt(cfg, diag, compile_log, iteration)
                prompt += f"\n\nCRITICAL: Your previous rewrite caused these Verilator errors:\n"
                prompt += compile_log[:3000]
                prompt += "\n\nFix these compilation errors. The code must compile cleanly.\n"

            healed = call_llm_and_heal(cfg, prompt, iteration)
            if not healed:
                Log.fail("LLM failed to produce valid code — aborting")
                break
            continue  # Retry compilation

        # ── Step 2: Analyze VCD ──
        diag = analyze_vcd(cfg)

        # ── Step 3: Check functional correctness ──
        if diag.all_signals_active:
            func_ok, func_detail = verify_functional_correctness(cfg)
            if func_ok:
                Log.banner(
                    f"🎉  SUCCESS — CORE HEALED  🎉\n"
                    f"Iteration: {iteration}\n"
                    f"Test: ADD (5 + 7 = 12) PASSED\n"
                    f"All signals active, functional test passed"
                )
                _print_final_report(cfg, iteration, diag)
                return True
            else:
                Log.warn(f"Signals active but functional test failed: {func_detail}")
                # Continue to LLM repair with functional failure info
        elif not diag.has_critical_failure:
            # Partial activity — still check functional result
            func_ok, func_detail = verify_functional_correctness(cfg)
            if func_ok:
                Log.banner(
                    f"🎉  SUCCESS — CORE HEALED  🎉\n"
                    f"Iteration: {iteration}\n"
                    f"Test: ADD (5 + 7 = 12) PASSED"
                )
                _print_final_report(cfg, iteration, diag)
                return True

        # ── Step 4: Build diagnostic prompt & heal ──
        prompt = build_diagnostic_prompt(cfg, diag, compile_log, iteration)
        healed = call_llm_and_heal(cfg, prompt, iteration)

        if not healed:
            Log.fail("LLM failed to produce valid code — aborting")
            break

    # If we exit the loop without success
    Log.banner(
        f"⚠️  MAX ITERATIONS REACHED ({cfg.max_iterations})  ⚠️\n"
        "Human intervention required.\n"
        "Check backups/ for iteration history."
    )
    return False


def _print_final_report(cfg: Config, iteration: int, diag: VCDDiagnostic):
    """Print a summary report after successful healing."""
    print(f"\n{Log.BOLD}{Log.GREEN}{'═'*60}{Log.RESET}")
    print(f"{Log.BOLD}{Log.GREEN}  FINAL REPORT{Log.RESET}")
    print(f"{Log.BOLD}{Log.GREEN}{'═'*60}{Log.RESET}")
    print(f"  Iterations required : {iteration}")
    print(f"  Core file           : {cfg.core_verilog}")
    print(f"  VCD trace           : {cfg.vcd_file}")
    print(f"  Backups             : {cfg.backup_dir}/")
    print()
    print(f"  {Log.BOLD}Signal Status:{Log.RESET}")
    for sig in [diag.pc, diag.reg_write, diag.alu_result, diag.alu_control]:
        if sig:
            icon = "🟢" if not sig.is_flatlined else "🔴"
            print(f"    {icon} {sig.name.split('.')[-1]:30s} → "
                  f"{'ACTIVE' if not sig.is_flatlined else 'FLATLINED'}")
    print(f"\n{Log.BOLD}{Log.GREEN}{'═'*60}{Log.RESET}\n")


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Entry point with environment setup and error handling."""

    # Load API key
    env_path = Path(__file__).parent / "pipeline" / ".env"
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(env_path)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print(f"{Log.RED}ERROR: GEMINI_API_KEY not found.{Log.RESET}")
        print(f"Set it in pipeline/.env or as an environment variable.")
        sys.exit(1)

    genai.configure(api_key=api_key)

    # Initialize configuration
    cfg = Config()

    # Verify critical files exist
    required_files = [
        cfg.core_verilog, cfg.testbench_verilog, cfg.sim_main_cpp,
        cfg.alu_verilog,
    ]
    for f in required_files:
        if not f.exists():
            print(f"{Log.RED}ERROR: Required file missing: {f}{Log.RESET}")
            sys.exit(1)

    Log.ok("All required files verified")
    Log.info(f"Project root: {cfg.project_root}")
    Log.info(f"Target file:  {cfg.core_verilog}")

    # Run the agentic loop
    success = run_agentic_loop(cfg)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
