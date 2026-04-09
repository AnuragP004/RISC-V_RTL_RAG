module testbench (
    input clk,
    input reset
);
    wire [31:0] pc_wire;
    wire [31:0] instr_wire;

    // 8KB Instruction Memory
    reg [31:0] instr_memory [0:2047];

    // Load the hex file dynamically if passed via Verilator plusarg
    initial begin
        if ($test$plusargs("loadmem")) begin
            $readmemh("rv32ui-p-add.hex", instr_memory);
        end
    end

    // Fetch the instruction (PC is byte-addressed, array is word-addressed)
    assign instr_wire = instr_memory[pc_wire[31:2]];

    // Instantiate your AI-generated core
    rv32i_core dut (
        .clk(clk),
        .reset(reset),
        .instr_mem_data(instr_wire),
        .instr_mem_addr(pc_wire)
    );

endmodule