`timescale 1ns/1ps
// SDR board top: host link layer driven by synthetic stand-in producers.
//
// link_test_sources -> link_tx (priority framer, CRC) -> cobs_encoder -> uart_tx.
// Every message is flagged SYNTHETIC until real receiver stages replace the sources.
// LED0 toggles each time a STATUS message is sent (about once per second).
// btnC resets the design; a short power-on reset also runs after configuration.
module sdr_top #(
    parameter integer CLK_HZ = 100_000_000,
    parameter integer BAUD_RATE = 1_000_000,
    parameter integer TICK_CYCLES = CLK_HZ / 100,
    parameter integer STATUS_TICKS = 100,
    parameter [31:0]  BUILD_ID = 32'h0
) (
    input  wire clk,
    input  wire btnC,
    output wire uart_tx,
    output reg  led = 1'b0
);
    localparam integer N = 11;
    localparam [7:0] T_STATUS = 8'h01;

    reg [1:0] btn_sync = 2'b00;
    reg [3:0] por = 0;
    wire rst = (por != 4'hf) || btn_sync[1];

    always @(posedge clk) begin
        btn_sync <= {btn_sync[0], btnC};
        if (por != 4'hf) por <= por + 1'b1;
    end

    wire [N-1:0] req, grant, p_valid, p_ready;
    wire [8*N-1:0] p_type, p_flags, p_data;
    wire [16*N-1:0] p_len;
    wire [7:0] msg_data, sent_type, enc_data;
    wire msg_valid, msg_last, msg_ready, sent_pulse, enc_valid, enc_ready;

    link_test_sources #(
        .CLK_HZ(CLK_HZ), .TICK_CYCLES(TICK_CYCLES), .STATUS_TICKS(STATUS_TICKS), .BUILD_ID(BUILD_ID), .N(N)
    ) sources (
        .clk(clk), .rst(rst), .req(req), .p_type(p_type), .p_flags(p_flags), .p_len(p_len),
        .grant(grant), .p_data(p_data), .p_valid(p_valid), .p_ready(p_ready)
    );

    link_tx #(.N(N)) framer (
        .clk(clk), .rst(rst), .req(req), .p_type(p_type), .p_flags(p_flags), .p_len(p_len), .grant(grant),
        .p_data(p_data), .p_valid(p_valid), .p_ready(p_ready), .out_data(msg_data), .out_valid(msg_valid),
        .out_last(msg_last), .out_ready(msg_ready), .sent_type(sent_type), .sent_pulse(sent_pulse)
    );

    cobs_encoder #(.DEPTH(1024)) encoder (
        .clk(clk), .rst(rst), .in_data(msg_data), .in_valid(msg_valid), .in_last(msg_last), .in_ready(msg_ready),
        .out_data(enc_data), .out_valid(enc_valid), .out_ready(enc_ready)
    );

    uart_tx #(.CLK_HZ(CLK_HZ), .BAUD_RATE(BAUD_RATE)) transmitter (
        .clk(clk), .rst(rst), .data(enc_data), .valid(enc_valid), .ready(enc_ready), .tx(uart_tx)
    );

    always @(posedge clk) begin
        if (rst) led <= 1'b0;
        else if (sent_pulse && sent_type == T_STATUS) led <= ~led;
    end
endmodule
