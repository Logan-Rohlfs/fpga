`timescale 1ns/1ps
// Checks the byte-serial CRC against the standard check value and an APEX frame.
module crc16_ccitt_tb;
    reg [15:0] crc;
    reg [7:0] data;
    wire [15:0] next;
    integer i;
    reg [8*9-1:0] check = "123456789";
    reg [8*17-1:0] apex = {8'h01, 8'h07, "APEX RADIO TEST"};

    crc16_ccitt dut (.crc(crc), .data(data), .next(next));

    task automatic run(input integer n, input [8*17-1:0] bytes_msb_first, input [15:0] expected, input [8*16-1:0] name);
        begin
            crc = 16'hffff;
            for (i = n - 1; i >= 0; i = i - 1) begin
                data = bytes_msb_first[8*i +: 8];
                #1 crc = next;
            end
            if (crc !== expected) $fatal(1, "%0s: expected %04x, got %04x", name, expected, crc);
        end
    endtask

    initial begin
        run(9, {64'h0, check}, 16'h29b1, "check value");
        run(17, apex, 16'hbb3c, "APEX TEST frame");
        $display("PASS: CRC-16-CCITT check value and APEX frame");
        $finish;
    end
endmodule
