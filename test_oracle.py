#!/usr/bin/env python3
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

from vcdvcd import VCDVCD

PROJECT_ROOT = Path(__file__).parent.resolve()
DEFAULT_SIM_BINARY = PROJECT_ROOT / "obj_dir" / "Vtestbench"
DEFAULT_TESTS_DIR = PROJECT_ROOT / "tests"
DEFAULT_VCD = PROJECT_ROOT / "simulation_trace.vcd"

SIG_GP = "TOP.testbench.dut.u_register_file.registers[3][31:0]"
SIG_PC = "TOP.testbench.dut.u_program_counter.pc[31:0]"
RESET_TIME = 10

@dataclass
class TestResult:
    test_name: str
    status: str
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)

def parse_int_from_vcd(bitstr: str):
    if bitstr is None: return None
    s = bitstr.strip().lower()
    if not s or "x" in s or "z" in s: return None
    if s.startswith("0b"): s = s[2:]
    return int(s, 2)

def evaluate_vcd(vcd_path: Path) -> Tuple[str, str, Dict]:
    if not vcd_path.exists():
        return "FAIL", "vcd_missing", {}

    vcd = VCDVCD(str(vcd_path))

    # Check PC is alive
    try:
        pc_tv = vcd[SIG_PC].tv
    except KeyError:
        return "FAIL", "pc_not_found", {}

    values = {v for t, v in pc_tv if t > RESET_TIME}
    if len(values) <= 1:
        return "FAIL", "pc_flatlined", {}

    # Extract GP (x3) trace to find the pass/fail value
    try:
        gp_sig = vcd[SIG_GP]
        gp_val = parse_int_from_vcd(gp_sig.tv[-1][1]) if gp_sig.tv else 0
    except KeyError:
        return "FAIL", "gp_not_found", {}

    if gp_val == 1:
        return "PASS", "gp_equals_1", {"gp": gp_val}
    elif gp_val > 1:
        test_num = gp_val >> 1
        return "FAIL", f"failed_test_case_{test_num}", {"gp": gp_val}
    else:
        return "FAIL", "gp_did_not_reach_pass_value", {"gp": gp_val}

def run_single_test(sim_binary, hex_path, vcd_path, timeout_s=10):
    test_name = hex_path.stem
    cmd = [str(sim_binary), f"+loadmem={hex_path}"]
    try:
        proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return TestResult(test_name, "FAIL", "simulation_timeout")

    if proc.returncode != 0:
        return TestResult(test_name, "FAIL", f"simulator_exit_{proc.returncode}")

    status, reason, details = evaluate_vcd(vcd_path)
    return TestResult(test_name, status, reason, details)

def main():
    tests = sorted(Path(DEFAULT_TESTS_DIR).glob("rv32ui-p-*.hex"))
    results = []
    
    status_col = {"PASS": "\033[92m", "FAIL": "\033[91m"}
    reset = "\033[0m"

    print(f"\n{'='*70}")
    print(f"  {'Test Name':<30s}  {'Status':<15s}  Reason")
    print(f"{'='*70}")

    for test_hex in tests:
        res = run_single_test(DEFAULT_SIM_BINARY, test_hex, DEFAULT_VCD)
        results.append(res)
        color = status_col.get(res.status, "")
        print(f"  {res.test_name:<30s}  {color}{res.status:<15s}{reset}  {res.reason}")

    print(f"{'='*70}")
    passes = sum(1 for r in results if r.status == "PASS")
    print(f"\n  PASS: {passes}  |  FAIL: {len(results)-passes}  |  TOTAL: {len(results)}")
    print(f"  Pass Rate: {passes}/{len(results)} rv32ui tests")
    
    with open(Path(DEFAULT_TESTS_DIR) / "oracle_results.json", "w") as f:
        json.dump([{"test": r.test_name, "status": r.status, "reason": r.reason} for r in results], f, indent=2)
    return 1 if passes < len(results) else 0

if __name__ == "__main__":
    sys.exit(main())
