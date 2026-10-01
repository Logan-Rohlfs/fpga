`timescale 1ns/1ps
// 8N1 receiver. Two flip-flops synchronize the asynchronous pin; samples occur
// at bit centers. valid/error pulse for one clock. At least four clocks/bit.
module uart_rx #(
    parameter integer CLK_HZ = 100_000_000,
    parameter integer BAUD_RATE = 1_000_000
)(
    input wire clk, input wire rst, input wire rx,
    output reg [7:0] data, output reg valid, output reg error
);
    localparam integer CLKS_PER_BIT=(CLK_HZ+BAUD_RATE/2)/BAUD_RATE;
    localparam integer CW=CLKS_PER_BIT>1 ? $clog2(CLKS_PER_BIT) : 1;
    localparam IDLE=0,START=1,DATA=2,STOP=3;
    (* ASYNC_REG = "TRUE" *) reg rx_meta=1,rx_sync=1;
    reg [1:0] state;
    reg [CW-1:0] count;
    reg [2:0] index;
    reg [7:0] shift;
    // synthesis translate_off
    initial if(CLKS_PER_BIT<4) $fatal(1,"uart_rx requires at least four clocks per bit");
    // synthesis translate_on
    always @(posedge clk) begin
        if(rst) begin
            rx_meta<=1;rx_sync<=1;state<=IDLE;count<=0;index<=0;
            shift<=0;data<=0;valid<=0;error<=0;
        end else begin
            rx_meta<=rx;rx_sync<=rx_meta;valid<=0;error<=0;
            case(state)
                IDLE: if(!rx_sync) begin state<=START;count<=0;end
                START: if(count==CLKS_PER_BIT/2-1) begin
                    count<=0;
                    if(!rx_sync) begin state<=DATA;index<=0;end
                    else state<=IDLE;
                end else count<=count+1'b1;
                DATA: if(count==CLKS_PER_BIT-1) begin
                    count<=0;shift[index]<=rx_sync;
                    if(index==7) state<=STOP;
                    else index<=index+1'b1;
                end else count<=count+1'b1;
                STOP: if(count==CLKS_PER_BIT-1) begin
                    count<=0;state<=IDLE;
                    if(rx_sync) begin data<=shift;valid<=1;end
                    else error<=1;
                end else count<=count+1'b1;
                default: state<=IDLE;
            endcase
        end
    end
endmodule
