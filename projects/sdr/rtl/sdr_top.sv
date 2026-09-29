`timescale 1ns/1ps
// Temporary hardware diagnostic for the host-facing SDR output path.
module sdr_top #(
    parameter integer CLK_HZ = 100_000_000,
    parameter integer BAUD_RATE = 115_200,
    parameter integer HEARTBEAT_CYCLES = 100_000_000
) (
    input  wire clk,
    input  wire btnC,
    output wire uart_tx,
    output reg  led = 1'b0
);
    localparam [1:0] SEND = 0, DRAIN = 1, PAUSE = 2;
    localparam integer PAUSE_WIDTH = (HEARTBEAT_CYCLES <= 1) ? 1 : $clog2(HEARTBEAT_CYCLES);
    localparam [3:0] LAST_BYTE = 10;

    reg [1:0] state = SEND;
    reg [3:0] index = 0;
    reg [PAUSE_WIDTH-1:0] pause_count = 0;
    wire ready;
    wire valid = (state == SEND);
    wire [7:0] data;

    function [7:0] message_byte(input [3:0] n);
        case (n)
            0: message_byte = "S";
            1: message_byte = "D";
            2: message_byte = "R";
            3: message_byte = " ";
            4: message_byte = "R";
            5: message_byte = "E";
            6: message_byte = "A";
            7: message_byte = "D";
            8: message_byte = "Y";
            9: message_byte = 8'h0d;
            10: message_byte = 8'h0a;
            default: message_byte = 8'h00;
        endcase
    endfunction

    assign data = message_byte(index);

    uart_tx #(.CLK_HZ(CLK_HZ), .BAUD_RATE(BAUD_RATE)) transmitter (
        .clk(clk), .rst(btnC), .data(data), .valid(valid), .ready(ready), .tx(uart_tx)
    );

    always @(posedge clk) begin
        if (btnC) begin
            state <= SEND;
            index <= 0;
            pause_count <= 0;
            led <= 1'b0;
        end else begin
            case (state)
                SEND: if (ready) begin
                    if (index == LAST_BYTE) begin
                        index <= 0;
                        state <= DRAIN;
                    end else begin
                        index <= index + 1'b1;
                    end
                end
                DRAIN: if (ready) begin
                    led <= ~led;
                    pause_count <= 0;
                    state <= PAUSE;
                end
                PAUSE: if (pause_count == HEARTBEAT_CYCLES - 1) begin
                    state <= SEND;
                end else begin
                    pause_count <= pause_count + 1'b1;
                end
                default: state <= SEND;
            endcase
        end
    end
endmodule
