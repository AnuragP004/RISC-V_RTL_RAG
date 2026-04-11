#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
SIM_BIN="$ROOT_DIR/obj_dir/Vtestbench"
ARTIFACT="$ROOT_DIR/tests/oracle_results.json"
PYTHON_BIN="$ROOT_DIR/venv/bin/python"

echo "=== Running RV32I ISA Test Suite (Measured Oracle) ==="

if [[ ! -x "$SIM_BIN" ]]; then
  echo "Simulator binary missing at $SIM_BIN"
  echo "Build first:"
  echo "  verilator -cc --exe --build -j 0 -Wno-fatal --trace --top-module testbench sim_main.cpp testbench.v rv32i_core.v program_counter.v instruction_decoder.v register_file.v branch_unit.v alu.v load_store_unit.v"
  exit 2
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

"$PYTHON_BIN" "$ROOT_DIR/test_oracle.py"
STATUS=$?

echo "Oracle artifact: $ARTIFACT"
exit "$STATUS"
