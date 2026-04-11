module branch_unit (
    input  [31:0] rs1_data,
    input  [31:0] rs2_data,
    input  [2:0]  funct3,
    output reg    branch_taken
);

    // Branch comparison logic
    always @(*) begin
        // Default assignment to prevent unintended latch inference
        branch_taken = 1'b0;

        case (funct3)
            3'b000: begin // BEQ: Branch if Equal
                if (rs1_data == rs2_data) begin
                    branch_taken = 1'b1;
                end
            end
            3'b001: begin // BNE: Branch if Not Equal
                if (rs1_data != rs2_data) begin
                    branch_taken = 1'b1;
                end
            end
            3'b100: begin // BLT: Branch if Less Than (signed)
                if ($signed(rs1_data) < $signed(rs2_data)) begin
                    branch_taken = 1'b1;
                end
            end
            3'b101: begin // BGE: Branch if Greater Than or Equal (signed)
                if ($signed(rs1_data) >= $signed(rs2_data)) begin
                    branch_taken = 1'b1;
                end
            end
            3'b110: begin // BLTU: Branch if Less Than (unsigned)
                if (rs1_data < rs2_data) begin
                    branch_taken = 1'b1;
                end
            end
            3'b111: begin // BGEU: Branch if Greater Than or Equal (unsigned)
                if (rs1_data >= rs2_data) begin
                    branch_taken = 1'b1;
                end
            end
            default: begin
                branch_taken = 1'b0;
            end
        endcase
    end

endmodule