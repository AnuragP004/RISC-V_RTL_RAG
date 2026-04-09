module rv32i_core (
    input  clk,
    input  reset,
    input  [31:0] instr_mem_data,
    output [31:0] instr_mem_addr
);

    // --- Internal Wires ---

    // Program Counter Signals
    wire [31:0] pc;
    wire [31:0] branch_target;

    // Decoder Outputs
    wire [6:0]  opcode;
    wire [4:0]  rd;
    wire [2:0]  funct3;
    wire [4:0]  rs1;
    wire [4:0]  rs2;
    wire [6:0]  funct7;
    wire [31:0] imm;

    // Register File Signals
    wire [31:0] rs1_data;
    wire [31:0] rs2_data;
    wire [31:0] write_data;

    // Branch Unit Output
    wire        branch_taken;

    // ALU Signals
    wire [31:0] alu_a;
    wire [31:0] alu_b;
    wire [31:0] alu_result;
    wire        alu_zero;

    // --- Control Signals (driven by the combinational control block) ---
    reg  reg_write;
    reg  pc_sel;
    reg  alu_src_b; // 0 for rs2_data, 1 for immediate
    reg  [3:0] alu_control;

    // --- Datapath Connections ---

    // Instruction Memory Address Output
    assign instr_mem_addr = pc;

    // ALU Operand Selection
    assign alu_a = rs1_data;
    assign alu_b = alu_src_b ? imm : rs2_data;
    
    // Branch Target Calculation (for B-type instructions)
    assign branch_target = pc + imm;

    // Register File Write Data Path (from ALU)
    assign write_data = alu_result;

    // --- Sub-module Instantiations ---

    program_counter u_program_counter (
        .clk           (clk),
        .reset         (reset),
        .branch_target (branch_target),
        .pc_sel        (pc_sel),
        .pc            (pc)
    );

    decoder u_decoder (
        .instr  (instr_mem_data),
        .opcode (opcode),
        .rd     (rd),
        .funct3 (funct3),
        .rs1    (rs1),
        .rs2    (rs2),
        .funct7 (funct7),
        .imm    (imm)
    );

    register_file u_register_file (
        .clk        (clk),
        .rs1        (rs1),
        .rs2        (rs2),
        .rd         (rd),
        .write_data (write_data),
        .reg_write  (reg_write),
        .rs1_data   (rs1_data),
        .rs2_data   (rs2_data)
    );

    branch_unit u_branch_unit (
        .rs1_data     (rs1_data),
        .rs2_data     (rs2_data),
        .funct3       (funct3),
        .branch_taken (branch_taken)
    );

    alu u_alu (
        .a           (alu_a),
        .b           (alu_b),
        .alu_control (alu_control),
        .result      (alu_result),
        .zero        (alu_zero)
    );

    // --- Main Control Logic ---

    always @(*) begin
        // Default assignments to prevent latches
        reg_write   = 1'b0;
        alu_src_b   = 1'b0;       // Default to register source (rs2)
        pc_sel      = 1'b0;       // Default to PC+4
        alu_control = 4'b0000;    // Default to ADD

        case (opcode)
            // R-Type: ADD, SUB, SLL, SLT, SLTU, XOR, SRL, SRA, OR, AND
            7'b0110011: begin
                reg_write = 1'b1;
                alu_src_b = 1'b0; // ALU operand is from register file (rs2)
                case (funct3)
                    3'b000: alu_control = (funct7[5]) ? 4'b0001 : 4'b0000; // SUB : ADD
                    3'b001: alu_control = 4'b0101; // SLL
                    3'b010: alu_control = 4'b0010; // SLT
                    3'b011: alu_control = 4'b0011; // SLTU
                    3'b100: alu_control = 4'b0111; // XOR
                    3'b101: alu_control = (funct7[5]) ? 4'b0110 : 4'b0100; // SRA : SRL
                    3'b110: alu_control = 4'b1000; // OR
                    3'b111: alu_control = 4'b1001; // AND
                    default: alu_control = 4'bxxxx;
                endcase
            end

            // I-Type: ADDI, SLTI, SLTIU, XORI, ORI, ANDI, SLLI, SRLI, SRAI
            7'b0010011: begin
                reg_write = 1'b1;
                alu_src_b = 1'b1; // ALU operand is from immediate
                case (funct3)
                    3'b000: alu_control = 4'b0000; // ADDI
                    3'b001: alu_control = 4'b0101; // SLLI
                    3'b010: alu_control = 4'b0010; // SLTI
                    3'b011: alu_control = 4'b0011; // SLTIU
                    3'b100: alu_control = 4'b0111; // XORI
                    3'b101: alu_control = (funct7[5]) ? 4'b0110 : 4'b0100; // SRAI : SRLI
                    3'b110: alu_control = 4'b1000; // ORI
                    3'b111: alu_control = 4'b1001; // ANDI
                    default: alu_control = 4'bxxxx;
                endcase
            end

            // B-Type: BEQ, BNE, BLT, BGE, BLTU, BGEU
            7'b1100011: begin
                reg_write = 1'b0; // Branches do not write to registers
                pc_sel = branch_taken; // If branch is taken, select branch target
            end

            default: begin
                // For unsupported opcodes (LOAD, STORE, JAL, etc.), treat as NOP.
                // All control signals retain their default values.
            end
        endcase
    end

endmodule