module load_store_unit (
    input  [2:0]  funct3,
    input  [31:0] addr,
    input  [31:0] write_data,
    input         mem_read,
    input         mem_write,
    input  [31:0] mem_data_in,
    output reg [31:0] mem_data_out,
    output reg [3:0]  mem_byte_en,
    output reg [31:0] read_data_out
);

    always @(*) begin
        // Default assignments to prevent latch inference
        mem_data_out  = 32'b0;
        mem_byte_en   = 4'b0;
        read_data_out = 32'b0;

        if (mem_write) begin
            // --- Store Logic ---
            case (funct3)
                // SB: Store Byte (funct3 = 3'b000)
                3'b000: begin
                    mem_byte_en  = 4'b0001 << addr[1:0];
                    mem_data_out = write_data << {addr[1:0], 3'b000};
                end
                // SH: Store Half-word (funct3 = 3'b001)
                3'b001: begin
                    mem_byte_en  = 4'b0011 << {addr[1], 1'b0};
                    mem_data_out = write_data << {addr[1], 4'b0000};
                end
                // SW: Store Word (funct3 = 3'b010)
                3'b010: begin
                    mem_byte_en  = 4'b1111;
                    mem_data_out = write_data;
                end
                default: begin
                    mem_byte_en  = 4'b0;
                    mem_data_out = 32'b0;
                end
            endcase
        end
        else if (mem_read) begin
            // --- Load Logic ---
            case (funct3)
                // LB: Load Byte, sign-extended (funct3 = 3'b000)
                3'b000: begin
                    reg [7:0] byte_data;
                    case (addr[1:0])
                        2'b00: byte_data = mem_data_in[7:0];
                        2'b01: byte_data = mem_data_in[15:8];
                        2'b10: byte_data = mem_data_in[23:16];
                        2'b11: byte_data = mem_data_in[31:24];
                    endcase
                    read_data_out = {{24{byte_data[7]}}, byte_data};
                end
                // LH: Load Half-word, sign-extended (funct3 = 3'b001)
                3'b001: begin
                    reg [15:0] half_data;
                    if (addr[1] == 1'b0) begin
                        half_data = mem_data_in[15:0];
                    end else begin
                        half_data = mem_data_in[31:16];
                    end
                    read_data_out = {{16{half_data[15]}}, half_data};
                end
                // LW: Load Word (funct3 = 3'b010)
                3'b010: begin
                    read_data_out = mem_data_in;
                end
                // LBU: Load Byte, zero-extended (funct3 = 3'b100)
                3'b100: begin
                    reg [7:0] byte_data;
                    case (addr[1:0])
                        2'b00: byte_data = mem_data_in[7:0];
                        2'b01: byte_data = mem_data_in[15:8];
                        2'b10: byte_data = mem_data_in[23:16];
                        2'b11: byte_data = mem_data_in[31:24];
                    endcase
                    read_data_out = {24'b0, byte_data};
                end
                // LHU: Load Half-word, zero-extended (funct3 = 3'b101)
                3'b101: begin
                    reg [15:0] half_data;
                    if (addr[1] == 1'b0) begin
                        half_data = mem_data_in[15:0];
                    end else begin
                        half_data = mem_data_in[31:16];
                    end
                    read_data_out = {16'b0, half_data};
                end
                default: begin
                    read_data_out = 32'b0;
                end
            endcase
        end
    end

endmodule