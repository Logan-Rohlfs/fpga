`timescale 1ns/1ps
// COBS-encodes one message at a time, then streams it followed by a 0x00 delimiter.
//
// Input bytes are accepted on in_valid && in_ready; in_last marks the final byte.
// Encoding is single pass: each block's code byte is backpatched into the buffer
// when a zero arrives or 254 nonzero bytes accumulate (code 0xFF). in_ready is low
// for that extra cycle and while the encoded message is being sent. The algorithm
// matches tools/sdr_cli/protocol.py:cobs_encode byte for byte.
//
// DEPTH must hold the longest message plus one code byte per 254 bytes plus one.
module cobs_encoder #(
    parameter integer DEPTH = 1024
) (
    input  wire       clk,
    input  wire       rst,
    input  wire [7:0] in_data,
    input  wire       in_valid,
    input  wire       in_last,
    output wire       in_ready,
    output wire [7:0] out_data,
    output wire       out_valid,
    input  wire       out_ready
);
    localparam integer AW = $clog2(DEPTH);
    localparam [1:0] FILL = 0, CLOSE = 1, FINISH = 2, SEND = 3;

    reg [7:0] mem [0:DEPTH-1];
    reg [1:0] state = FILL;
    reg [AW-1:0] wp = 1;
    reg [AW-1:0] code_pos = 0;
    reg [AW-1:0] rp = 0;
    reg [7:0] code = 1;
    reg last_pending = 0;

    // A write port shared by data bytes and backpatched code bytes.
    reg we;
    reg [AW-1:0] waddr;
    reg [7:0] wdata;

    wire accept = in_valid && in_ready;
    assign in_ready = (state == FILL) && !rst;
    assign out_valid = (state == SEND) && !rst;
    assign out_data = (rp == wp) ? 8'h00 : mem[rp];

    always @* begin
        we = 1'b0;
        waddr = wp;
        wdata = in_data;
        case (state)
            FILL: if (accept) begin
                we = 1'b1;
                if (in_data == 8'h00) begin
                    waddr = code_pos;
                    wdata = code;
                end
            end
            CLOSE: begin
                we = 1'b1;
                waddr = code_pos;
                wdata = 8'hff;
            end
            FINISH: begin
                we = 1'b1;
                waddr = code_pos;
                wdata = code;
            end
            default: ;
        endcase
    end

    always @(posedge clk) begin
        if (we)
            mem[waddr] <= wdata;
    end

    always @(posedge clk) begin
        if (rst) begin
            state <= FILL;
            wp <= 1;
            code_pos <= 0;
            code <= 1;
            rp <= 0;
            last_pending <= 1'b0;
        end else begin
            case (state)
                FILL: if (accept) begin
                    last_pending <= in_last;
                    if (in_data == 8'h00) begin
                        code_pos <= wp;
                        wp <= wp + 1'b1;
                        code <= 1;
                        if (in_last) state <= FINISH;
                    end else begin
                        wp <= wp + 1'b1;
                        code <= code + 1'b1;
                        if (code == 8'hfe) state <= CLOSE;
                        else if (in_last) state <= FINISH;
                    end
                end
                CLOSE: begin
                    code_pos <= wp;
                    wp <= wp + 1'b1;
                    code <= 1;
                    state <= last_pending ? FINISH : FILL;
                end
                FINISH: begin
                    rp <= 0;
                    state <= SEND;
                end
                SEND: if (out_ready) begin
                    if (rp == wp) begin
                        wp <= 1;
                        code_pos <= 0;
                        code <= 1;
                        state <= FILL;
                    end else begin
                        rp <= rp + 1'b1;
                    end
                end
            endcase
        end
    end
endmodule
