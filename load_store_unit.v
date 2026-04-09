module load_store_unit (
    input  [2:0]  funct3,
    input  [31:0] addr,
    input  [31:0] write_data,
    input         mem_read,
    input         mem_write,
    // NOTE: The following ports are required for a functional LSU
    // and have been added to the provided interface.
    input  [31:0] mem_data_in,
    output reg [31:0] mem_data_out,
    output reg [3:0]  mem_byte_en,
    
    output reg [31:0] read_data_out
);

    // RISC-V funct3 assignments for load/store instructions
    localparam F3_B  = 3'b000; // SB, LB
    localparam F3_H  = 3'b001; // SH, LH
    localparam F3_W  = 3'b010; // SW, LW
    localparam F3_BU = 3'b100; // LBU
    localparam F3_HU = 3'b101; // LHU

    always_comb begin
        // Default assignments to prevent latches
        read_data_out = 32'b0;
        mem_data_out  = 32'b0;
        mem_byte_en   = 4'b0;

        if (mem_read) begin
            // Load logic
            case (funct3)
                F3_B: begin // Load Byte (LB)
                    case (addr[1:0])
                        2'b00: read_data_out = {{24{mem_data_in[7]}},  mem_data_in[7:0]};
                        2'b01: read_data_out = {{24{mem_data_in[15]}}, mem_data_in[15:8]};
                        2'b10: read_data_out = {{24{mem_data_in[23]}}, mem_data_in[23:16]};
                        2'b11: read_data_out = {{24{mem_data_in[31]}}, mem_data_in[31:24]};
                    endcase
                end
                F3_H: begin // Load Half-word (LH)
                    if (addr[1] == 1'b0) begin // Aligned address: addr[1:0] is 00
                        read_data_out = {{16{mem_data_in[15]}}, mem_data_in[15:0]};
                    end else begin // Aligned address: addr[1:0] is 10
                        read_data_out = {{16{mem_data_in[31]}}, mem_data_in[31:16]};
                    end
                end
                F3_W: begin // Load Word (LW)
                    read_data_out = mem_data_in;
                end
                F3_BU: begin // Load Byte Unsigned (LBU)
                     case (addr[1:0])
                        2'b00: read_data_out = {24'b0, mem_data_in[7:0]};
                        2'b01: read_data_out = {24'b0, mem_data_in[15:8]};
                        2'b10: read_data_out = {24'b0, mem_data_in[23:16]};
                        2'b11: read_data_out = {24'b0, mem_data_in[31:24]};
                    endcase
                end
                F3_HU: begin // Load Half-word Unsigned (LHU)
                    if (addr[1] == 1'b0) begin // Aligned address: addr[1:0] is 00
                        read_data_out = {16'b0, mem_data_in[15:0]};
                    end else begin // Aligned address: addr[1:0] is 10
                        read_data_out = {16'b0, mem_data_in[31:16]};
                    end
                end
                default: read_data_out = 32'b0;
            endcase
        end else if (mem_write) begin
            // Store logic
            // Shift write data to correct byte lane based on address offset
            case (addr[1:0])
                2'b00: mem_data_out = write_data;
                2'b01: mem_data_out = write_data << 8;
                2'b10: mem_data_out = write_data << 16;
                2'b11: mem_data_out = write_data << 24;
            endcase
            
            // Generate byte enables based on funct3 and address offset
            case (funct3)
                F3_B: begin // Store Byte (SB)
                    mem_byte_en = 1'b1 << addr[1:0];
                end
                F3_H: begin // Store Half-word (SH)
                    mem_byte_en = 2'b11 << addr[1:0];
                end
                F3_W: begin // Store Word (SW)
                    mem_byte_en = 4'b1111;
                end
                default: mem_byte_en = 4'b0;
            endcase
        end
    end

endmodule