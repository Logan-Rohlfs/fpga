// Basys 3 clock: 100 MHz. LED0 toggles every 50,000,000 cycles (0.5 s).
module blink #(
    parameter integer HALF_PERIOD = 50_000_000
) (
    input  wire clk,
    output reg  led = 1'b0
);
    localparam integer COUNT_WIDTH = $clog2(HALF_PERIOD);
    reg [COUNT_WIDTH-1:0] count = 0;

    always @(posedge clk) begin
        if (count == HALF_PERIOD - 1) begin
            count <= 0;
            led <= ~led;
        end else begin
            count <= count + 1'b1;
        end
    end
endmodule

