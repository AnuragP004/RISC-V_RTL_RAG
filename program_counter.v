module program_counter (
    input  clk,
    input  reset,
    input  [31:0] branch_target,
    input         pc_sel,
    output reg [31:0] pc
);

    // This register holds the next value for the program counter.
    // The logic is combinational.
    reg [31:0] pc_next;

    always @(*) begin
        // Default behavior is to increment the PC by 4 to fetch the next instruction.
        pc_next = pc + 32'd4;

        // If pc_sel is asserted, a branch or jump is taken.
        // The next PC value is the branch_target address.
        if (pc_sel) begin
            pc_next = branch_target;
        end
    end

    // This is the sequential block that updates the PC register on each clock cycle.
    always @(posedge clk) begin
        if (reset) begin
            // On reset, the processor starts execution from address 0.
            pc <= 32'h00000000;
        end else begin
            // On a normal clock edge, update the PC with the pre-calculated next value.
            pc <= pc_next;
        end
    end

endmodule