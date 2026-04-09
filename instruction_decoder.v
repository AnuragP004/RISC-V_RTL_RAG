module decoder (
    input  [31:0] instr,
    output reg [6:0]  opcode,
    output reg [4:0]  rd,
    output reg [2:0]  funct3,
    output reg [4:0]  rs1,
    output reg [4:0]  rs2,
    output reg [6:0]  funct7,
    output reg [31:0] imm
);

    always @(*) begin
        // [Rule 4] Default assignments at the top of the combinational block
        opcode = 7'b0;
        rd     = 5'b0;
        funct3 = 3'b0;
        rs1    = 5'b0;
        rs2    = 5'b0;
        funct7 = 7'b0;
        imm    = 32'b0;

        // The opcode is always located in bits [6:0]
        opcode = instr[6:0];

        // Decode remaining fields and immediate based on the instruction type
        case (opcode)
            // U-Type: LUI (0110111), AUIPC (0010111)
            7'b0110111, 7'b0010111: begin
                rd  = instr[11:7];
                imm = {instr[31:12], 12'b0};
            end

            // J-Type: JAL (1101111)
            7'b1101111: begin
                rd  = instr[11:7];
                // imm[20:1] = {instr[31], instr[19:12], instr[20], instr[30:21]}
                imm = {{11{instr[31]}}, instr[31], instr[19:12], instr[20], instr[30:21], 1'b0};
            end

            // I-Type: JALR (1100111), LOAD (0000011), OP-IMM (0010011)
            7'b1100111, 7'b0000011, 7'b0010011: begin
                rd     = instr[11:7];
                funct3 = instr[14:12];
                rs1    = instr[19:15];
                // Sign-extend from the most significant bit of the immediate
                imm    = {{20{instr[31]}}, instr[31:20]};
            end

            // B-Type: BRANCH (1100011)
            7'b1100011: begin
                funct3 = instr[14:12];
                rs1    = instr[19:15];
                rs2    = instr[24:20];
                // [CRITICAL] imm[12:1] = {instr[31], instr[7], instr[30:25], instr[11:8]}
                imm    = {{19{instr[31]}}, instr[31], instr[7], instr[30:25], instr[11:8], 1'b0};
            end

            // S-Type: STORE (0100011)
            7'b0100011: begin
                funct3 = instr[14:12];
                rs1    = instr[19:15];
                rs2    = instr[24:20];
                // imm[11:0] = {instr[31:25], instr[11:7]}
                imm    = {{20{instr[31]}}, instr[31:25], instr[11:7]};
            end

            // R-Type: OP (0110011)
            7'b0110011: begin
                rd     = instr[11:7];
                funct3 = instr[14:12];
                rs1    = instr[19:15];
                rs2    = instr[24:20];
                funct7 = instr[31:25];
                // No immediate for R-Type, imm remains its default 0 value
            end

            default: begin
                // For any illegal or unsupported opcodes, all outputs retain their
                // default values (mostly 0), except for the opcode field itself,
                // which will pass through the unrecognized opcode.
            end
        endcase
    end

endmodule