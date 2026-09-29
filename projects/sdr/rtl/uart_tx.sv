`timescale 1ns/1ps
// Reusable 8N1 UART transmitter. One byte is accepted on valid && ready.
module uart_tx #(
    parameter integer CLK_HZ = 100_000_000,
    parameter integer BAUD_RATE = 115_200
) (
    input  wire       clk,
    input  wire       rst,
    input  wire [7:0] data,
    input  wire       valid,
    output wire       ready,
    output wire       tx
);
    localparam integer CLKS_PER_BIT = (CLK_HZ + BAUD_RATE / 2) / BAUD_RATE;
    localparam integer COUNT_WIDTH = (CLKS_PER_BIT <= 1) ? 1 : $clog2(CLKS_PER_BIT);

    reg [COUNT_WIDTH-1:0] baud_count = 0;
    reg [9:0] shift_reg = 10'h3ff;
    reg [3:0] bit_index = 0;
    reg active = 1'b0;

    assign ready = !active && !rst;
    assign tx = (active && !rst) ? shift_reg[0] : 1'b1;

    always @(posedge clk) begin
        if (rst) begin
            baud_count <= 0;
            shift_reg <= 10'h3ff;
            bit_index <= 0;
            active <= 1'b0;
        end else if (!active) begin
            if (valid) begin
                // LSB first: start(0), eight data bits, stop(1).
                shift_reg <= {1'b1, data, 1'b0};
                baud_count <= 0;
                bit_index <= 0;
                active <= 1'b1;
            end
        end else if (baud_count == CLKS_PER_BIT - 1) begin
            baud_count <= 0;
            shift_reg <= {1'b1, shift_reg[9:1]};
            if (bit_index == 9)
                active <= 1'b0;
            else
                bit_index <= bit_index + 1'b1;
        end else begin
            baud_count <= baud_count + 1'b1;
        end
    end
endmodule
