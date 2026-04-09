#include <iostream>
#include <memory>
#include "verilated.h"
#include "verilated_vcd_c.h"
#include "Vtestbench.h"

vluint64_t main_time = 0;
double sc_time_stamp() { return main_time; }

int main(int argc, char **argv) {
    // 1. Create context FIRST
    auto contextp = std::make_unique<VerilatedContext>();
    
    // 2. Pass arguments directly to the isolated context (THE FIX)
    contextp->commandArgs(argc, argv);
    
    // 3. Bind the testbench to this specific context
    auto top = std::make_unique<Vtestbench>(contextp.get());

    Verilated::traceEverOn(true);
    auto tracep = std::make_unique<VerilatedVcdC>();
    top->trace(tracep.get(), 99);
    tracep->open("simulation_trace.vcd");

    top->clk = 0;
    top->reset = 1;

    while (!contextp->gotFinish() && main_time < 200) {
        main_time++;
        top->clk = !top->clk;
        if (main_time > 10) top->reset = 0;
        top->eval();
        tracep->dump(main_time);
    }

    top->final();
    tracep->close();
    return 0;
}
