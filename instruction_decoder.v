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

    // RISC-V RV32I opcodes
    localparam OPCODE_LUI    = 7'b0110111;
    localparam OPCODE_AUIPC  = 7'b0010111;
    localparam OPCODE_JAL    = 7'b1101111;
    localparam OPCODE_JALR   = 7'b1100111; // I-type
    localparam OPCODE_BRANCH = 7'b1100011; // B-type
    localparam OPCODE_LOAD   = 7'b0000011; // I-type
    localparam OPCODE_STORE  = 7'b0100011; // S-type
    localparam OPCODE_IMM    = 7'b0010011; // I-type
    localparam OPCODE_REG    = 7'b0110011; // R-type

    always @(*) begin
        // Default assignments to prevent latches
        opcode = 7'b0;
        rd     = 5'b0;
        funct3 = 3'b0;
        rs1    = 5'b0;
        rs2    = 5'b0;
        funct7 = 7'b0;
        imm    = 32'b0;

        // Field extraction from instruction
        opcode = instr[6:0];
        rd     = instr[11:7];
        funct3 = instr[14:12];
        rs1    = instr[19:15];
        rs2    = instr[24:20];
        funct7 = instr[31:25];
        
        // Immediate generation based on instruction type (determined by opcode)
        case (opcode)
            // U-Type: LUI, AUIPC
            OPCODE_LUI, OPCODE_AUIPC: begin
                imm = {instr[31:12], 12'b0};
            end

            // J-Type: JAL
            OPCODE_JAL: begin
                imm = { {12{instr[31]}}, instr[19:12], instr[20], instr[30:21], 1'b0 };
            end

            // I-Type: JALR, Loads, Immediate Arithmetic/Logic
            OPCODE_JALR, OPCODE_LOAD, OPCODE_IMM: begin
                imm = { {20{instr[31]}}, instr[31:20] };
            end

            // B-Type: Branches
            OPCODE_BRANCH: begin
                imm = { {20{instr[31]}}, instr[7], instr[30:25], instr[11:8], 1'b0 };
            end

            // S-Type: Stores
            OPCODE_STORE: begin
                imm = { {20{instr[31]}}, instr[31:25], instr[11:7] };
            end

            // R-Type and others have no immediate, defaults to 0
            default: begin
                imm = 32'b0;
            end
        endcase
    end

endmodule