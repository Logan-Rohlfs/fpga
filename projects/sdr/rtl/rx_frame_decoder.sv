// Configurable provisional packet decoder. Defaults are a TEST profile, not a
// claim about RF4463 on-air settings. Sync is sent MSB first; LSB_FIRST affects
// payload bytes only. Whitening is reset after sync and precedes byte assembly.
// TYPE_FILTER=1 is a one-entry type-implied length (the APEX air format has no
// length field): only frames whose type byte equals FRAME_TYPE are assembled,
// and FRAME_BYTES is that type's length. Any other type byte returns to sync
// hunt immediately; it counts as a sync hit but not as a good or bad frame.
module rx_frame_decoder #(
    parameter integer FRAME_BYTES = 19,
    parameter [31:0] SYNC_WORD = 32'hd391d391,
    parameter integer SYNC_BITS = 32,
    parameter integer LSB_FIRST = 0,
    parameter integer INVERT_BITS = 0,
    parameter integer WHITEN_ENABLE = 0,
    parameter [8:0] WHITEN_SEED = 9'h1ff,
    parameter [8:0] WHITEN_POLY = 9'h021,
    parameter integer TYPE_OFFSET = 0,
    parameter integer SEQ_OFFSET = 1,
    parameter integer SEQ_BYTES = 1,
    parameter integer SEQ_LITTLE_ENDIAN = 1,
    parameter [15:0] CRC_POLY = 16'h1021,
    parameter [15:0] CRC_INIT = 16'hffff,
    parameter [15:0] CRC_XOROUT = 16'h0000,
    parameter integer CRC_TRAILER_LITTLE_ENDIAN = 0,
    parameter integer BIT_TIMEOUT_CYCLES = 1000000,
    parameter integer TYPE_FILTER = 0,
    parameter [7:0] FRAME_TYPE = 8'h00
)(
    input wire clk, input wire rst,
    input wire bit_valid, input wire bit_in,
    output reg frame_valid, input wire frame_ready,
    output reg frame_complete, // one-cycle notification when a new output is stored
    output reg [FRAME_BYTES*8-1:0] frame_data,
    output wire [7:0] frame_len,
    output reg [7:0] frame_type,
    output reg [15:0] frame_seq,
    output reg frame_crc_ok,
    output reg [31:0] sync_count, good_count, bad_count,
    output reg [31:0] dropped_count, timeout_count,
    output reg locked
);
    localparam integer TW = BIT_TIMEOUT_CYCLES > 1 ? $clog2(BIT_TIMEOUT_CYCLES) : 1;
    localparam [31:0] SYNC_MASK = 32'hffffffff >> (32-SYNC_BITS);
    reg [31:0] sync_shift;
    reg [5:0] hunt_bits;
    reg [TW-1:0] idle_cycles;
    reg [7:0] byte_index;
    reg [2:0] bit_index;
    reg [7:0] byte_shift;
    reg [FRAME_BYTES*8-1:0] working_frame;
    reg [15:0] crc;
    reg [7:0] trailer_first;
    reg [8:0] whitening;
    wire normalized_bit = bit_in ^ (INVERT_BITS != 0);
    wire decoded_bit = normalized_bit ^ ((WHITEN_ENABLE != 0) && whitening[0]);
    wire [31:0] next_sync = {sync_shift[30:0], normalized_bit};
    wire [7:0] next_byte = LSB_FIRST ? {decoded_bit, byte_shift[7:1]} : {byte_shift[6:0], decoded_bit};
    wire [15:0] received_crc = CRC_TRAILER_LITTLE_ENDIAN ? {next_byte, trailer_first} : {trailer_first, next_byte};
    wire crc_pass = received_crc == (crc ^ CRC_XOROUT);

    function [15:0] crc_byte;
        input [15:0] old_crc;
        input [7:0] data;
        reg [15:0] c;
        integer k;
        begin
            c = old_crc ^ {data,8'h00};
            for (k=0;k<8;k=k+1)
                c = c[15] ? (c << 1) ^ CRC_POLY : c << 1;
            crc_byte = c;
        end
    endfunction

    // Parameter guard intentionally simulation-only: no hidden clamping.
    // synthesis translate_off
    initial begin
        if (FRAME_BYTES < 3 || FRAME_BYTES > 255 || SYNC_BITS < 1 || SYNC_BITS > 32 ||
            TYPE_OFFSET < 0 || TYPE_OFFSET >= FRAME_BYTES-2 ||
            SEQ_OFFSET < 0 || SEQ_OFFSET+SEQ_BYTES > FRAME_BYTES-2 ||
            (SEQ_BYTES != 1 && SEQ_BYTES != 2) || BIT_TIMEOUT_CYCLES < 1)
            $fatal(1,"invalid rx_frame_decoder profile");
    end
    // synthesis translate_on

    always @(posedge clk) begin
        if (rst) begin
            frame_valid <= 0; frame_complete <= 0; frame_data <= 0; frame_type <= 0;
            frame_seq <= 0; frame_crc_ok <= 0;
            sync_count <= 0; good_count <= 0; bad_count <= 0;
            dropped_count <= 0; timeout_count <= 0;
            locked <= 0; sync_shift <= 0; hunt_bits <= 0;
            idle_cycles <= 0; byte_index <= 0; bit_index <= 0;
            byte_shift <= 0; working_frame <= 0; crc <= CRC_INIT;
            trailer_first <= 0; whitening <= WHITEN_SEED;
        end else begin
            frame_complete <= 0;
            if (frame_valid && frame_ready) frame_valid <= 0;
            if (!locked) begin
                idle_cycles <= 0;
                if (bit_valid) begin
                    sync_shift <= next_sync;
                    if (hunt_bits < SYNC_BITS) hunt_bits <= hunt_bits + 1'b1;
                    if (hunt_bits >= SYNC_BITS-1 && (next_sync & SYNC_MASK) == (SYNC_WORD & SYNC_MASK)) begin
                        locked <= 1; sync_count <= sync_count + 1'b1;
                        byte_index <= 0; bit_index <= 0; byte_shift <= 0;
                        working_frame <= 0; crc <= CRC_INIT;
                        whitening <= WHITEN_SEED;
                    end
                end
            end else if (bit_valid) begin
                idle_cycles <= 0;
                if (WHITEN_ENABLE != 0)
                    whitening <= (whitening >> 1) ^ (whitening[0] ? WHITEN_POLY : 9'd0);
                byte_shift <= next_byte;
                bit_index <= bit_index + 1'b1;
                if (bit_index == 7) begin
                    working_frame[8*byte_index +: 8] <= next_byte;
                    byte_index <= byte_index + 1'b1;
                    if (byte_index < FRAME_BYTES-2) crc <= crc_byte(crc,next_byte);
                    if (byte_index == FRAME_BYTES-2) trailer_first <= next_byte;
                    if (TYPE_FILTER != 0 && byte_index == TYPE_OFFSET && next_byte != FRAME_TYPE) begin
                        locked <= 0; hunt_bits <= 0; sync_shift <= 0;
                    end
                    if (byte_index == FRAME_BYTES-1) begin
                        locked <= 0; hunt_bits <= 0; sync_shift <= 0;
                        if (crc_pass) good_count <= good_count + 1'b1;
                        else bad_count <= bad_count + 1'b1;
                        if (!frame_valid || frame_ready) begin
                            frame_valid <= 1; frame_complete <= 1;
                            frame_data <= {next_byte, working_frame[FRAME_BYTES*8-9:0]};
                            frame_type <= working_frame[8*TYPE_OFFSET +: 8];
                            if (SEQ_BYTES == 1)
                                frame_seq <= {8'd0,working_frame[8*SEQ_OFFSET +: 8]};
                            else if (SEQ_LITTLE_ENDIAN)
                                frame_seq <= working_frame[8*SEQ_OFFSET +: 16];
                            else
                                frame_seq <= {working_frame[8*SEQ_OFFSET +: 8],working_frame[8*(SEQ_OFFSET+1) +: 8]};
                            frame_crc_ok <= crc_pass;
                        end else dropped_count <= dropped_count + 1'b1;
                    end
                end
            end else if (idle_cycles == BIT_TIMEOUT_CYCLES-1) begin
                locked <= 0; hunt_bits <= 0; sync_shift <= 0;
                idle_cycles <= 0; timeout_count <= timeout_count + 1'b1;
            end else idle_cycles <= idle_cycles + 1'b1;
        end
    end
    assign frame_len = FRAME_BYTES;
endmodule
