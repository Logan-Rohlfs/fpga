`timescale 1ns/1ps
// Synthetic analog-boundary stimulus only. The receiver gets samples, never bits.
// Defaults are a configurable development profile, not measured transmitter settings.
// Five binomial NRZ taps at quarter-symbol spacing approximate Gaussian BT~0.5.
module adc_signal_source #(
    parameter integer CLK_HZ=100000000,
    parameter integer SAMPLE_RATE_HZ=1000000,
    parameter integer BIT_RATE=10000,
    parameter integer DEVIATION_HZ=20000,
    parameter integer PACKET_SAMPLES=50000,
    parameter integer AMPLITUDE_A=1400,
    parameter integer AMPLITUDE_B=1000,
    parameter integer NOISE_A=8,
    parameter integer NOISE_B=16,
    parameter integer DELAY_B_SAMPLES=3,
    parameter integer PREAMBLE_BITS=64,
    parameter [31:0] SYNC_WORD=32'hd391d391
)(
    input wire clk, rst, enable,
    input wire [31:0] carrier_ftw,
    output reg sample_valid,
    output reg signed [11:0] sample_a, sample_b
);
    localparam integer DIVIDER=CLK_HZ/SAMPLE_RATE_HZ;
    localparam integer SPS=SAMPLE_RATE_HZ/BIT_RATE;
    localparam integer QUARTER=SPS/4;
    localparam integer DATA_START=PREAMBLE_BITS+32;
    localparam integer CRC_START=DATA_START+136;
    localparam integer END_BIT=DATA_START+152;
    localparam integer B_DEPTH=DELAY_B_SAMPLES>0 ? DELAY_B_SAMPLES : 1;
    localparam signed [63:0] DEV_WIDE=(64'sd4294967296*DEVIATION_HZ)/SAMPLE_RATE_HZ;
    localparam signed [31:0] DEV_STEP=DEV_WIDE[31:0];
    integer clock_count, packet_count, bit_sample, bit_position, quarter_count;
    reg [7:0] sequence_number;
    reg [15:0] crc;
    reg active;
    reg [31:0] phase;
    reg [15:0] random_a, random_b;
    reg signed [2:0] shape0,shape1,shape2,shape3;
    reg signed [11:0] b_delay[0:B_DEPTH-1];
    integer j;
    function automatic [7:0] data_byte(input integer index, input [7:0] seq);
        begin
            case(index)
                0:data_byte=1; 1:data_byte=seq;
                2:data_byte="A";3:data_byte="P";4:data_byte="E";5:data_byte="X";
                6:data_byte=" ";7:data_byte="R";8:data_byte="A";9:data_byte="D";
                10:data_byte="I";11:data_byte="O";12:data_byte=" ";13:data_byte="T";
                14:data_byte="E";15:data_byte="S";16:data_byte="T";
                default:data_byte=0;
            endcase
        end
    endfunction
    reg packet_bit;
    reg [7:0] current_byte;
    integer relative_bit;
    always @* begin
        packet_bit=0;
        relative_bit=bit_position-DATA_START;
        current_byte=data_byte(relative_bit/8,sequence_number);
        if(bit_position<PREAMBLE_BITS) packet_bit=bit_position[0];
        else if(bit_position<DATA_START) packet_bit=SYNC_WORD[31-(bit_position-PREAMBLE_BITS)];
        else if(bit_position<CRC_START) packet_bit=current_byte[7-relative_bit%8];
        else if(bit_position<END_BIT) packet_bit=crc[15-(bit_position-CRC_START)];
    end
    function automatic signed [11:0] sine(input [7:0] angle);
        reg [5:0] address;
        reg signed [11:0] magnitude;
        begin
            address=angle[6] ? ~angle[5:0] : angle[5:0];
            case(address)
                6'd0:magnitude=12'sd25;
                6'd1:magnitude=12'sd75;
                6'd2:magnitude=12'sd126;
                6'd3:magnitude=12'sd176;
                6'd4:magnitude=12'sd226;
                6'd5:magnitude=12'sd275;
                6'd6:magnitude=12'sd325;
                6'd7:magnitude=12'sd375;
                6'd8:magnitude=12'sd424;
                6'd9:magnitude=12'sd473;
                6'd10:magnitude=12'sd522;
                6'd11:magnitude=12'sd570;
                6'd12:magnitude=12'sd618;
                6'd13:magnitude=12'sd666;
                6'd14:magnitude=12'sd713;
                6'd15:magnitude=12'sd760;
                6'd16:magnitude=12'sd807;
                6'd17:magnitude=12'sd852;
                6'd18:magnitude=12'sd898;
                6'd19:magnitude=12'sd943;
                6'd20:magnitude=12'sd987;
                6'd21:magnitude=12'sd1031;
                6'd22:magnitude=12'sd1074;
                6'd23:magnitude=12'sd1116;
                6'd24:magnitude=12'sd1158;
                6'd25:magnitude=12'sd1199;
                6'd26:magnitude=12'sd1239;
                6'd27:magnitude=12'sd1279;
                6'd28:magnitude=12'sd1318;
                6'd29:magnitude=12'sd1356;
                6'd30:magnitude=12'sd1393;
                6'd31:magnitude=12'sd1430;
                6'd32:magnitude=12'sd1465;
                6'd33:magnitude=12'sd1500;
                6'd34:magnitude=12'sd1533;
                6'd35:magnitude=12'sd1566;
                6'd36:magnitude=12'sd1598;
                6'd37:magnitude=12'sd1629;
                6'd38:magnitude=12'sd1659;
                6'd39:magnitude=12'sd1688;
                6'd40:magnitude=12'sd1716;
                6'd41:magnitude=12'sd1743;
                6'd42:magnitude=12'sd1769;
                6'd43:magnitude=12'sd1793;
                6'd44:magnitude=12'sd1817;
                6'd45:magnitude=12'sd1840;
                6'd46:magnitude=12'sd1861;
                6'd47:magnitude=12'sd1881;
                6'd48:magnitude=12'sd1901;
                6'd49:magnitude=12'sd1919;
                6'd50:magnitude=12'sd1936;
                6'd51:magnitude=12'sd1951;
                6'd52:magnitude=12'sd1966;
                6'd53:magnitude=12'sd1979;
                6'd54:magnitude=12'sd1992;
                6'd55:magnitude=12'sd2003;
                6'd56:magnitude=12'sd2012;
                6'd57:magnitude=12'sd2021;
                6'd58:magnitude=12'sd2028;
                6'd59:magnitude=12'sd2035;
                6'd60:magnitude=12'sd2039;
                6'd61:magnitude=12'sd2043;
                6'd62:magnitude=12'sd2046;
                6'd63:magnitude=12'sd2047;
            endcase
            sine=angle[7] ? -magnitude : magnitude;
        end
    endfunction
    function automatic signed [11:0] clamp(input signed [31:0] x);
        begin
            if(x>2047) clamp=2047;
            else if(x < -2048) clamp=-2048;
            else clamp=x[11:0];
        end
    endfunction
    wire signed [2:0] nrz=packet_bit ? 3'sd1 : -3'sd1;
    wire signed [7:0] shaped=nrz+4*shape0+6*shape1+4*shape2+shape3;
    wire signed [63:0] deviation_product=$signed(DEV_STEP)*$signed(shaped);
    wire signed [31:0] step=carrier_ftw+(deviation_product >>> 4);
    wire signed [31:0] noise_a=($signed({1'b0,random_a[7:0]})-128)*NOISE_A/128;
    wire signed [31:0] noise_b=($signed({1'b0,random_b[7:0]})-128)*NOISE_B/128;
    wire signed [31:0] tone_a=(active && enable) ? ($signed(sine(phase[31:24]))*AMPLITUDE_A) >>> 11 : 0;
    wire signed [31:0] tone_b=(active && enable) ? ($signed(sine(phase[31:24]))*AMPLITUDE_B) >>> 11 : 0;
    always @(posedge clk) begin
        sample_valid<=0;
        if(rst) begin
            clock_count<=0;packet_count<=0;bit_sample<=0;bit_position<=0;quarter_count<=0;
            sequence_number<=0;crc<=16'hffff;active<=0;phase<=0;
            random_a<=16'hace1;random_b<=16'hcafe;
            shape0<=-1;shape1<=-1;shape2<=-1;shape3<=-1;
            sample_a<=0;sample_b<=0;
            for(j=0;j<B_DEPTH;j=j+1) b_delay[j]<=0;
        end else if(clock_count==DIVIDER-1) begin
            clock_count<=0;sample_valid<=1;
            sample_a<=clamp(tone_a+noise_a);
            b_delay[0]<=clamp(tone_b+noise_b);
            for(j=1;j<B_DEPTH;j=j+1) b_delay[j]<=b_delay[j-1];
            sample_b<=DELAY_B_SAMPLES==0 ? clamp(tone_b+noise_b) : b_delay[B_DEPTH-1];
            phase<=phase+step;
            random_a<={random_a[14:0],random_a[15]^random_a[13]^random_a[12]^random_a[10]};
            random_b<={random_b[14:0],random_b[15]^random_b[13]^random_b[12]^random_b[10]};
            if(quarter_count==QUARTER-1) begin
                quarter_count<=0;shape0<=nrz;shape1<=shape0;shape2<=shape1;shape3<=shape2;
            end else quarter_count<=quarter_count+1;
            if(packet_count==PACKET_SAMPLES-1) packet_count<=0;
            else packet_count<=packet_count+1;
            if(packet_count==0) begin
                active<=1;bit_position<=0;bit_sample<=0;crc<=16'hffff;
            end else if(active) begin
                if(bit_sample==0 && bit_position>=DATA_START && bit_position<CRC_START)
                    crc<=(crc<<1)^((crc[15]^packet_bit) ? 16'h1021 : 16'h0000);
                if(bit_sample==SPS-1) begin
                    bit_sample<=0;
                    if(bit_position==END_BIT+1) begin active<=0;sequence_number<=sequence_number+1;end
                    else bit_position<=bit_position+1;
                end else bit_sample<=bit_sample+1;
            end
        end else clock_count<=clock_count+1;
    end
`ifndef SYNTHESIS
    initial begin
        if(CLK_HZ % SAMPLE_RATE_HZ != 0 || SAMPLE_RATE_HZ % BIT_RATE != 0 || SPS<4 || SPS%4!=0)
            $fatal(1,"ADC source requires integer clocks/sample and samples/bit divisible by four");
        if(PACKET_SAMPLES < (END_BIT+3)*SPS) $fatal(1,"Packet interval too short");
        if(DELAY_B_SAMPLES<0) $fatal(1,"Negative antenna delay");
    end
`endif
endmodule
