// Sample-derived diagnostics: rectangular-window 64-point complex DFT.
// Bin powers are normalized by N^2 and FULL_SCALE^2; no calibrated dBm.
// Log approximation is within about 0.4 dB except integer quantization at very
// small amplitudes. Spectrum clips to [-120, 7.5] dBFS in 0.5 dB steps.
// Noise estimates integrate the mean outer-bin power over all 64 bins. Filtering
// and signal energy in those bins bias this estimate; this is not calibrated NF.
module rx_observer #(
    parameter integer SAMPLE_RATE_HZ = 100000,
    parameter integer FULL_SCALE = 16384,
    parameter integer NOISE_EDGE_HZ = 35000
)(
    input wire clk, input wire rst,
    input wire iq_valid, input wire signed [15:0] iq_i, iq_q,
    input wire trigger,
    input wire [31:0] t_us,
    output reg [31:0] capture_t_us,
    output reg valid, input wire ready,
    output reg [511:0] spectrum,
    output reg [2047:0] iq,
    output reg signed [15:0] power_dbfs_x10, noise_dbfs_x10, snr_db_x10,
    output reg [31:0] dropped_count,
    output wire busy
);
    function signed [15:0] sine;
        input [5:0] phase;
        begin
            case (phase)
                6'd0: sine = 16'sd0;
                6'd1: sine = 16'sd1606;
                6'd2: sine = 16'sd3196;
                6'd3: sine = 16'sd4756;
                6'd4: sine = 16'sd6270;
                6'd5: sine = 16'sd7723;
                6'd6: sine = 16'sd9102;
                6'd7: sine = 16'sd10394;
                6'd8: sine = 16'sd11585;
                6'd9: sine = 16'sd12665;
                6'd10: sine = 16'sd13623;
                6'd11: sine = 16'sd14449;
                6'd12: sine = 16'sd15137;
                6'd13: sine = 16'sd15679;
                6'd14: sine = 16'sd16069;
                6'd15: sine = 16'sd16305;
                6'd16: sine = 16'sd16384;
                6'd17: sine = 16'sd16305;
                6'd18: sine = 16'sd16069;
                6'd19: sine = 16'sd15679;
                6'd20: sine = 16'sd15137;
                6'd21: sine = 16'sd14449;
                6'd22: sine = 16'sd13623;
                6'd23: sine = 16'sd12665;
                6'd24: sine = 16'sd11585;
                6'd25: sine = 16'sd10394;
                6'd26: sine = 16'sd9102;
                6'd27: sine = 16'sd7723;
                6'd28: sine = 16'sd6270;
                6'd29: sine = 16'sd4756;
                6'd30: sine = 16'sd3196;
                6'd31: sine = 16'sd1606;
                6'd32: sine = 16'sd0;
                6'd33: sine = -16'sd1606;
                6'd34: sine = -16'sd3196;
                6'd35: sine = -16'sd4756;
                6'd36: sine = -16'sd6270;
                6'd37: sine = -16'sd7723;
                6'd38: sine = -16'sd9102;
                6'd39: sine = -16'sd10394;
                6'd40: sine = -16'sd11585;
                6'd41: sine = -16'sd12665;
                6'd42: sine = -16'sd13623;
                6'd43: sine = -16'sd14449;
                6'd44: sine = -16'sd15137;
                6'd45: sine = -16'sd15679;
                6'd46: sine = -16'sd16069;
                6'd47: sine = -16'sd16305;
                6'd48: sine = -16'sd16384;
                6'd49: sine = -16'sd16305;
                6'd50: sine = -16'sd16069;
                6'd51: sine = -16'sd15679;
                6'd52: sine = -16'sd15137;
                6'd53: sine = -16'sd14449;
                6'd54: sine = -16'sd13623;
                6'd55: sine = -16'sd12665;
                6'd56: sine = -16'sd11585;
                6'd57: sine = -16'sd10394;
                6'd58: sine = -16'sd9102;
                6'd59: sine = -16'sd7723;
                6'd60: sine = -16'sd6270;
                6'd61: sine = -16'sd4756;
                6'd62: sine = -16'sd3196;
                6'd63: sine = -16'sd1606;
            endcase
        end
    endfunction
    localparam integer EDGE_BIN=(NOISE_EDGE_HZ*64+SAMPLE_RATE_HZ-1)/SAMPLE_RATE_HZ;
    localparam integer NOISE_BINS=65-2*EDGE_BIN;
    // Elaboration-only reference constant; never infer runtime integer division.
    function integer reference_db;
        input integer value;
        integer j,e,fraction,extra;
        begin
            e=0;for(j=0;j<31;j=j+1)if(value[j])e=j;
            fraction=(e>=4 ? value>>(e-4) : value<<(4-e))&15;
            case(fraction)
                0:extra=0;1:extra=3;2:extra=5;3:extra=7;
                4:extra=10;5:extra=12;6:extra=14;7:extra=16;
                8:extra=18;9:extra=19;10:extra=21;11:extra=23;
                12:extra=24;13:extra=26;14:extra=27;default:extra=29;
            endcase
            reference_db=e*30+e/10+extra;
        end
    endfunction
    localparam signed [12:0] REFERENCE_DB=reference_db(FULL_SCALE*FULL_SCALE);
    function [2:0] leading_byte;
        input [7:0] value;
        begin
            casex(value)
                8'b1xxxxxxx:leading_byte=7;8'b01xxxxxx:leading_byte=6;
                8'b001xxxxx:leading_byte=5;8'b0001xxxx:leading_byte=4;
                8'b00001xxx:leading_byte=3;8'b000001xx:leading_byte=2;
                8'b0000001x:leading_byte=1;default:leading_byte=0;
            endcase
        end
    endfunction
    function [5:0] leading_power;
        input [47:0] value;
        begin
            if(|value[47:40])leading_power=6'd40+leading_byte(value[47:40]);
            else if(|value[39:32])leading_power=6'd32+leading_byte(value[39:32]);
            else if(|value[31:24])leading_power=6'd24+leading_byte(value[31:24]);
            else if(|value[23:16])leading_power=6'd16+leading_byte(value[23:16]);
            else if(|value[15:8])leading_power=6'd8+leading_byte(value[15:8]);
            else leading_power={3'd0,leading_byte(value[7:0])};
        end
    endfunction
    function [4:0] fraction_db;
        input [3:0] fraction;
        begin
            case(fraction)
                0:fraction_db=0;1:fraction_db=3;2:fraction_db=5;3:fraction_db=7;
                4:fraction_db=10;5:fraction_db=12;6:fraction_db=14;7:fraction_db=16;
                8:fraction_db=18;9:fraction_db=19;10:fraction_db=21;11:fraction_db=23;
                12:fraction_db=24;13:fraction_db=26;14:fraction_db=27;default:fraction_db=29;
            endcase
        end
    endfunction
    localparam IDLE=0,CAPTURE=1,LOAD=2,MULTIPLY=3,ACCUMULATE=4,
               NORMALIZE=5,SQUARE=6,POWER=7,LOG_FIND=8,LOG_SHIFT=9,
               LOG_CALC=10,LOG_SAVE=11,BIN_QUANT=12,SAVE_BIN=13,
               FINISH=14,DIVIDE=15,FINISH_PUBLISH=16;
    reg [4:0] state;
    reg signed [15:0] memory_i[0:63],memory_q[0:63];
    reg [5:0] capture_index,bin_index,sample_index;
    reg signed [15:0] sample_i,sample_q,coefficient_cos,coefficient_sin;
    reg signed [31:0] product_ic,product_qs,product_qc,product_is;
    reg signed [39:0] acc_real,acc_imag;
    wire signed [32:0] term_real={product_ic[31],product_ic}+{product_qs[31],product_qs};
    wire signed [32:0] term_imag={product_qc[31],product_qc}-{product_is[31],product_is};
    reg signed [16:0] normalized_real,normalized_imag;
    reg [33:0] square_real,square_imag;
    reg [41:0] noise_sum;
    reg [47:0] noise_power,log_value;
    reg [5:0] log_exponent;
    reg [4:0] log_mantissa;
    reg [1:0] log_target;
    reg signed [12:0] log_db;
    reg signed [15:0] signal_db,noise_db;
    reg [10:0] quant_numerator;
    reg [7:0] quant_byte;
    reg [47:0] div_dividend,div_quotient;
    reg [6:0] div_remainder;
    reg [5:0] div_count;
    wire [7:0] div_next={div_remainder,div_dividend[47]};
    wire div_subtract=div_next>=NOISE_BINS;
    reg capture_power_valid;
    reg [32:0] capture_power;
    reg [39:0] signal_sum;
    wire signed [31:0] input_square_i=iq_i*iq_i;
    wire signed [31:0] input_square_q=iq_q*iq_q;
    wire [5:0] phase_index=bin_index*sample_index;
    wire [5:0] shifted_bin=bin_index+6'd32;
    wire outer_bin=bin_index>=EDGE_BIN && bin_index<=64-EDGE_BIN;
    wire [47:0] normalized_log=log_value>>(log_exponent>=4 ? log_exponent-6'd4 : 6'd0);
    wire [10:0] exponent_db=({5'd0,log_exponent}<<5)-({5'd0,log_exponent}<<1);
    wire [2:0] exponent_tenth=log_exponent>=40 ? 3'd4 : log_exponent>=30 ? 3'd3 :
        log_exponent>=20 ? 3'd2 : log_exponent>=10 ? 3'd1 : 3'd0;
    wire [11:0] absolute_db={1'b0,exponent_db}+{9'd0,exponent_tenth}+{7'd0,fraction_db(log_mantissa[3:0])};
    assign busy=state!=IDLE || valid;
    // synthesis translate_off
    initial if(FULL_SCALE<1 || FULL_SCALE>32768 || SAMPLE_RATE_HZ<1 || EDGE_BIN<1 || EDGE_BIN>32)
        $fatal(1,"invalid rx_observer profile");
    // synthesis translate_on
    always @(posedge clk) begin
        if(rst) begin
            state<=IDLE;valid<=0;spectrum<=0;iq<=0;capture_t_us<=0;
            power_dbfs_x10<=-1200;noise_dbfs_x10<=-1200;snr_db_x10<=0;
            dropped_count<=0;capture_index<=0;bin_index<=0;sample_index<=0;
            acc_real<=0;acc_imag<=0;capture_power_valid<=0;capture_power<=0;
            signal_sum<=0;noise_sum<=0;noise_power<=0;log_value<=0;
            log_exponent<=0;log_mantissa<=0;log_target<=0;log_db<=0;
            signal_db<=0;noise_db<=0;quant_numerator<=0;quant_byte<=0;
            div_dividend<=0;div_quotient<=0;div_remainder<=0;div_count<=0;
            sample_i<=0;sample_q<=0;coefficient_cos<=0;coefficient_sin<=0;
            product_ic<=0;product_qs<=0;product_qc<=0;product_is<=0;
            normalized_real<=0;normalized_imag<=0;square_real<=0;square_imag<=0;
        end else begin
            if(valid && ready)valid<=0;
            if(trigger && busy)dropped_count<=dropped_count+1'b1;
            capture_power_valid<=state==CAPTURE && iq_valid;
            if(state==CAPTURE && iq_valid)
                capture_power<={1'b0,input_square_i}+{1'b0,input_square_q};
            if(capture_power_valid)signal_sum<=signal_sum+capture_power;
            case(state)
                IDLE:if(trigger && !valid)begin
                    state<=CAPTURE;capture_index<=0;signal_sum<=0;noise_sum<=0;
                end
                CAPTURE:if(iq_valid)begin
                    memory_i[capture_index]<=iq_i;memory_q[capture_index]<=iq_q;
                    // Outputs are built in place while valid is low. They remain
                    // immutable from valid assertion until ready accepts them.
                    iq[capture_index*32 +: 32]<={iq_q,iq_i};
                    if(capture_index==0)capture_t_us<=t_us;
                    if(capture_index==63)begin
                        bin_index<=0;sample_index<=0;acc_real<=0;acc_imag<=0;state<=LOAD;
                    end else capture_index<=capture_index+1'b1;
                end
                LOAD:begin
                    sample_i<=memory_i[sample_index];sample_q<=memory_q[sample_index];
                    coefficient_cos<=sine(phase_index+6'd16);coefficient_sin<=sine(phase_index);state<=MULTIPLY;
                end
                MULTIPLY:begin
                    product_ic<=sample_i*coefficient_cos;product_qs<=sample_q*coefficient_sin;
                    product_qc<=sample_q*coefficient_cos;product_is<=sample_i*coefficient_sin;state<=ACCUMULATE;
                end
                ACCUMULATE:begin
                    acc_real<=acc_real+{{7{term_real[32]}},term_real};
                    acc_imag<=acc_imag+{{7{term_imag[32]}},term_imag};
                    if(sample_index==63)state<=NORMALIZE;
                    else begin sample_index<=sample_index+1'b1;state<=LOAD;end
                end
                NORMALIZE:begin
                    normalized_real<=acc_real>>>20;normalized_imag<=acc_imag>>>20;state<=SQUARE;
                end
                SQUARE:begin
                    square_real<=normalized_real*normalized_real;
                    square_imag<=normalized_imag*normalized_imag;state<=POWER;
                end
                POWER:begin
                    log_value<={14'd0,square_real}+{14'd0,square_imag};
                    log_target<=0;state<=LOG_FIND;
                end
                LOG_FIND:begin
                    log_exponent<=leading_power(log_value);state<=LOG_SHIFT;
                end
                LOG_SHIFT:begin
                    log_mantissa<=log_exponent>=4 ? normalized_log[4:0] : log_value[4:0]<<(6'd4-log_exponent);
                    state<=LOG_CALC;
                end
                LOG_CALC:begin
                    log_db<=log_value==0 ? -13'sd1200 : $signed({1'b0,absolute_db})-REFERENCE_DB;
                    state<=LOG_SAVE;
                end
                LOG_SAVE:begin
                    if(log_target==0)begin
                        if(outer_bin)noise_sum<=noise_sum+log_value[41:0];
                        quant_numerator<=log_db<=-1200 ? 11'd0 : log_db>=75 ? 11'd1275 : log_db+13'sd1200;
                        state<=BIN_QUANT;
                    end else if(log_target==1)begin
                        signal_db<=log_db < -1200 ? -16'sd1200 : {{3{log_db[12]}},log_db};
                        log_value<=noise_power;log_target<=2;state<=LOG_FIND;
                    end else begin
                        noise_db<=log_db < -1200 ? -16'sd1200 : {{3{log_db[12]}},log_db};
                        state<=FINISH_PUBLISH;
                    end
                end
                BIN_QUANT:begin
                    // Unsigned bounded division: eleven bits, not a signed
                    // 32-bit general divider on the spectrum write path.
                    quant_byte<=quant_numerator/11'd5;state<=SAVE_BIN;
                end
                SAVE_BIN:begin
                    spectrum[shifted_bin*8 +: 8]<=quant_byte;
                    if(bin_index==63)state<=FINISH;
                    else begin
                        bin_index<=bin_index+1'b1;sample_index<=0;
                        acc_real<=0;acc_imag<=0;state<=LOAD;
                    end
                end
                FINISH:begin
                    // Constant divisor, restoring one bit/clock. The remainder
                    // is seven bits instead of a 64-bit combinational divide.
                    div_dividend<={noise_sum,6'd0};div_quotient<=0;
                    div_remainder<=0;div_count<=47;state<=DIVIDE;
                end
                DIVIDE:begin
                    div_remainder<=div_subtract ? div_next-NOISE_BINS : div_next;
                    div_dividend<={div_dividend[46:0],1'b0};
                    div_quotient<={div_quotient[46:0],div_subtract};
                    if(div_count==0)begin
                        noise_power<={div_quotient[46:0],div_subtract};
                        log_value<={14'd0,signal_sum[39:6]};log_target<=1;state<=LOG_FIND;
                    end else div_count<=div_count-1'b1;
                end
                FINISH_PUBLISH:begin
                    power_dbfs_x10<=signal_db;noise_dbfs_x10<=noise_db;
                    snr_db_x10<=signal_db>noise_db ? signal_db-noise_db : 16'sd0;
                    valid<=1;state<=IDLE;
                end
                default:state<=IDLE;
            endcase
        end
    end
endmodule
