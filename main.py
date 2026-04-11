#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║            SILICON REFLEX — Push-Button RV32I Compiler                      ║
║                                                                              ║
║   Configuration-driven, CLI-enabled autonomous EDA pipeline:                 ║
║     --target all   → Generate all modules + Compile + Simulate + Heal        ║
║     --target <mod> → Generate a single module from processor_spec.json       ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import re
import sys
import json
import time
import shutil
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any

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
PROJECT_ROOT = Path(__file__).parent.resolve()
SPEC_FILE    = PROJECT_ROOT / "processor_spec.json"
VCD_FILE     = PROJECT_ROOT / "simulation_trace.vcd"
BACKUP_DIR   = PROJECT_ROOT / "backups"
SIM_BINARY   = PROJECT_ROOT / "obj_dir" / "Vtestbench"

# ── Global Hardware Axioms ───────────────────────────────────────────────────
# Injected into EVERY generation and healing prompt without exception.

HARDWARE_RULES = """\
Use non-blocking assignments (<=) in clocked blocks. \
Never use blocking assignments (=) in clocked blocks. \
Use always @(*) for combinational logic. \
Provide default assignments to prevent latches. \
Variables assigned inside always blocks MUST be declared as 'reg'. Do not assign to 'wire' inside procedural blocks."""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFIGURATION LOADER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def load_spec(spec_path: Path) -> Dict[str, Any]:
    """
    Load and validate the processor specification JSON.
    Returns the parsed dict or exits on failure.
    """
    if not spec_path.exists():
        print(f"  ✗ FATAL: Specification file not found: {spec_path}")
        sys.exit(1)

    try:
        with open(spec_path, "r") as f:
            spec = json.load(f)
    except json.JSONDecodeError as e:
        print(f"  ✗ FATAL: Invalid JSON in {spec_path.name}: {e}")
        sys.exit(1)

    # Validate required top-level keys
    for key in ("project", "modules", "verification", "alu_encodings"):
        if key not in spec:
            print(f"  ✗ FATAL: Missing required key '{key}' in {spec_path.name}")
            sys.exit(1)

    return spec


def build_alu_encoding_string(spec: Dict) -> str:
    """Format ALU encodings from the spec into a Verilog localparam block."""
    lines = []
    for name, value in spec["alu_encodings"].items():
        lines.append(f"localparam {name:12s} = {value};")
    return "\n".join(lines)


def build_locked_interfaces(spec: Dict) -> str:
    """Build a summary of all sub-module interfaces for the healing prompt."""
    lines = []
    for i, (mod_name, mod) in enumerate(spec["modules"].items(), 1):
        if mod_name != spec["project"]["heal_target"]:
            lines.append(f"{i}. {mod_name}: {mod['interface'].splitlines()[0]}")
    return "\n".join(lines)


def get_verilog_sources(spec: Dict) -> List[str]:
    """Build the list of Verilog source files from the spec."""
    sources = [spec["project"]["sim_driver"], "testbench.v"]
    for mod_name, mod in spec["modules"].items():
        sources.append(mod["file"])
    return sources


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

def generate_single_module(spec: Dict, module_name: str):
    """
    Generate a single module by looking it up in the processor spec.
    Prepends HARDWARE_RULES to the constraints before calling the LLM.
    """
    section(f"📐  GENERATING MODULE: {module_name}")

    if module_name not in spec["modules"]:
        log_fail(f"Module '{module_name}' not found in processor_spec.json")
        available = ", ".join(spec["modules"].keys())
        log_info(f"Available modules: {available}")
        sys.exit(1)

    # Lazy import
    try:
        from pipeline.generate_rtl import generate_component
    except ImportError as e:
        log_fail(f"Could not import generate_component: {e}")
        sys.exit(1)

    mod = spec["modules"][module_name]
    display_name = mod.get("display_name", module_name)
    interface = mod["interface"]

    # Build enriched constraints: HARDWARE_RULES + module-specific constraints
    enriched_constraints = f"[STRICT HARDWARE RULES]\n{HARDWARE_RULES}\n\n"

    # For the top-level core, also inject ALU encodings
    if mod.get("is_top_level", False):
        alu_block = build_alu_encoding_string(spec)
        enriched_constraints += f"[GROUND-TRUTH ALU ENCODINGS — COPY THESE EXACTLY]\n{alu_block}\n\n"

    enriched_constraints += f"[MODULE-SPECIFIC CONSTRAINTS]\n{mod['constraints']}"

    target_file = PROJECT_ROOT / mod["file"]
    if target_file.exists():
        log_info(f"{mod['file']} already exists — skipping generation")
        return

    log_info(f"Generating {display_name}...")
    generate_component(display_name, interface, enriched_constraints, filename=mod["file"])

    if target_file.exists():
        log_ok(f"{mod['file']} generated successfully")
    else:
        log_fail(f"Failed to generate {mod['file']}")
        sys.exit(1)


def run_initial_generation(spec: Dict):
    """
    Generate ALL modules defined in the processor spec.
    Skips any file that already exists on disk.
    """
    section("📐  PHASE 1: RAG-DRIVEN VERILOG GENERATION")

    # Lazy import
    try:
        from pipeline.generate_rtl import generate_component
    except ImportError as e:
        log_warn(f"Could not import generate_component: {e}")
        log_info("Skipping generation — assuming pre-existing Verilog files.")
        return

    alu_block = build_alu_encoding_string(spec)

    for mod_name, mod in spec["modules"].items():
        target = PROJECT_ROOT / mod["file"]
        display_name = mod.get("display_name", mod_name)

        if target.exists():
            log_info(f"{mod['file']} already exists — skipping generation")
            continue

        # Build enriched constraints
        enriched_constraints = f"[STRICT HARDWARE RULES]\n{HARDWARE_RULES}\n\n"
        if mod.get("is_top_level", False):
            enriched_constraints += f"[GROUND-TRUTH ALU ENCODINGS — COPY THESE EXACTLY]\n{alu_block}\n\n"
        enriched_constraints += f"[MODULE-SPECIFIC CONSTRAINTS]\n{mod['constraints']}"

        log_info(f"Generating {display_name}...")
        generate_component(display_name, mod["interface"], enriched_constraints, filename=mod["file"])

        if target.exists():
            log_ok(f"{mod['file']} generated successfully")
        else:
            log_fail(f"Failed to generate {mod['file']}")

    # Final check
    missing = [
        m["file"] for m in spec["modules"].values()
        if not (PROJECT_ROOT / m["file"]).exists()
    ]
    if missing:
        log_fail(f"Missing files after generation: {missing}")
        sys.exit(1)
    else:
        log_ok("All Verilog source files verified ✔")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PHASE 2: COMPILE & SIMULATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def compile_and_simulate(spec: Dict) -> Tuple[bool, str]:
    """
    Run Verilator to compile the design, then execute the simulation binary.
    Returns (success: bool, error_message: str).
    """
    section("🔧  PHASE 2: COMPILE & SIMULATE")

    top_module = spec["project"]["top_module"]
    sources = get_verilog_sources(spec)

    # ── Step 1: Verilator Compilation ───────────────────────────────────
    verilator_cmd = [
        "verilator",
        "-cc", "--exe", "--build",
        "-j", "0",
        "-Wno-fatal",
        "--trace",
        "--top-module", top_module,
    ] + sources

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
    sim_cmd = [str(SIM_BINARY), f"+loadmem=tests/{spec['project']['test_hex']}"]
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


def _check_signal_alive(vcd: VCDVCD, label: str, sig_path: str,
                        reset_time: int) -> Optional[str]:
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
    post_reset = [(t, v) for t, v in all_tv if t > reset_time]

    # Inherited value at the reset boundary
    inherited = _get_inherited_value(all_tv, reset_time)

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
        return (f"{label}: FLATLINED at {stuck_val} "
                f"(inherited={inherited}, post_reset_transitions={len(post_reset)})")

    # Signal is ACTIVE
    return None


def check_waveforms(spec: Dict) -> List[str]:
    """
    Parse simulation_trace.vcd and verify all monitored signals are alive.
    Also runs functional assertions defined in the spec.

    Returns a list of diagnostic error strings. Empty list = all pass.
    """
    section("🔬  PHASE 3: VCD WAVEFORM CRITIC")

    if not VCD_FILE.exists():
        return ["VCD file not found — simulation may have failed."]

    vcd = VCDVCD(str(VCD_FILE))
    log_ok(f"Parsed VCD: {len(vcd.signals)} signals")

    errors = []
    reset_time = spec["project"]["reset_time"]
    monitored = spec["verification"]["monitored_signals"]

    # ── Signal Liveness Checks ──────────────────────────────────────────
    for label, sig_path in monitored.items():
        diag = _check_signal_alive(vcd, label, sig_path, reset_time)
        if diag:
            print(f"    🔴 {label:30s} → {diag}")
            errors.append(diag)
        else:
            print(f"    🟢 {label:30s} → ACTIVE")

    # ── Functional Assertions ───────────────────────────────────────────
    func_checks = spec["verification"].get("functional_checks", [])
    if func_checks:
        section("🎯  PHASE 3b: FUNCTIONAL VERIFICATION")

    for check in func_checks:
        sig_path = check["signal"]
        expected = check["expected_value"]
        desc = check.get("description", sig_path)

        try:
            sig = vcd[sig_path]
            if sig.tv:
                final_val_str = sig.tv[-1][1]
                final_val = int(final_val_str, 2)
                if final_val == expected:
                    log_ok(f"{desc} — PASSED ✅ (got {final_val})")
                else:
                    msg = f"{desc} — FAILED (got {final_val}, expected {expected})"
                    log_fail(msg)
                    errors.append(msg)
            else:
                errors.append(f"{desc}: register has no data in VCD")
        except KeyError:
            log_warn(f"Signal '{sig_path}' not found in VCD — skipping check: {desc}")

    return errors


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PHASE 4: AGENTIC SELF-HEALING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _backup_core(core_file: Path, iteration: int):
    """Create a timestamped backup of the heal target."""
    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"{core_file.name}.iter_{iteration}_{ts}"
    shutil.copy2(str(core_file), str(backup_path))
    log_info(f"Backed up current code → {backup_path.name}")


def _sanitize_verilog(raw_text: str, module_name: str) -> Optional[str]:
    """
    Extract valid Verilog from the LLM response.
    Strips markdown fences and validates structural integrity.
    """
    text = raw_text
    text = re.sub(r"```(?:verilog|systemverilog|sv)?\s*\n?", "", text)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()

    # Extract only the target module if the LLM output extras
    pattern = rf"(module\s+{re.escape(module_name)}\b.*?endmodule)"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        text = match.group(1)

    # Validate structural integrity
    if f"module {module_name}" not in text:
        return None
    if "endmodule" not in text:
        return None
    if "u_program_counter" not in text:
        return None
    if "u_alu" not in text:
        return None

    return text + "\n"


def agentic_heal(spec: Dict, errors: List[str], iteration: int) -> bool:
    """
    The Silicon Reflex: use VCD diagnostics to prompt the LLM
    to rewrite the control logic in the heal target.

    Returns True if the file was successfully patched, False on failure.
    """
    section("🤖  PHASE 4: AGENTIC SELF-HEALING")

    heal_target = spec["project"]["heal_target"]
    core_mod = spec["modules"][heal_target]
    core_file = PROJECT_ROOT / core_mod["file"]
    llm_model = spec["project"]["llm_model"]
    alu_block = build_alu_encoding_string(spec)
    locked_if = build_locked_interfaces(spec)

    # ── Step 1: Backup ──────────────────────────────────────────────────
    _backup_core(core_file, iteration)

    # ── Step 2: Read current source ────────────────────────────────────
    current_source = core_file.read_text()

    # ── Step 3: Build the diagnostic prompt ────────────────────────────
    error_block = "\n".join(f"  - {e}" for e in errors)

    prompt = f"""\
You are an expert Verilog RTL engineer debugging a single-cycle RV32I RISC-V processor.

[STRICT HARDWARE RULES]
{HARDWARE_RULES}

[GROUND-TRUTH ALU ENCODINGS — COPY THESE EXACTLY]
{alu_block}

[LOCKED SUB-MODULE INTERFACES — DO NOT CHANGE PORT NAMES]
{locked_if}

[VCD DIAGNOSTIC FAILURES]
The following failures were detected by the automated waveform critic after simulating
the processor with the {spec['project']['test_hex']} test:
{error_block}

[CURRENT BROKEN SOURCE — {core_mod['file']}]
{current_source}

[YOUR TASK]
Rewrite the COMPLETE {core_mod['file']} module to fix the VCD diagnostic failures above.

CRITICAL REQUIREMENTS:
1. You MUST keep ALL sub-module instantiations with the EXACT same port connections.
2. You MUST fix the control unit's always @(*) block to correctly drive:
   - reg_write: Assert HIGH for R-type (0110011) and I-type (0010011) instructions.
   - alu_control: Use the EXACT ALU encodings listed above (e.g., SUB = 4'b1000, NOT 4'b0001).
   - alu_src_b: Assert HIGH for I-type instructions (ALU operand B = immediate).
   - pc_sel: Assert HIGH when a B-type branch is taken.
3. You MUST provide default assignments at the top of the always block.
4. You MUST NOT change any module ports or sub-module instantiation bindings.

OUTPUT ONLY the complete, valid Verilog for the {heal_target} module.
Do NOT include markdown fences, explanations, or commentary. Just the code."""

    # ── Step 4: Call LLM ───────────────────────────────────────────────
    model = genai.GenerativeModel(llm_model)
    log_info(f"Calling {llm_model} (temperature=0.2)...")

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
    clean_code = _sanitize_verilog(raw_text, heal_target)

    if clean_code is None:
        log_fail("LLM output failed structural validation — skipping overwrite")
        log_info(f"Raw output preview: {raw_text[:200]}...")
        return False

    # ── Step 6: Atomic overwrite ───────────────────────────────────────
    old_lines = len(current_source.splitlines())
    new_lines = len(clean_code.splitlines())

    core_file.write_text(clean_code)
    log_ok(f"Wrote healed {core_mod['file']} ({len(clean_code)} bytes)")
    log_info(f"Lines: {old_lines} → {new_lines} (delta: {new_lines - old_lines:+d})")

    return True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CLI & MAIN EXECUTION LOOP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Silicon Reflex — Configuration-driven RV32I Push-Button Compiler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python3 main.py                        # Generate all + compile + simulate + heal
  python3 main.py --target all           # Same as above
  python3 main.py --target alu           # Generate only the ALU module
  python3 main.py --target rv32i_core    # Generate only the top-level core
  python3 main.py --spec custom.json     # Use a custom processor spec
  python3 main.py --list-modules         # Show available module names
""",
    )
    parser.add_argument(
        "--target",
        default="all",
        help="Module to generate. Use 'all' for full pipeline. (default: all)",
    )
    parser.add_argument(
        "--spec",
        default=str(SPEC_FILE),
        help=f"Path to processor specification JSON. (default: {SPEC_FILE.name})",
    )
    parser.add_argument(
        "--list-modules",
        action="store_true",
        help="List all available module names from the spec and exit.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # ── Load specification ─────────────────────────────────────────────
    spec = load_spec(Path(args.spec))
    project = spec["project"]

    # ── --list-modules ─────────────────────────────────────────────────
    if args.list_modules:
        print("\nAvailable modules in processor_spec.json:\n")
        for name, mod in spec["modules"].items():
            display = mod.get("display_name", name)
            flag = " ★ (top-level)" if mod.get("is_top_level") else ""
            print(f"  {name:25s} → {mod['file']:30s} {display}{flag}")
        print(f"\nUse: python3 main.py --target <module_name>")
        return

    # ── Single-module generation (--target <name>) ────────────────────
    if args.target != "all":
        banner(f"SILICON REFLEX — Single Module: {args.target}")
        print(f"  Spec     : {args.spec}")
        print(f"  Target   : {args.target}")
        print(f"  Time     : {timestamp()}")

        generate_single_module(spec, args.target)

        log_ok(f"Module '{args.target}' generation complete.")
        log_info("Simulation/healing loop skipped (single-module mode).")
        return

    # ── Full pipeline (--target all) ──────────────────────────────────
    heal_target = project["heal_target"]
    heal_file = spec["modules"][heal_target]["file"]
    max_iters = project["max_heal_iterations"]

    banner("SILICON REFLEX — Push-Button RV32I Compiler")
    print(f"  Project  : {PROJECT_ROOT}")
    print(f"  Spec     : {Path(args.spec).name}")
    print(f"  Target   : {heal_file}")
    print(f"  Test     : {project['test_hex']}")
    print(f"  Max Iters: {max_iters}")
    print(f"  LLM      : {project['llm_model']}")
    print(f"  Time     : {timestamp()}")

    # Phase 1: Generate all Verilog if needed
    run_initial_generation(spec)

    # Phase 2–4: Compile → Critic → Heal loop
    for iteration in range(1, max_iters + 1):
        banner(f"ITERATION {iteration} / {max_iters}  —  {timestamp()}")

        # Phase 2: Compile & Simulate
        compile_ok, compile_err = compile_and_simulate(spec)

        if not compile_ok:
            log_warn("Compilation failed — attempting LLM repair of syntax errors")
            syntax_errors = [f"COMPILE ERROR: {compile_err[:500]}"]
            healed = agentic_heal(spec, syntax_errors, iteration)
            if not healed:
                log_fail("Could not heal syntax errors — aborting")
                sys.exit(1)
            continue

        # Phase 3: VCD Waveform Critic
        errors = check_waveforms(spec)

        if not errors:
            # ── SUCCESS ─────────────────────────────────────────────
            core_file = PROJECT_ROOT / heal_file
            banner("🎉  SUCCESS — CORE VERIFIED  🎉")
            print(f"  Iteration        : {iteration}")
            print(f"  Test             : {project['test_hex']} PASSED")
            print(f"  All signals      : ACTIVE")
            print(f"  Core file        : {core_file}")
            print(f"  VCD trace        : {VCD_FILE}")
            print(f"  Backups          : {BACKUP_DIR}/")
            print()
            return

        # Phase 4: Heal
        log_warn(f"Waveform critic found {len(errors)} failure(s) — entering self-heal")
        healed = agentic_heal(spec, errors, iteration)
        if not healed:
            log_fail("Self-heal failed — will retry if iterations remain")

    # ── Exhausted all iterations ──────────────────────────────────────
    banner("⚠  MAX ITERATIONS EXHAUSTED")
    print(f"  The core could not be fully healed in {max_iters} iterations.")
    print(f"  Last core file : {PROJECT_ROOT / heal_file}")
    print(f"  Backups        : {BACKUP_DIR}/")
    print(f"  Review the VCD : {VCD_FILE}")
    sys.exit(1)


if __name__ == "__main__":
    main()
