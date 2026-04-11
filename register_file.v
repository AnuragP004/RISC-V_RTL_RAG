module register_file (
    input  clk,
    input  [4:0]  rs1,
    input  [4:0]  rs2,
    input  [4:0]  rd,
    input  [31:0] write_data,
    input         reg_write,
    output reg [31:0] rs1_data,
    output reg [31:0] rs2_data
);

    // 31 general-purpose 32-bit registers (x1-x31)
    // Register x0 is hardwired to zero and does not need physical storage.
    reg [31:0] registers[1:31];

    // Synchronous write port
    // Write occurs on the positive clock edge.
    // Writes to register 0 are ignored to keep it hardwired to zero.
    always @(posedge clk) begin
        if (reg_write && (rd != 5'b0)) begin
            registers[rd] <= write_data;
        end
    end

    // Combinational read ports
    // The read logic is asynchronous.
    always_comb begin
        // Default assignments are implicitly handled by the ternary operators,
        // ensuring full coverage and no latch inference.
        
        // Read port 1: Handle hardwired x0
        rs1_data = (rs1 == 5'b0) ? 32'h00000000 : registers[rs1];

        // Read port 2: Handle hardwired x0
        rs2_data = (rs2 == 5'b0) ? 32'h00000000 : registers[rs2];
    end

endmodule