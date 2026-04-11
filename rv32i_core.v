module rv32i_core (
    input  clk,
    input  reset,
    input  [31:0] instr_mem_data,
    output [31:0] instr_mem_addr,
    output [31:0] data_mem_addr,
    output [31:0] data_mem_wdata,
    output        data_mem_we,
    output [3:0]  data_mem_byte_en,
    input  [31:0] data_mem_rdata
);

    // Ground-truth ALU Encodings
    localparam ALU_ADD      = 4'b0000;
    localparam ALU_SUB      = 4'b1000;
    localparam ALU_SLL      = 4'b0001;
    localparam ALU_SLT      = 4'b0010;
    localparam ALU_SLTU     = 4'b0011;
    localparam ALU_XOR      = 4'b0100;
    localparam ALU_SRL      = 4'b0101;
    localparam ALU_SRA      = 4'b1101;
    localparam ALU_OR       = 4'b0110;
    localparam ALU_AND      = 4'b0111;
    localparam ALU_COPY_B   = 4'b1111;
    
    // RV32I Opcodes
    localparam OPCODE_LUI    = 7'b0110111;
    localparam OPCODE_AUIPC  = 7'b0010111;
    localparam OPCODE_JAL    = 7'b1101111;
    localparam OPCODE_JALR   = 7'b1100111;
    localparam OPCODE_BRANCH = 7'b1100011;
    localparam OPCODE_LOAD   = 7'b0000011;
    localparam OPCODE_STORE  = 7'b0100011;
    localparam OPCODE_R_TYPE = 7'b0110011;
    localparam OPCODE_I_TYPE = 7'b0010011;
    
    // RV32I Funct3 Encodings
    localparam FUNCT3_ADDI_ADD_SUB = 3'b000;
    localparam FUNCT3_SLLI_SLL     = 3'b001;
    localparam FUNCT3_SLTI_SLT     = 3'b010;
    localparam FUNCT3_SLTIU_SLTU   = 3'b011;
    localparam FUNCT3_XORI_XOR     = 3'b100;
    localparam FUNCT3_SRLI_SRL_SRA = 3'b101;
    localparam FUNCT3_ORI_OR       = 3'b110;
    localparam FUNCT3_ANDI_AND     = 3'b111;
    
    // RV32I Funct7 Encodings
    localparam FUNCT7_SUB_SRA = 7'b0100000;
    
    //----------------------------------------------------------------
    // Internal Signals
    //----------------------------------------------------------------
    
    // PC signals
    wire [31:0] pc_out;
    reg  [1:0]  pc_sel;
    reg  [31:0] pc_jump_target;
    
    // Decoder signals
    wire [6:0]  opcode;
    wire [4:0]  rd;
    wire [2:0]  funct3;
    wire [4:0]  rs1;
    wire [4:0]  rs2;
    wire [6:0]  funct7;
    wire [31:0] imm;
    
    // Register File signals
    wire [31:0] rs1_data_out;
    wire [31:0] rs2_data_out;
    reg         reg_write;
    reg  [31:0] reg_write_data;
    
    // Branch Unit signals
    wire        branch_taken_wire;
    
    // ALU signals
    wire [31:0] alu_result_wire;
    wire        alu_zero_wire;
    reg  [31:0] alu_a;
    reg  [31:0] alu_b;
    reg  [3:0]  alu_control;
    
    // Load/Store Unit signals
    wire [31:0] lsu_read_data_out;
    wire [31:0] lsu_mem_data_out;
    wire [3:0]  lsu_mem_byte_en;
    reg         mem_read;
    reg         mem_write;
    
    // Control/Mux signals
    reg alu_src_a_sel; // 0: rs1_data, 1: pc
    reg alu_src_b_sel; // 0: rs2_data, 1: imm
    reg [1:0] wb_sel;  // 00: ALU, 01: Mem, 10: PC+4

    //----------------------------------------------------------------
    // Sub-Module Instantiations
    //----------------------------------------------------------------

    program_counter u_program_counter (
        .clk           (clk),
        .reset         (reset),
        .branch_target (pc_jump_target),
        .pc_sel        (pc_sel),
        .pc            (pc_out)
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
        .write_data (reg_write_data),
        .reg_write  (reg_write),
        .rs1_data   (rs1_data_out),
        .rs2_data   (rs2_data_out)
    );

    branch_unit u_branch_unit (
        .rs1_data     (rs1_data_out),
        .rs2_data     (rs2_data_out),
        .funct3       (funct3),
        .branch_taken (branch_taken_wire)
    );
    
    alu u_alu (
        .a           (alu_a),
        .b           (alu_b),
        .alu_control (alu_control),
        .result      (alu_result_wire),
        .zero        (alu_zero_wire)
    );
    
    load_store_unit u_load_store_unit (
        .funct3        (funct3),
        .addr          (alu_result_wire),
        .write_data    (rs2_data_out),
        .mem_read      (mem_read),
        .mem_write     (mem_write),
        .mem_data_in   (data_mem_rdata),
        .mem_data_out  (lsu_mem_data_out),
        .mem_byte_en   (lsu_mem_byte_en),
        .read_data_out (lsu_read_data_out)
    );

    //----------------------------------------------------------------
    // Combinational Logic: Control and Datapath
    //----------------------------------------------------------------
    always @(*) begin
        // Default assignments to prevent latches
        reg_write       = 1'b0;
        mem_read        = 1'b0;
        mem_write       = 1'b0;
        pc_sel          = 2'b00; // Default: PC+4
        alu_src_a_sel   = 1'b0;  // Default: rs1_data
        alu_src_b_sel   = 1'b0;  // Default: rs2_data
        wb_sel          = 2'b00; // Default: ALU result
        alu_control     = ALU_ADD;
        
        // --- Control Logic based on instruction opcode ---
        case (opcode)
            OPCODE_LUI: begin
                reg_write     = 1'b1;
                alu_src_b_sel = 1'b1;
                alu_control   = ALU_COPY_B;
                wb_sel        = 2'b00;
            end
            OPCODE_AUIPC: begin
                reg_write     = 1'b1;
                alu_src_a_sel = 1'b1;
                alu_src_b_sel = 1'b1;
                alu_control   = ALU_ADD;
                wb_sel        = 2'b00;
            end
            OPCODE_JAL: begin
                reg_write = 1'b1;
                wb_sel    = 2'b10;
                pc_sel    = 2'b01;
            end
            OPCODE_JALR: begin
                reg_write = 1'b1;
                wb_sel    = 2'b10;
                pc_sel    = 2'b10;
            end
            OPCODE_BRANCH: begin
                if (branch_taken_wire) begin
                    pc_sel = 2'b01;
                end
            end
            OPCODE_LOAD: begin
                reg_write     = 1'b1;
                mem_read      = 1'b1;
                alu_src_b_sel = 1'b1;
                alu_control   = ALU_ADD;
                wb_sel        = 2'b01;
            end
            OPCODE_STORE: begin
                mem_write     = 1'b1;
                alu_src_b_sel = 1'b1;
                alu_control   = ALU_ADD;
            end
            OPCODE_R_TYPE: begin
                reg_write = 1'b1;
                wb_sel    = 2'b00;
                case (funct3)
                    FUNCT3_ADDI_ADD_SUB: alu_control = (funct7 == FUNCT7_SUB_SRA) ? ALU_SUB : ALU_ADD;
                    FUNCT3_SLLI_SLL:     alu_control = ALU_SLL;
                    FUNCT3_SLTI_SLT:     alu_control = ALU_SLT;
                    FUNCT3_SLTIU_SLTU:   alu_control = ALU_SLTU;
                    FUNCT3_XORI_XOR:     alu_control = ALU_XOR;
                    FUNCT3_SRLI_SRL_SRA: alu_control = (funct7 == FUNCT7_SUB_SRA) ? ALU_SRA : ALU_SRL;
                    FUNCT3_ORI_OR:       alu_control = ALU_OR;
                    FUNCT3_ANDI_AND:     alu_control = ALU_AND;
                    default:             alu_control = ALU_ADD;
                endcase
            end
            OPCODE_I_TYPE: begin
                reg_write     = 1'b1;
                alu_src_b_sel = 1'b1;
                wb_sel        = 2'b00;
                case (funct3)
                    FUNCT3_ADDI_ADD_SUB: alu_control = ALU_ADD;
                    FUNCT3_SLLI_SLL:     alu_control = ALU_SLL;
                    FUNCT3_SLTI_SLT:     alu_control = ALU_SLT;
                    FUNCT3_SLTIU_SLTU:   alu_control = ALU_SLTU;
                    FUNCT3_XORI_XOR:     alu_control = ALU_XOR;
                    FUNCT3_SRLI_SRL_SRA: alu_control = (funct7 == FUNCT7_SUB_SRA) ? ALU_SRA : ALU_SRL;
                    FUNCT3_ORI_OR:       alu_control = ALU_OR;
                    FUNCT3_ANDI_AND:     alu_control = ALU_AND;
                    default:             alu_control = ALU_ADD;
                endcase
            end
            default: ; // Maintain defaults for invalid opcodes
        endcase

        // --- Datapath Muxing and Calculations ---

        // ALU Source A Mux
        alu_a = (alu_src_a_sel == 1'b1) ? pc_out : rs1_data_out;

        // ALU Source B Mux
        alu_b = (alu_src_b_sel == 1'b1) ? imm : rs2_data_out;
        
        // PC Jump Target Calculation
        begin
            reg [31:0] branch_target_calc;
            reg [31:0] jalr_target_calc;
            branch_target_calc = pc_out + imm;
            jalr_target_calc   = (rs1_data_out + imm) & ~32'h1;
            
            pc_jump_target = (pc_sel == 2'b10) ? jalr_target_calc : branch_target_calc;
        end
        
        // Register File Write-Back Mux
        begin
            reg [31:0] pc_plus_4;
            pc_plus_4 = pc_out + 32'd4;
            
            case (wb_sel)
                2'b00:  reg_write_data = alu_result_wire;   // ALU result
                2'b01:  reg_write_data = lsu_read_data_out; // Data from memory
                2'b10:  reg_write_data = pc_plus_4;         // PC+4 for JAL/JALR
                default: reg_write_data = 32'hdeadbeef;     // Should not occur
            endcase
        end
    end

    //----------------------------------------------------------------
    // Top-Level Output Assignments
    //----------------------------------------------------------------
    assign instr_mem_addr = pc_out;
    assign data_mem_addr  = alu_result_wire;
    assign data_mem_wdata = lsu_mem_data_out;
    assign data_mem_we    = mem_write;
    assign data_mem_byte_en = lsu_mem_byte_en;

endmodule