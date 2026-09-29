`timescale 1ns/1ps
// One-byte CRC-16-CCITT update: poly 0x1021, MSB first, no reflection.
// Start from 16'hffff; the check value for "123456789" is 16'h29b1.
module crc16_ccitt (
    input  wire [15:0] crc,
    input  wire [7:0]  data,
    output wire [15:0] next
);
    function automatic [15:0] step(input [15:0] c, input [7:0] d);
        integer i;
        reg [15:0] x;
        begin
            x = c ^ {d, 8'h00};
            for (i = 0; i < 8; i = i + 1)
                x = x[15] ? ((x << 1) ^ 16'h1021) : (x << 1);
            step = x;
        end
    endfunction

    assign next = step(crc, data);
endmodule
