module register_file (
    input  clk,
    input  [4:0]  rs1,
    input  [4:0]  rs2,
    input  [4:0]  rd,
    input  [31:0] write_data,
    input         reg_write,
    output [31:0] rs1_data,
    output [31:0] rs2_data
);

    // 31 general-purpose 32-bit registers.
    // Index 0 is not implemented, as x0 is hardwired to zero.
    reg [31:0] registers[31:1];

    // Asynchronous (combinational) read for rs1
    // If rs1 is 0, return 0. Otherwise, return the value from the register array.
    assign rs1_data = (rs1 == 5'b0) ? 32'b0 : registers[rs1];

    // Asynchronous (combinational) read for rs2
    // If rs2 is 0, return 0. Otherwise, return the value from the register array.
    assign rs2_data = (rs2 == 5'b0) ? 32'b0 : registers[rs2];

    // Synchronous write on the positive edge of the clock
    always @(posedge clk) begin
        if (reg_write && (rd != 5'b0)) begin
            registers[rd] <= write_data;
        end
    end

endmodule