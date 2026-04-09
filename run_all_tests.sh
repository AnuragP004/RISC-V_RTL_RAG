#!/bin/bash
echo "=== Running RV32I ISA Test Suite ==="
SUCCESS=0
FAIL=0
# Assuming riscv-tests hex files are in a /tests folder
for test in tests/rv32ui-p-*.hex; do
    ./obj_dir/Vtestbench +loadmem="$test" > /dev/null 2>&1
    # Check your simulator's exit code or a specific register state here
    if [ $? -eq 0 ]; then
        echo "[PASS] $test"
        ((SUCCESS++))
    else
        echo "[FAIL] $test"
        ((FAIL++))
    fi
done
echo "=== Results: $SUCCESS / 47 Passed ==="
