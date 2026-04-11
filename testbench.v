module testbench (
    input clk,
    input reset
);
    // --- Instruction Memory Interface ---
    wire [31:0] pc_wire;
    wire [31:0] instr_wire;

    // 16KB Instruction Memory (4096 words)
    reg [31:0] instr_memory [0:4095];
    string loadmem_path;

    // Fetch instruction (PC is byte-addressed, array is word-addressed)
    // Alias 0x8000XXXX to index [13:2] so test binaries map correctly
    wire [11:0] imem_word_addr = pc_wire[13:2];
    assign instr_wire = instr_memory[imem_word_addr];

    // --- Data Memory Interface ---
    wire [31:0] data_mem_addr_wire;
    wire [31:0] data_mem_wdata_wire;
    wire        data_mem_we_wire;
    wire [3:0]  data_mem_byte_en_wire;
    wire [31:0] data_mem_rdata_wire;

    // 16KB Data Memory (4096 words)
    reg [31:0] data_memory [0:4095];
    wire [11:0] dmem_word_addr;
    assign dmem_word_addr = data_mem_addr_wire[13:2];

    // Initialize both memories from the same hex file
    integer i;
    initial begin
        for (i = 0; i < 4096; i = i + 1) begin
            instr_memory[i] = 32'h00000000;
            data_memory[i] = 32'h00000000;
        end
        if ($value$plusargs("loadmem=%s", loadmem_path)) begin
            $display("[TB] Loading test image: %0s", loadmem_path);
            $readmemh(loadmem_path, instr_memory);
            $readmemh(loadmem_path, data_memory);
        end else begin
            $display("[TB] No +loadmem path supplied");
        end
    end

    // Combinational read
    assign data_mem_rdata_wire = data_memory[dmem_word_addr];

    // Synchronous write with byte enables
    always @(posedge clk) begin
        if (data_mem_we_wire) begin
            if (data_mem_byte_en_wire[0])
                data_memory[dmem_word_addr][7:0]   <= data_mem_wdata_wire[7:0];
            if (data_mem_byte_en_wire[1])
                data_memory[dmem_word_addr][15:8]  <= data_mem_wdata_wire[15:8];
            if (data_mem_byte_en_wire[2])
                data_memory[dmem_word_addr][23:16] <= data_mem_wdata_wire[23:16];
            if (data_mem_byte_en_wire[3])
                data_memory[dmem_word_addr][31:24] <= data_mem_wdata_wire[31:24];
        end
    end

    // --- Core Instantiation ---
    rv32i_core dut (
        .clk            (clk),
        .reset          (reset),
        .instr_mem_data (instr_wire),
        .instr_mem_addr (pc_wire),
        .data_mem_addr  (data_mem_addr_wire),
        .data_mem_wdata (data_mem_wdata_wire),
        .data_mem_we    (data_mem_we_wire),
        .data_mem_byte_en(data_mem_byte_en_wire),
        .data_mem_rdata (data_mem_rdata_wire)
    );

endmodule