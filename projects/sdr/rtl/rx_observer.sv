// Sample-derived diagnostics: rectangular-window POINTS-point complex DFT
// (POINTS = 64, 128 or 256). Each observation captures POINTS samples, then
// computes every bin at three clocks per sample per bin: about
// 3*POINTS^2+10*POINTS clocks (about 2 ms at 256 points and 100 MHz) after a
// POINTS-sample capture (2.56 ms at 100 kS/s), within the SPECTRUM period.
// 256 is the upper limit: the sine table resolves 1/256 turn, and a 512-bin
// SPECTRUM payload (534 B) would exceed the link's 512-byte MAX_PAYLOAD.
// Bin powers are normalized by N^2 and FULL_SCALE^2; no calibrated dBm.
// Log approximation is within about 0.4 dB except integer quantization at very
// small amplitudes. Spectrum clips to [-120, 7.5] dBFS in 0.5 dB steps.
// Noise estimates integrate the mean outer-bin power over all POINTS bins. Filtering
// and signal energy in those bins bias this estimate; this is not calibrated NF.
// Captured I/Q and spectrum bytes live in small inferred RAMs and are read out
// through registered byte ports (one-clock latency). A published result stays
// readable and immutable from valid until ready releases it; the reader asserts
// ready only after it has finished reading. Reset makes both ports read zero.
// The I/Q snapshot port exposes the first 64 captured samples.
module rx_observer #(
    parameter integer POINTS = 64,
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
    input wire [$clog2(POINTS)-1:0] spectrum_addr, // byte k is bin k-POINTS/2 (DC at POINTS/2)
    output wire [7:0] spectrum_data,
    input wire [7:0] iq_addr,       // byte 4n+{0,1,2,3} = sample n {I lo,I hi,Q lo,Q hi}
    output wire [7:0] iq_data,
    output reg signed [15:0] power_dbfs_x10, noise_dbfs_x10, snr_db_x10,
    output reg [31:0] dropped_count,
    output wire busy
);
    // round(16384*sin(2*pi*k/256)) for k=0..64. Every supported length uses
    // this one exact table (the 64-point table is every fourth entry).
    function [14:0] quarter_sine;
        input [6:0] k;
        begin
            case(k)
                7'd0:quarter_sine=15'd0; 7'd1:quarter_sine=15'd402; 7'd2:quarter_sine=15'd804; 7'd3:quarter_sine=15'd1205; 7'd4:quarter_sine=15'd1606;
                7'd5:quarter_sine=15'd2006; 7'd6:quarter_sine=15'd2404; 7'd7:quarter_sine=15'd2801; 7'd8:quarter_sine=15'd3196; 7'd9:quarter_sine=15'd3590;
                7'd10:quarter_sine=15'd3981; 7'd11:quarter_sine=15'd4370; 7'd12:quarter_sine=15'd4756; 7'd13:quarter_sine=15'd5139; 7'd14:quarter_sine=15'd5520;
                7'd15:quarter_sine=15'd5897; 7'd16:quarter_sine=15'd6270; 7'd17:quarter_sine=15'd6639; 7'd18:quarter_sine=15'd7005; 7'd19:quarter_sine=15'd7366;
                7'd20:quarter_sine=15'd7723; 7'd21:quarter_sine=15'd8076; 7'd22:quarter_sine=15'd8423; 7'd23:quarter_sine=15'd8765; 7'd24:quarter_sine=15'd9102;
                7'd25:quarter_sine=15'd9434; 7'd26:quarter_sine=15'd9760; 7'd27:quarter_sine=15'd10080; 7'd28:quarter_sine=15'd10394; 7'd29:quarter_sine=15'd10702;
                7'd30:quarter_sine=15'd11003; 7'd31:quarter_sine=15'd11297; 7'd32:quarter_sine=15'd11585; 7'd33:quarter_sine=15'd11866; 7'd34:quarter_sine=15'd12140;
                7'd35:quarter_sine=15'd12406; 7'd36:quarter_sine=15'd12665; 7'd37:quarter_sine=15'd12916; 7'd38:quarter_sine=15'd13160; 7'd39:quarter_sine=15'd13395;
                7'd40:quarter_sine=15'd13623; 7'd41:quarter_sine=15'd13842; 7'd42:quarter_sine=15'd14053; 7'd43:quarter_sine=15'd14256; 7'd44:quarter_sine=15'd14449;
                7'd45:quarter_sine=15'd14635; 7'd46:quarter_sine=15'd14811; 7'd47:quarter_sine=15'd14978; 7'd48:quarter_sine=15'd15137; 7'd49:quarter_sine=15'd15286;
                7'd50:quarter_sine=15'd15426; 7'd51:quarter_sine=15'd15557; 7'd52:quarter_sine=15'd15679; 7'd53:quarter_sine=15'd15791; 7'd54:quarter_sine=15'd15893;
                7'd55:quarter_sine=15'd15986; 7'd56:quarter_sine=15'd16069; 7'd57:quarter_sine=15'd16143; 7'd58:quarter_sine=15'd16207; 7'd59:quarter_sine=15'd16261;
                7'd60:quarter_sine=15'd16305; 7'd61:quarter_sine=15'd16340; 7'd62:quarter_sine=15'd16364; 7'd63:quarter_sine=15'd16379; 7'd64:quarter_sine=15'd16384;
                default:quarter_sine=15'd0;
            endcase
        end
    endfunction
    // phase is in 1/256 turns; quarter-wave symmetry gives the full period.
    function signed [15:0] sine;
        input [7:0] phase;
        reg [14:0] magnitude;
        begin
            magnitude=quarter_sine(phase[6] ? 7'd64-{1'b0,phase[5:0]} : {1'b0,phase[5:0]});
            sine=phase[7] ? -$signed({1'b0,magnitude}) : $signed({1'b0,magnitude});
        end
    endfunction
    localparam integer LOG2N=$clog2(POINTS);
    localparam [LOG2N-1:0] LAST=POINTS-1;
    localparam integer EDGE_BIN=(NOISE_EDGE_HZ*POINTS+SAMPLE_RATE_HZ-1)/SAMPLE_RATE_HZ;
    localparam integer NOISE_BINS=POINTS+1-2*EDGE_BIN;
    // Accumulator, sum and divider widths grow by one bit per doubling of POINTS.
    localparam integer ACC_W=34+LOG2N,SIGNAL_W=34+LOG2N,NOISE_W=36+LOG2N;
    localparam integer DIV_W=NOISE_W+LOG2N,REM_W=$clog2(NOISE_BINS+1);
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
    // Inferred RAMs (no reset): {Q,I} per sample, one byte per spectrum bin.
    // dft_memory is single-port (capture writes, DFT reads) so POINTS samples
    // fit block RAM; snapshot_memory keeps only the 64 snapshot samples for
    // the reader port, so the longer DFT adds no dual-port LUT RAM.
    reg [31:0] dft_memory[0:POINTS-1];
    reg [31:0] snapshot_memory[0:63];
    reg [7:0] spectrum_memory[0:POINTS-1];
    reg [31:0] sample_word,iq_word;
    reg [7:0] spectrum_word;
    reg [1:0] iq_lane;
    reg has_data;
    reg [LOG2N-1:0] capture_index,bin_index,sample_index,phase_index;
    wire signed [15:0] sample_i=sample_word[15:0],sample_q=sample_word[31:16];
    reg signed [15:0] coefficient_cos,coefficient_sin;
    reg signed [31:0] product_ic,product_qs,product_qc,product_is;
    reg signed [ACC_W-1:0] acc_real,acc_imag;
    wire signed [32:0] term_real={product_ic[31],product_ic}+{product_qs[31],product_qs};
    wire signed [32:0] term_imag={product_qc[31],product_qc}-{product_is[31],product_is};
    reg signed [16:0] normalized_real,normalized_imag;
    reg [33:0] square_real,square_imag;
    reg [NOISE_W-1:0] noise_sum;
    reg [47:0] noise_power,log_value;
    reg [5:0] log_exponent;
    reg [4:0] log_mantissa;
    reg [1:0] log_target;
    reg signed [12:0] log_db;
    reg signed [15:0] signal_db,noise_db;
    reg [10:0] quant_numerator;
    reg [7:0] quant_byte;
    reg [DIV_W-1:0] div_dividend,div_quotient;
    reg [REM_W-1:0] div_remainder;
    reg [5:0] div_count;
    wire [REM_W:0] div_next={div_remainder,div_dividend[DIV_W-1]};
    wire div_subtract=div_next>=NOISE_BINS;
    reg capture_power_valid;
    reg [32:0] capture_power;
    reg [SIGNAL_W-1:0] signal_sum;
    wire signed [31:0] input_square_i=iq_i*iq_i;
    wire signed [31:0] input_square_q=iq_q*iq_q;
    wire [LOG2N-1:0] shifted_bin=bin_index+POINTS/2;
    wire outer_bin=bin_index>=EDGE_BIN && bin_index<=POINTS-EDGE_BIN;
    // DFT phase index in 1/256 turns.
    wire [7:0] table_phase=8'(phase_index)<<(8-LOG2N);
    wire [47:0] normalized_log=log_value>>(log_exponent>=4 ? log_exponent-6'd4 : 6'd0);
    wire [10:0] exponent_db=({5'd0,log_exponent}<<5)-({5'd0,log_exponent}<<1);
    wire [2:0] exponent_tenth=log_exponent>=40 ? 3'd4 : log_exponent>=30 ? 3'd3 :
        log_exponent>=20 ? 3'd2 : log_exponent>=10 ? 3'd1 : 3'd0;
    wire [11:0] absolute_db={1'b0,exponent_db}+{9'd0,exponent_tenth}+{7'd0,fraction_db(log_mantissa[3:0])};
    // dft_memory: one port, capture writes then DFT reads.
    wire [LOG2N-1:0] dft_address=state==CAPTURE ? capture_index : sample_index;
    wire capture_write=state==CAPTURE && iq_valid;
    always @(posedge clk) begin
        if(capture_write)dft_memory[dft_address]<={iq_q,iq_i};
        sample_word<=dft_memory[dft_address];
    end
    always @(posedge clk) begin
        if(capture_write && capture_index<64)snapshot_memory[capture_index[5:0]]<={iq_q,iq_i};
        iq_word<=snapshot_memory[iq_addr[7:2]];
        iq_lane<=iq_addr[1:0];
        if(state==SAVE_BIN)spectrum_memory[shifted_bin]<=quant_byte;
        spectrum_word<=spectrum_memory[spectrum_addr];
    end
    assign spectrum_data=has_data ? spectrum_word : 8'd0;
    assign iq_data=!has_data ? 8'd0 : iq_word[8*iq_lane +: 8];
    // floor(n/5) == (n*1639)>>13 exactly for 0 <= n <= 1275.
    wire [21:0] quant_product=quant_numerator*14'd1639;
    assign busy=state!=IDLE || valid;
    // Elaboration guard (synthesis and simulation): unsupported lengths fail.
    generate if(POINTS!=64 && POINTS!=128 && POINTS!=256) begin : unsupported_points
        $error("rx_observer POINTS must be 64, 128 or 256");
    end endgenerate
    // synthesis translate_off
    initial if((POINTS!=64 && POINTS!=128 && POINTS!=256) || FULL_SCALE<1 || FULL_SCALE>32768 ||
               SAMPLE_RATE_HZ<1 || EDGE_BIN<1 || EDGE_BIN>POINTS/2)
        $fatal(1,"invalid rx_observer profile");
    // synthesis translate_on
    always @(posedge clk) begin
        if(rst) begin
            state<=IDLE;valid<=0;has_data<=0;capture_t_us<=0;
            power_dbfs_x10<=-1200;noise_dbfs_x10<=-1200;snr_db_x10<=0;
            dropped_count<=0;capture_index<=0;bin_index<=0;sample_index<=0;phase_index<=0;
            acc_real<=0;acc_imag<=0;capture_power_valid<=0;capture_power<=0;
            signal_sum<=0;noise_sum<=0;noise_power<=0;log_value<=0;
            log_exponent<=0;log_mantissa<=0;log_target<=0;log_db<=0;
            signal_db<=0;noise_db<=0;quant_numerator<=0;quant_byte<=0;
            div_dividend<=0;div_quotient<=0;div_remainder<=0;div_count<=0;
            coefficient_cos<=0;coefficient_sin<=0;
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
                    // The RAMs are only written while valid is low, so a
                    // published result is immutable until ready releases it.
                    if(capture_index==0)capture_t_us<=t_us;
                    if(capture_index==LAST)begin
                        bin_index<=0;sample_index<=0;phase_index<=0;acc_real<=0;acc_imag<=0;state<=LOAD;
                    end else capture_index<=capture_index+1'b1;
                end
                LOAD:begin
                    // sample_word is read from port A at sample_index this edge.
                    coefficient_cos<=sine(table_phase+8'd64);coefficient_sin<=sine(table_phase);state<=MULTIPLY;
                end
                MULTIPLY:begin
                    product_ic<=sample_i*coefficient_cos;product_qs<=sample_q*coefficient_sin;
                    product_qc<=sample_q*coefficient_cos;product_is<=sample_i*coefficient_sin;state<=ACCUMULATE;
                end
                ACCUMULATE:begin
                    acc_real<=acc_real+{{(ACC_W-33){term_real[32]}},term_real};
                    acc_imag<=acc_imag+{{(ACC_W-33){term_imag[32]}},term_imag};
                    if(sample_index==LAST)state<=NORMALIZE;
                    else begin
                        // phase = bin*sample mod POINTS, accumulated instead of multiplied.
                        sample_index<=sample_index+1'b1;phase_index<=phase_index+bin_index;state<=LOAD;
                    end
                end
                NORMALIZE:begin
                    // Divide by POINTS and by the 2^14 coefficient scale.
                    normalized_real<=acc_real>>>(14+LOG2N);normalized_imag<=acc_imag>>>(14+LOG2N);state<=SQUARE;
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
                        if(outer_bin)noise_sum<=noise_sum+log_value[NOISE_W-1:0];
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
                    // Bounded divide-by-five as an exact reciprocal multiply.
                    quant_byte<=quant_product[20:13];state<=SAVE_BIN;
                end
                SAVE_BIN:begin
                    // RAM write of quant_byte at shifted_bin happens above.
                    if(bin_index==LAST)state<=FINISH;
                    else begin
                        bin_index<=bin_index+1'b1;sample_index<=0;phase_index<=0;
                        acc_real<=0;acc_imag<=0;state<=LOAD;
                    end
                end
                FINISH:begin
                    // Constant divisor, restoring one bit/clock. The remainder
                    // is REM_W bits instead of a wide combinational divide.
                    // Shifting by LOG2N integrates the mean over all POINTS bins.
                    div_dividend<={noise_sum,{LOG2N{1'b0}}};div_quotient<=0;
                    div_remainder<=0;div_count<=DIV_W-1;state<=DIVIDE;
                end
                DIVIDE:begin
                    div_remainder<=div_subtract ? div_next-NOISE_BINS : div_next;
                    div_dividend<={div_dividend[DIV_W-2:0],1'b0};
                    div_quotient<={div_quotient[DIV_W-2:0],div_subtract};
                    if(div_count==0)begin
                        // At most mean outer-bin power * POINTS < 2^43: fits 48 bits.
                        noise_power<=48'({div_quotient[DIV_W-2:0],div_subtract});
                        log_value<={14'd0,signal_sum[SIGNAL_W-1:LOG2N]};log_target<=1;state<=LOG_FIND;
                    end else div_count<=div_count-1'b1;
                end
                FINISH_PUBLISH:begin
                    power_dbfs_x10<=signal_db;noise_dbfs_x10<=noise_db;
                    snr_db_x10<=signal_db>noise_db ? signal_db-noise_db : 16'sd0;
                    valid<=1;has_data<=1;state<=IDLE;
                end
                default:state<=IDLE;
            endcase
        end
    end
endmodule
