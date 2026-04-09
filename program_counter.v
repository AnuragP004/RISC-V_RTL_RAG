module program_counter (
    input  clk,
    input  reset,
    input  [31:0] branch_target,
    input         pc_sel, // 1 to branch, 0 to increment
    output reg [31:0] pc
);

    always @(posedge clk) begin
        if (reset) begin
            pc <= 32'h00000000;
        end else begin
            if (pc_sel) begin
                pc <= branch_target;
            end else begin
                pc <= pc + 32'd4;
            end
        end
    end

endmodule