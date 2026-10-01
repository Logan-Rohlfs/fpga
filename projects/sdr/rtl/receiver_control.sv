// Development receiver control, matching tools/sdr_cli/receiver_control.py.
// SR/version1/seq/carrierLE32/ncoLE32/enable/CRC-CCITT LE16 (15 bytes).
// Commands become visible only after validation; application and acknowledgment
// belong to the caller. A stalled command is immutable; further commands drop.
module receiver_control #(
    parameter integer CLK_HZ=100_000_000,
    parameter integer BAUD_RATE=1_000_000,
    parameter integer INTERBYTE_TIMEOUT_CYCLES=CLK_HZ/100
)(
    input wire clk, input wire rst, input wire uart_rx,
    output reg command_valid, input wire command_ready,
    output reg [7:0] cmd_seq,
    output reg [31:0] carrier_ftw,nco_ftw,
    output reg enable,
    output reg [31:0] rejected_count,dropped_count
);
    wire [7:0] rx_data;
    wire rx_valid,rx_error;
    uart_rx #(.CLK_HZ(CLK_HZ),.BAUD_RATE(BAUD_RATE)) receiver(
        .clk(clk),.rst(rst),.rx(uart_rx),.data(rx_data),.valid(rx_valid),.error(rx_error));
    localparam integer TW=INTERBYTE_TIMEOUT_CYCLES>1 ? $clog2(INTERBYTE_TIMEOUT_CYCLES) : 1;
    reg [3:0] index;
    reg [TW-1:0] idle_count;
    reg [103:0] body;
    reg [15:0] crc;
    reg [7:0] crc_low;
    function [15:0] crc_byte;
        input [15:0] previous;
        input [7:0] value;
        reg [15:0] c;integer bit_number;
        begin
            c=previous^{value,8'd0};
            for(bit_number=0;bit_number<8;bit_number=bit_number+1)
                c=c[15] ? (c<<1)^16'h1021 : c<<1;
            crc_byte=c;
        end
    endfunction
    // synthesis translate_off
    initial if(INTERBYTE_TIMEOUT_CYCLES<1) $fatal(1,"invalid receiver_control timeout");
    // synthesis translate_on
    always @(posedge clk) begin
        if(rst) begin
            command_valid<=0;cmd_seq<=0;carrier_ftw<=0;nco_ftw<=0;enable<=0;
            rejected_count<=0;dropped_count<=0;index<=0;idle_count<=0;
            body<=0;crc<=16'hffff;crc_low<=0;
        end else begin
            if(command_valid && command_ready) command_valid<=0;
            if(rx_error) begin
                index<=0;idle_count<=0;rejected_count<=rejected_count+1'b1;
            end else if(rx_valid) begin
                idle_count<=0;
                if(index==0) begin
                    if(rx_data==8'h53) begin
                        index<=1;body[7:0]<=rx_data;crc<=crc_byte(16'hffff,rx_data);
                    end
                end else if(index==1) begin
                    if(rx_data==8'h52) begin
                        index<=2;body[15:8]<=rx_data;crc<=crc_byte(crc,rx_data);
                    end else if(rx_data==8'h53) begin
                        crc<=crc_byte(16'hffff,rx_data); // overlapping S S R
                    end else index<=0;
                end else if(index<13) begin
                    body[8*index +: 8]<=rx_data;crc<=crc_byte(crc,rx_data);index<=index+1'b1;
                end else if(index==13) begin
                    crc_low<=rx_data;index<=14;
                end else begin
                    index<=0;
                    if({rx_data,crc_low}==crc && body[23:16]==1 &&
                       body[31:24]!=255 && body[103:96]<=1) begin
                        if(!command_valid || command_ready) begin
                            command_valid<=1;cmd_seq<=body[31:24];
                            carrier_ftw<=body[63:32];nco_ftw<=body[95:64];enable<=body[96];
                        end else dropped_count<=dropped_count+1'b1;
                    end else rejected_count<=rejected_count+1'b1;
                end
            end else if(index!=0) begin
                if(idle_count==INTERBYTE_TIMEOUT_CYCLES-1) begin
                    index<=0;idle_count<=0;rejected_count<=rejected_count+1'b1;
                end else idle_count<=idle_count+1'b1;
            end
        end
    end
endmodule
