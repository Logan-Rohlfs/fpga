// Sample-to-frame receiver; only the caller determines sample provenance.
// Reset on profile/NCO changes. A synthetic sample makes provenance sticky until
// reset so a packet spanning a source change cannot be presented as measured.
module rx_pipeline #(
    parameter integer DECIMATION=10,
    parameter integer SAMPLES_PER_SYMBOL=10,
    parameter integer MIN_MAGNITUDE=64,
    parameter integer IQ_RATE_HZ=100000,
    parameter integer FRAME_BYTES=19,
    parameter [31:0] SYNC_WORD=32'hd391d391,
    parameter integer SYNC_BITS=32,
    parameter integer LSB_FIRST=0,
    parameter integer INVERT_BITS=0,
    parameter integer WHITEN_ENABLE=0,
    parameter [8:0] WHITEN_SEED=9'h1ff,
    parameter [8:0] WHITEN_POLY=9'h021,
    parameter integer TYPE_OFFSET=0,
    parameter integer SEQ_OFFSET=1,
    parameter integer SEQ_BYTES=1,
    parameter integer SEQ_LITTLE_ENDIAN=1,
    parameter [15:0] CRC_POLY=16'h1021,
    parameter [15:0] CRC_INIT=16'hffff,
    parameter [15:0] CRC_XOROUT=16'h0000,
    parameter integer CRC_TRAILER_LITTLE_ENDIAN=0,
    parameter integer BIT_TIMEOUT_CYCLES=1000000
)(
    input wire clk, rst,
    input wire [31:0] nco_step,
    input wire sample_valid,
    input wire signed [11:0] sample_data,
    input wire sample_synthetic,
    input wire [31:0] t_us,
    output reg synthetic,
    output wire iq_valid,
    output wire signed [15:0] iq_i,iq_q,
    output wire bit_valid,bit_data,
    output wire signed [31:0] discriminator,frequency_offset_hz,
    output wire [15:0] magnitude,
    output wire [7:0] quality,
    output wire signal_present,
    output reg frame_valid, input wire frame_ready,
    output reg [31:0] frame_t_us,
    output reg signed [31:0] frame_frequency_offset_hz,
    output reg [7:0] frame_quality,
    output reg [15:0] frame_magnitude,
    output reg [FRAME_BYTES*8-1:0] frame_data,
    output wire [7:0] frame_len,
    output reg [7:0] frame_type,
    output reg [15:0] frame_seq,
    output reg frame_crc_ok,
    output wire [31:0] sync_count,good_count,bad_count,dropped_count,timeout_count,
    output wire locked
);
    wire decoder_valid,decoder_complete;
    reg [31:0] pending_t_us;
    reg signed [31:0] pending_frequency;
    reg [7:0] pending_quality;
    reg [15:0] pending_magnitude;
    always @(posedge clk) begin
        if(rst) begin
            pending_t_us<=0; pending_frequency<=0; pending_quality<=0; pending_magnitude<=0;
        end else if(decoder_complete) begin
            pending_t_us<=t_us; pending_frequency<=frequency_offset_hz;
            pending_quality<=quality; pending_magnitude<=magnitude;
        end
    end
    wire decoder_ready=!frame_valid || frame_ready;
    wire [FRAME_BYTES*8-1:0] decoder_data;
    wire [7:0] decoder_type;
    wire [15:0] decoder_seq;
    wire decoder_crc_ok;
    always @(posedge clk) begin
        if(rst) begin
            frame_valid<=0; frame_data<=0; frame_type<=0; frame_seq<=0;
            frame_crc_ok<=0; frame_t_us<=0; frame_frequency_offset_hz<=0; frame_quality<=0; frame_magnitude<=0;
        end else begin
            if(frame_valid && frame_ready) frame_valid<=0;
            if(decoder_valid && decoder_ready) begin
                frame_valid<=1; frame_data<=decoder_data; frame_type<=decoder_type;
                frame_seq<=decoder_seq; frame_crc_ok<=decoder_crc_ok;
                frame_t_us<=decoder_complete ? t_us : pending_t_us;
                frame_quality<=decoder_complete ? quality : pending_quality;
                frame_magnitude<=decoder_complete ? magnitude : pending_magnitude;
                frame_frequency_offset_hz<=decoder_complete ? frequency_offset_hz : pending_frequency;
            end
        end
    end
    always @(posedge clk) begin
        if(rst) synthetic<=0;
        else if(sample_valid && sample_synthetic) synthetic<=1;
    end
    rx_channel #(.DECIMATION(DECIMATION),.SAMPLES_PER_SYMBOL(SAMPLES_PER_SYMBOL),
        .MIN_MAGNITUDE(MIN_MAGNITUDE),.IQ_RATE_HZ(IQ_RATE_HZ)) channel(
        .clk(clk),.rst(rst),.nco_step(nco_step),.sample_valid(sample_valid),.sample_data(sample_data),
        .iq_valid(iq_valid),.iq_i(iq_i),.iq_q(iq_q),.bit_valid(bit_valid),.bit_data(bit_data),
        .discriminator(discriminator),.frequency_offset_hz(frequency_offset_hz),.magnitude(magnitude),.quality(quality),.signal_present(signal_present));
    rx_frame_decoder #(.FRAME_BYTES(FRAME_BYTES),.SYNC_WORD(SYNC_WORD),.SYNC_BITS(SYNC_BITS),
        .LSB_FIRST(LSB_FIRST),.INVERT_BITS(INVERT_BITS),.WHITEN_ENABLE(WHITEN_ENABLE),
        .WHITEN_SEED(WHITEN_SEED),.WHITEN_POLY(WHITEN_POLY),.TYPE_OFFSET(TYPE_OFFSET),
        .SEQ_OFFSET(SEQ_OFFSET),.SEQ_BYTES(SEQ_BYTES),.SEQ_LITTLE_ENDIAN(SEQ_LITTLE_ENDIAN),
        .CRC_POLY(CRC_POLY),.CRC_INIT(CRC_INIT),.CRC_XOROUT(CRC_XOROUT),
        .CRC_TRAILER_LITTLE_ENDIAN(CRC_TRAILER_LITTLE_ENDIAN),.BIT_TIMEOUT_CYCLES(BIT_TIMEOUT_CYCLES)) decoder(
        .clk(clk),.rst(rst),.bit_valid(bit_valid),.bit_in(bit_data),.frame_valid(decoder_valid),.frame_complete(decoder_complete),
        .frame_ready(decoder_ready),.frame_data(decoder_data),.frame_len(frame_len),.frame_type(decoder_type),
        .frame_seq(decoder_seq),.frame_crc_ok(decoder_crc_ok),.sync_count(sync_count),.good_count(good_count),
        .bad_count(bad_count),.dropped_count(dropped_count),.timeout_count(timeout_count),.locked(locked));
endmodule
