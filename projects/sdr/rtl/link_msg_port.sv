`timescale 1ns/1ps
// One link_tx producer port: holds a pending message and streams its payload.
//
// Pulse trigger when a new message is due. If the previous message is still
// pending, the new one is dropped (drop pulses); otherwise accept pulses and the
// parent must snapshot the message fields in that cycle. len is sampled on
// accept; 0 is allowed.
//
// The parent computes byte_in from idx, and may pipeline that logic internally
// by up to LATENCY-1 register stages. The port registers byte_in and asserts
// valid only LATENCY cycles after idx last changed, so the producer's logic is
// timing-isolated from link_tx. Throughput is one byte per LATENCY+1 cycles,
// far above the UART rate.
module link_msg_port #(
    parameter integer LATENCY = 3
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        trigger,
    input  wire [15:0] len,
    input  wire [7:0]  byte_in,
    input  wire        grant,
    input  wire        ready,
    output reg         req = 1'b0,
    output reg  [15:0] idx = 0,
    output reg  [7:0]  data = 0,
    output wire        valid,
    output wire        accept,
    output wire        drop
);
    reg [15:0] cur_len = 0;
    reg [3:0] settle = 0;
    wire fresh = (settle == LATENCY);

    assign accept = trigger && !req;
    assign drop = trigger && req;
    assign valid = grant && req && (cur_len != 0) && fresh;

    always @(posedge clk) begin
        data <= byte_in;
        if (rst) begin
            req <= 1'b0;
            idx <= 0;
            settle <= 0;
        end else if (accept) begin
            req <= 1'b1;
            idx <= 0;
            cur_len <= len;
            settle <= 0;
        end else if (grant && req && cur_len == 0) begin
            req <= 1'b0;
        end else if (valid && ready) begin
            idx <= idx + 1'b1;
            settle <= 0;
            if (idx == cur_len - 1) req <= 1'b0;
        end else if (!fresh) begin
            settle <= settle + 1'b1;
        end
    end
endmodule
