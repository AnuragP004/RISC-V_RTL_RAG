module branch_unit (
    input  [31:0] rs1_data,
    input  [31:0] rs2_data,
    input  [2:0]  funct3,
    output reg    branch_taken
);

    // Combinational logic for branch condition evaluation
    always @(*) begin
        // Default assignment to prevent latches.
        // The branch is not taken by default.
        branch_taken = 1'b0;

        case (funct3)
            3'b000: // BEQ: Branch if Equal
                if (rs1_data == rs2_data)
                    branch_taken = 1'b1;
            3'b001: // BNE: Branch if Not Equal
                if (rs1_data != rs2_data)
                    branch_taken = 1'b1;
            3'b100: // BLT: Branch if Less Than (signed)
                if ($signed(rs1_data) < $signed(rs2_data))
                    branch_taken = 1'b1;
            3'b101: // BGE: Branch if Greater Than or Equal (signed)
                if ($signed(rs1_data) >= $signed(rs2_data))
                    branch_taken = 1'b1;
            3'b110: // BLTU: Branch if Less Than (unsigned)
                if (rs1_data < rs2_data)
                    branch_taken = 1'b1;
            3'b111: // BGEU: Branch if Greater Than or Equal (unsigned)
                if (rs1_data >= rs2_data)
                    branch_taken = 1'b1;
        endcase
    end

endmodule