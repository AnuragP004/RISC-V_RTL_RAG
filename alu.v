module alu (
    input  [31:0] a,
    input  [31:0] b,
    input  [3:0]  alu_control,
    output reg [31:0] result,
    output zero
);

    // ALU operation encodings (based on a common RISC-V control scheme)
    localparam ALU_ADD  = 4'b0000;
    localparam ALU_SUB  = 4'b1000; // ALU_ADD with a control bit high
    localparam ALU_SLL  = 4'b0001;
    localparam ALU_SLT  = 4'b0010;
    localparam ALU_SLTU = 4'b0011;
    localparam ALU_XOR  = 4'b0100;
    localparam ALU_SRL  = 4'b0101;
    localparam ALU_SRA  = 4'b1101; // ALU_SRL with a control bit high
    localparam ALU_OR   = 4'b0110;
    localparam ALU_AND  = 4'b0111;
    localparam ALU_COPY_B = 4'b1111; // Used for LUI

    always_comb begin
        // Default assignment to prevent latch inference
        result = 32'b0;

        case (alu_control)
            ALU_ADD:  result = a + b;
            ALU_SUB:  result = a - b;
            ALU_SLL:  result = a << b[4:0];
            ALU_SLT:  result = ($signed(a) < $signed(b)) ? 32'd1 : 32'd0;
            ALU_SLTU: result = (a < b) ? 32'd1 : 32'd0;
            ALU_XOR:  result = a ^ b;
            ALU_SRL:  result = a >> b[4:0];
            ALU_SRA:  result = $signed(a) >>> b[4:0];
            ALU_OR:   result = a | b;
            ALU_AND:  result = a & b;
            ALU_COPY_B: result = b;
            default:  result = 32'b0;
        endcase
    end

    // The 'zero' flag is high if the result is 0.
    assign zero = (result == 32'b0);

endmodule