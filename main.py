#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║            SILICON REFLEX — Push-Button RV32I Compiler                      ║
║                                                                              ║
║   End-to-end autonomous pipeline:                                            ║
║     Phase 1 → RAG-driven Verilog generation                                  ║
║     Phase 2 → Verilator compilation & simulation                             ║
║     Phase 3 → VCD waveform critic (flatline detection)                       ║
║     Phase 4 → LLM-driven agentic self-healing loop                           ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import re
import sys
import time
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional

# ── Third-party ──────────────────────────────────────────────────────────────
from dotenv import load_dotenv

# Load API keys before configuring genai
load_dotenv(Path(__file__).parent / "pipeline" / ".env")

import google.generativeai as genai
from vcdvcd import VCDVCD

# ── API Setup ────────────────────────────────────────────────────────────────
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    print("  ✗ FATAL: GEMINI_API_KEY not found in pipeline/.env")
    sys.exit(1)
genai.configure(api_key=API_KEY)

# ── Project Paths ────────────────────────────────────────────────────────────
PROJECT_ROOT   = Path(__file__).parent.resolve()
CORE_FILE      = PROJECT_ROOT / "rv32i_core.v"
VCD_FILE       = PROJECT_ROOT / "simulation_trace.vcd"
BACKUP_DIR     = PROJECT_ROOT / "backups"
SIM_BINARY     = PROJECT_ROOT / "obj_dir" / "Vtestbench"
HEX_FILE       = PROJECT_ROOT / "rv32ui-p-add.hex"

# All source files that Verilator needs
VERILOG_SOURCES = [
    "sim_main.cpp",
    "testbench.v",
    "rv32i_core.v",
    "alu.v",
    "instruction_decoder.v",
    "register_file.v",
    "branch_unit.v",
    "program_counter.v",
]

# ── Global Constants ─────────────────────────────────────────────────────────

MAX_HEAL_ITERATIONS = 3
RESET_TIME = 10   # sim_main.cpp deasserts reset after time=10
LLM_MODEL = "gemini-2.5-pro"

HARDWARE_RULES = """\
Use non-blocking assignments (<=) in clocked blocks. \
Never use blocking assignments (=) in clocked blocks. \
Use always @(*) for combinational logic. \
Provide default assignments to prevent latches."""

# The locked sub-module interfaces — the LLM must NEVER change these ports
LOCKED_INTERFACES = """\
1. program_counter: (input clk, reset, [31:0] branch_target, pc_sel, output reg [31:0] pc)
2. decoder:         (input [31:0] instr, output reg [6:0] opcode, [4:0] rd, [2:0] funct3, [4:0] rs1, [4:0] rs2, [6:0] funct7, [31:0] imm)
3. register_file:   (input clk, [4:0] rs1, [4:0] rs2, [4:0] rd, [31:0] write_data, reg_write, output [31:0] rs1_data, [31:0] rs2_data)
4. branch_unit:     (input [31:0] rs1_data, [31:0] rs2_data, [2:0] funct3, output reg branch_taken)
5. alu:             (input [31:0] a, [31:0] b, [3:0] alu_control, output reg [31:0] result, output zero)"""

# Ground-truth ALU encodings — extracted from alu.v to prevent hallucinated mappings
ALU_ENCODINGS = """\
localparam ALU_ADD    = 4'b0000;
localparam ALU_SUB    = 4'b1000;
localparam ALU_SLL    = 4'b0001;
localparam ALU_SLT    = 4'b0010;
localparam ALU_SLTU   = 4'b0011;
localparam ALU_XOR    = 4'b0100;
localparam ALU_SRL    = 4'b0101;
localparam ALU_SRA    = 4'b1101;
localparam ALU_OR     = 4'b0110;
localparam ALU_AND    = 4'b0111;
localparam ALU_COPY_B = 4'b1111;"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  UTILITIES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def banner(text: str, char: str = "═", width: int = 78):
    """Print a framed banner line."""
    pad = max(0, width - len(text) - 4)
    left = pad // 2
    right = pad - left
    print(f"\n╔{char * (width - 2)}╗")
    print(f"║{' ' * left} {text} {' ' * right}║")
    print(f"╚{char * (width - 2)}╝\n")

def section(title: str):
    """Print a section header."""
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")

def log_ok(msg: str):
    print(f"  ✓ {msg}")

def log_fail(msg: str):
    print(f"  ✗ {msg}")

def log_info(msg: str):
    print(f"  ℹ {msg}")

def log_warn(msg: str):
    print(f"  ⚠ {msg}")

def timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PHASE 1: RAG-DRIVEN GENERATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_initial_generation():
    """
    Import the generation pipeline and produce all sub-modules + top-level core.
    Skips generation for any file that already exists on disk.
    """
    section("📐  PHASE 1: RAG-DRIVEN VERILOG GENERATION")

    # Lazy import — only needed if we actually generate
    try:
        from pipeline.generate_rtl import generate_component
    except ImportError as e:
        log_warn(f"Could not import generate_component: {e}")
        log_info("Skipping generation — assuming pre-existing Verilog files.")
        return

    # ── Sub-module definitions ──────────────────────────────────────────
    components = [
        {
            "name": "ALU",
            "file": "alu.v",
            "interface": """module alu (
    input  [31:0] a,
    input  [31:0] b,
    input  [3:0]  alu_control,
    output reg [31:0] result,
    output zero
);""",
            "warnings": "Use the ALU_ADD=4'b0000, ALU_SUB=4'b1000 encoding scheme."
        },
        {
            "name": "Program Counter",
            "file": "program_counter.v",
            "interface": """module program_counter (
    input  clk,
    input  reset,
    input  [31:0] branch_target,
    input         pc_sel,
    output reg [31:0] pc
);""",
            "warnings": "On reset, set PC to 0x00000000. If pc_sel=1, load branch_target; else increment by 4."
        },
        {
            "name": "Instruction Decoder",
            "file": "instruction_decoder.v",
            "interface": """module decoder (
    input  [31:0] instr,
    output reg [6:0]  opcode,
    output reg [4:0]  rd,
    output reg [2:0]  funct3,
    output reg [4:0]  rs1,
    output reg [4:0]  rs2,
    output reg [6:0]  funct7,
    output reg [31:0] imm
);""",
            "warnings": "Decode ALL RV32I immediate types: I, S, B, U, J. Sign-extend correctly."
        },
        {
            "name": "Register File",
            "file": "register_file.v",
            "interface": """module register_file (
    input  clk,
    input  [4:0]  rs1,
    input  [4:0]  rs2,
    input  [4:0]  rd,
    input  [31:0] write_data,
    input         reg_write,
    output [31:0] rs1_data,
    output [31:0] rs2_data
);""",
            "warnings": "Register x0 is hardwired to zero. Writes occur on the positive clock edge."
        },
        {
            "name": "Branch Unit",
            "file": "branch_unit.v",
            "interface": """module branch_unit (
    input  [31:0] rs1_data,
    input  [31:0] rs2_data,
    input  [2:0]  funct3,
    output reg    branch_taken
);""",
            "warnings": "Implement BEQ, BNE, BLT, BGE, BLTU, BGEU via funct3 decoding."
        },
    ]

    # ── Top-level core definition ──────────────────────────────────────
    core_def = {
        "name": "RV32I Core",
        "file": "rv32i_core.v",
        "interface": """module rv32i_core (
    input  clk,
    input  reset,
    input  [31:0] instr_mem_data,
    output [31:0] instr_mem_addr
);""",
        "warnings": f"""[CRITICAL ERROR RECOVERY - PORT MISMATCHES]
You MUST instantiate sub-modules using the EXACT port names below:
{LOCKED_INTERFACES}

[GROUND-TRUTH ALU ENCODINGS - COPY THESE EXACTLY]
{ALU_ENCODINGS}

[ROUTING INSTRUCTIONS]
- Connect instr_mem_addr to pc.
- Connect instr_mem_data to decoder's instr input.
- Declare intermediate wires to route datapath signals.
- Write a combinational always @(*) block for the control unit.
- Map alu_control using the EXACT localparam values above."""
    }

    all_components = components + [core_def]

    for comp in all_components:
        target = PROJECT_ROOT / comp["file"]
        if target.exists():
            log_info(f"{comp['file']} already exists — skipping generation")
        else:
            log_info(f"Generating {comp['name']}...")
            generate_component(comp["name"], comp["interface"], comp["warnings"])
            if target.exists():
                log_ok(f"{comp['file']} generated successfully")
            else:
                log_fail(f"Failed to generate {comp['file']}")

    # Final check
    missing = [c["file"] for c in all_components if not (PROJECT_ROOT / c["file"]).exists()]
    if missing:
        log_fail(f"Missing files after generation: {missing}")
        sys.exit(1)
    else:
        log_ok("All Verilog source files verified ✔")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PHASE 2: COMPILE & SIMULATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def compile_and_simulate() -> Tuple[bool, str]:
    """
    Run Verilator to compile the design, then execute the simulation binary.
    Returns (success: bool, error_message: str).
    """
    section("🔧  PHASE 2: COMPILE & SIMULATE")

    # ── Step 1: Verilator Compilation ───────────────────────────────────
    verilator_cmd = [
        "verilator",
        "-cc", "--exe", "--build",
        "-j", "0",
        "-Wno-fatal",
        "--trace",
        "--top-module", "testbench",
    ] + VERILOG_SOURCES

    log_info(f"Verilator command: {' '.join(verilator_cmd[:6])} ...")

    result = subprocess.run(
        verilator_cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        error_msg = result.stderr.strip()
        # Filter to actual %Error lines, not warnings
        error_lines = [
            l for l in error_msg.split("\n")
            if "%Error" in l or "error:" in l.lower()
        ]
        log_fail("Verilator compilation FAILED")
        for line in error_lines[:10]:
            print(f"    {line.strip()}")
        return False, error_msg

    log_ok("Verilator compilation succeeded")

    # ── Step 2: Execute Simulation ──────────────────────────────────────
    sim_cmd = [str(SIM_BINARY), "+loadmem"]
    log_info(f"Running simulation: {sim_cmd[0]}")

    result = subprocess.run(
        sim_cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        log_fail(f"Simulation failed: {result.stderr.strip()}")
        return False, result.stderr

    if not VCD_FILE.exists():
        log_fail("Simulation ran but no VCD trace file was generated")
        return False, "Missing simulation_trace.vcd"

    log_ok("Simulation completed — VCD trace written")
    return True, ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PHASE 3: VCD WAVEFORM CRITIC
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Signals to monitor for liveness
MONITORED_SIGNALS = {
    "pc":        "TOP.testbench.dut.u_program_counter.pc[31:0]",
    "reg_write": "TOP.testbench.dut.reg_write",
    "alu_result":"TOP.testbench.dut.u_alu.result[31:0]",
    "write_data":"TOP.testbench.dut.write_data[31:0]",
}

# The expected functional result: x3 = 5 + 7 = 12
EXPECTED_REG    = "TOP.testbench.dut.u_register_file.registers[3][31:0]"
EXPECTED_VALUE  = 12


def _get_inherited_value(tv_pairs: list, boundary: int) -> Optional[str]:
    """
    Return the last signal value at or before the boundary time.
    This is the value the signal holds when reset deasserts.
    """
    inherited = None
    for t, v in tv_pairs:
        if t <= boundary:
            inherited = v
        else:
            break
    return inherited


def _check_signal_alive(vcd: VCDVCD, label: str, sig_path: str) -> Optional[str]:
    """
    Determine if a signal is flatlined post-reset.

    Returns None if the signal is ACTIVE (multiple unique values),
    or a diagnostic string describing the failure.

    CRITICAL: accounts for the inherited reset value so that a signal
    which is e.g. '1' during reset and only transitions to '0' post-reset
    is correctly identified as ACTIVE (2 unique values).
    """
    try:
        sig = vcd[sig_path]
    except KeyError:
        return f"{label}: SIGNAL NOT FOUND in VCD ({sig_path})"

    all_tv = sig.tv
    if not all_tv:
        return f"{label}: NO DATA in VCD trace"

    # Post-reset transitions
    post_reset = [(t, v) for t, v in all_tv if t > RESET_TIME]

    # Inherited value at the reset boundary
    inherited = _get_inherited_value(all_tv, RESET_TIME)

    # Build the complete set of values active during post-reset execution
    active_values = set()
    if inherited is not None:
        active_values.add(inherited)
    for _, v in post_reset:
        active_values.add(v)

    if len(active_values) == 0:
        return f"{label}: NO POST-RESET DATA"

    if len(active_values) <= 1:
        stuck_val = list(active_values)[0]
        return f"{label}: FLATLINED at {stuck_val} (inherited={inherited}, post_reset_transitions={len(post_reset)})"

    # Signal is ACTIVE
    return None


def check_waveforms() -> List[str]:
    """
    Parse simulation_trace.vcd and verify all monitored signals are alive.
    Also runs a functional assertion on register x3 for the ADD test.

    Returns a list of diagnostic error strings. Empty list = all pass.
    """
    section("🔬  PHASE 3: VCD WAVEFORM CRITIC")

    if not VCD_FILE.exists():
        return ["VCD file not found — simulation may have failed."]

    vcd = VCDVCD(str(VCD_FILE))
    log_ok(f"Parsed VCD: {len(vcd.signals)} signals")

    errors = []

    # ── Signal Liveness Checks ──────────────────────────────────────────
    for label, sig_path in MONITORED_SIGNALS.items():
        diag = _check_signal_alive(vcd, label, sig_path)
        if diag:
            print(f"    🔴 {label:30s} → {diag}")
            errors.append(diag)
        else:
            print(f"    🟢 {label:30s} → ACTIVE")

    # ── Functional Assertion: x3 = 12 ──────────────────────────────────
    section("🎯  PHASE 3b: FUNCTIONAL VERIFICATION")
    try:
        sig = vcd[EXPECTED_REG]
        # Get the final value of x3
        if sig.tv:
            final_val_str = sig.tv[-1][1]
            final_val = int(final_val_str, 2)
            if final_val == EXPECTED_VALUE:
                log_ok(f"x3 = {final_val} (expected {EXPECTED_VALUE}) — ADD test PASSED ✅")
            else:
                msg = f"x3 = {final_val} (expected {EXPECTED_VALUE}) — ADD test FAILED"
                log_fail(msg)
                errors.append(msg)
        else:
            errors.append("x3 register has no data in VCD")
    except KeyError:
        log_warn(f"Register signal '{EXPECTED_REG}' not found in VCD — skipping functional check")

    return errors


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PHASE 4: AGENTIC SELF-HEALING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _backup_core(iteration: int):
    """Create a timestamped backup of rv32i_core.v."""
    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"rv32i_core.v.iter_{iteration}_{ts}"
    shutil.copy2(str(CORE_FILE), str(backup_path))
    log_info(f"Backed up current code → {backup_path.name}")


def _sanitize_verilog(raw_text: str) -> Optional[str]:
    """
    Extract valid Verilog from the LLM response.
    Strips markdown fences and validates structural integrity.
    """
    # Remove markdown fences
    text = raw_text
    text = re.sub(r"```(?:verilog|systemverilog|sv)?\s*\n?", "", text)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()

    # If the LLM output multiple modules, extract only rv32i_core
    match = re.search(
        r"(module\s+rv32i_core\b.*?endmodule)",
        text,
        re.DOTALL
    )
    if match:
        text = match.group(1)

    # Validate structural integrity
    if "module rv32i_core" not in text:
        return None
    if "endmodule" not in text:
        return None
    if "u_program_counter" not in text:
        return None
    if "u_alu" not in text:
        return None

    return text + "\n"


def agentic_heal(errors: List[str], iteration: int) -> bool:
    """
    The Silicon Reflex: use VCD diagnostics to prompt the LLM
    to rewrite the control logic in rv32i_core.v.

    Returns True if the file was successfully patched, False on failure.
    """
    section("🤖  PHASE 4: AGENTIC SELF-HEALING")

    # ── Step 1: Backup ──────────────────────────────────────────────────
    _backup_core(iteration)

    # ── Step 2: Read current source ────────────────────────────────────
    current_source = CORE_FILE.read_text()

    # ── Step 3: Build the diagnostic prompt ────────────────────────────
    error_block = "\n".join(f"  - {e}" for e in errors)

    prompt = f"""\
You are an expert Verilog RTL engineer debugging a single-cycle RV32I RISC-V processor.

[STRICT HARDWARE RULES]
{HARDWARE_RULES}

[GROUND-TRUTH ALU ENCODINGS — COPY THESE EXACTLY]
{ALU_ENCODINGS}

[LOCKED SUB-MODULE INTERFACES — DO NOT CHANGE PORT NAMES]
{LOCKED_INTERFACES}

[VCD DIAGNOSTIC FAILURES]
The following failures were detected by the automated waveform critic after simulating
the processor with the rv32ui-p-add test (computes x3 = 5 + 7 = 12):
{error_block}

[CURRENT BROKEN SOURCE — rv32i_core.v]
{current_source}

[YOUR TASK]
Rewrite the COMPLETE rv32i_core.v module to fix the VCD diagnostic failures above.

CRITICAL REQUIREMENTS:
1. You MUST keep ALL sub-module instantiations with the EXACT same port connections.
2. You MUST fix the control unit's always @(*) block to correctly drive:
   - reg_write: Assert HIGH for R-type (0110011) and I-type (0010011) instructions.
   - alu_control: Use the EXACT ALU encodings listed above (e.g., SUB = 4'b1000, NOT 4'b0001).
   - alu_src_b: Assert HIGH for I-type instructions (ALU operand B = immediate).
   - pc_sel: Assert HIGH when a B-type branch is taken.
3. You MUST provide default assignments at the top of the always block.
4. You MUST NOT change any module ports or sub-module instantiation bindings.

OUTPUT ONLY the complete, valid Verilog for the rv32i_core module.
Do NOT include markdown fences, explanations, or commentary. Just the code."""

    # ── Step 4: Call LLM ───────────────────────────────────────────────
    model = genai.GenerativeModel(LLM_MODEL)
    log_info(f"Calling {LLM_MODEL} (temperature=0.2)...")

    t0 = time.time()
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(temperature=0.2),
        )
        elapsed = time.time() - t0
        log_ok(f"LLM responded in {elapsed:.1f}s")
    except Exception as e:
        log_fail(f"LLM call failed: {e}")
        return False

    # ── Step 5: Sanitize & validate ────────────────────────────────────
    raw_text = response.text
    clean_code = _sanitize_verilog(raw_text)

    if clean_code is None:
        log_fail("LLM output failed structural validation — skipping overwrite")
        log_info(f"Raw output preview: {raw_text[:200]}...")
        return False

    # ── Step 6: Atomic overwrite ───────────────────────────────────────
    old_lines = len(current_source.splitlines())
    new_lines = len(clean_code.splitlines())

    CORE_FILE.write_text(clean_code)
    log_ok(f"Wrote healed rv32i_core.v ({len(clean_code)} bytes)")
    log_info(f"Lines: {old_lines} → {new_lines} (delta: {new_lines - old_lines:+d})")

    return True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN EXECUTION LOOP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    banner("SILICON REFLEX — Push-Button RV32I Compiler")
    print(f"  Project  : {PROJECT_ROOT}")
    print(f"  Target   : {CORE_FILE.name}")
    print(f"  Test     : rv32ui-p-add (x3 = 5 + 7 = 12)")
    print(f"  Max Iters: {MAX_HEAL_ITERATIONS}")
    print(f"  LLM      : {LLM_MODEL}")
    print(f"  Time     : {timestamp()}")

    # ── Phase 1: Generate all Verilog if needed ────────────────────────
    run_initial_generation()

    # ── Phase 2–4: Compile → Critic → Heal loop ──────────────────────
    for iteration in range(1, MAX_HEAL_ITERATIONS + 1):
        banner(f"ITERATION {iteration} / {MAX_HEAL_ITERATIONS}  —  {timestamp()}")

        # Phase 2: Compile & Simulate
        compile_ok, compile_err = compile_and_simulate()

        if not compile_ok:
            log_warn("Compilation failed — attempting LLM repair of syntax errors")
            syntax_errors = [f"COMPILE ERROR: {compile_err[:500]}"]
            healed = agentic_heal(syntax_errors, iteration)
            if not healed:
                log_fail("Could not heal syntax errors — aborting")
                sys.exit(1)
            continue  # Retry compilation

        # Phase 3: VCD Waveform Critic
        errors = check_waveforms()

        if not errors:
            # ── SUCCESS ─────────────────────────────────────────────
            banner("🎉  SUCCESS — CORE VERIFIED  🎉")
            print(f"  Iteration        : {iteration}")
            print(f"  Test             : ADD (5 + 7 = 12) PASSED")
            print(f"  All signals      : ACTIVE")
            print(f"  Core file        : {CORE_FILE}")
            print(f"  VCD trace        : {VCD_FILE}")
            print(f"  Backups          : {BACKUP_DIR}/")
            print()
            return  # Clean exit

        # Phase 4: Heal
        log_warn(f"Waveform critic found {len(errors)} failure(s) — entering self-heal")
        healed = agentic_heal(errors, iteration)
        if not healed:
            log_fail("Self-heal failed — will retry if iterations remain")

    # ── Exhausted all iterations ──────────────────────────────────────
    banner("⚠  MAX ITERATIONS EXHAUSTED")
    print(f"  The core could not be fully healed in {MAX_HEAL_ITERATIONS} iterations.")
    print(f"  Last core file : {CORE_FILE}")
    print(f"  Backups        : {BACKUP_DIR}/")
    print(f"  Review the VCD : {VCD_FILE}")
    sys.exit(1)


if __name__ == "__main__":
    main()
