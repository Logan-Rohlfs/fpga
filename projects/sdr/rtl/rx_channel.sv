// Real low-IF receiver. All state advances on valid samples; no sample spacing
// restriction. Frequency step is unsigned phase turns/sample (2^32 = one turn).
// Changing nco_step requires rst, which also discards filter/timing history.
// Integrate-and-dump is a first-order CIC; it is intentionally configurable,
// not a substitute for a transmitter-specific adjacent-channel rejection spec.
module rx_channel #(
    parameter integer DECIMATION = 10,
    parameter integer SAMPLES_PER_SYMBOL = 10,
    parameter integer MIN_MAGNITUDE = 64,
    parameter integer INVERT_BITS = 0,
    parameter integer IQ_RATE_HZ = 100000
)(
    input wire clk, input wire rst,
    input wire [31:0] nco_step,
    input wire sample_valid, input wire signed [11:0] sample_data,
    output reg iq_valid,
    output reg signed [15:0] iq_i, output reg signed [15:0] iq_q,
    output reg bit_valid, output reg bit_data,
    output reg signed [31:0] discriminator,
    output reg [15:0] magnitude,
    output reg [7:0] quality,
    output reg signed [31:0] frequency_offset_hz,
    output reg signal_present
);
    // A signed 12x8 product uses 20 bits. Keep one guard bit beyond
    // log2(DECIMATION) growth, rather than synthesizing a 40-bit divider.
    localparam integer ACC_BITS = 21 + $clog2(DECIMATION);
    localparam integer DEC_BITS = DECIMATION < 2 ? 1 : $clog2(DECIMATION);
    localparam integer SYMBOL_BITS = $clog2(SAMPLES_PER_SYMBOL);
    localparam signed [ACC_BITS-1:0] SCALE_DIVISOR = DECIMATION * 16;
    // Quarter-wave lookup: no external ROM file or vendor primitive.
    function signed [7:0] sine;
        input [4:0] phase;
        reg [7:0] level;
        reg [3:0] index;
        begin
            index = phase[3] ? 4'd8 - {1'b0,phase[2:0]} : {1'b0,phase[2:0]};
            case(index)
                0:level=0; 1:level=25; 2:level=49; 3:level=71;
                4:level=90; 5:level=106; 6:level=117; 7:level=125;
                default:level=127;
            endcase
            sine = phase[4] ? -$signed(level) : $signed(level);
        end
    endfunction
    function signed [15:0] scale;
        input signed [ACC_BITS-1:0] value;
        reg signed [ACC_BITS-1:0] normalized;
        begin
            normalized = value / SCALE_DIVISOR;
            if(normalized > 32767) scale=32767;
            else if(normalized < -32768) scale=-32768;
            else scale=normalized[15:0];
        end
    endfunction
    function [15:0] absolute;
        input signed [15:0] value;
        begin absolute = value[15] ? -value : value; end
    endfunction
    localparam integer MIDPOINT = (SAMPLES_PER_SYMBOL < 2) ? 1 : SAMPLES_PER_SYMBOL/2;
    // Quadrant unwrap averaged over 1024 IQ samples: a coarse, data-dependent
    // mean frequency, not an invented calibrated carrier/SNR estimate.
    wire [1:0] quadrant = iq_q[15] ? (iq_i[15] ? 2'd2 : 2'd3)
                                              : (iq_i[15] ? 2'd1 : 2'd0);
    reg [1:0] previous_quadrant;
    wire signed [1:0] quadrant_delta = quadrant-previous_quadrant;
    reg signed [12:0] phase_sum;
    wire signed [12:0] next_phase_sum = phase_sum + {{11{quadrant_delta[1]}},quadrant_delta};
    reg [9:0] frequency_count;
    reg [31:0] phase;
    reg mix_valid;
    reg signed [19:0] mixed_i, mixed_q;
    reg signed [ACC_BITS-1:0] sum_i, sum_q;
    reg [DEC_BITS-1:0] decimation_count;
    wire signed [ACC_BITS-1:0] accumulated_i = sum_i + {{(ACC_BITS-20){mixed_i[19]}},mixed_i};
    wire signed [ACC_BITS-1:0] accumulated_q = sum_q + {{(ACC_BITS-20){mixed_q[19]}},mixed_q};
    reg signed [15:0] previous_i, previous_q;
    reg previous_valid;
    reg cross_valid;
    reg signed [31:0] cross_a, cross_b;
    reg [16:0] cross_magnitude;
    wire signed [32:0] cross_difference = {cross_a[31],cross_a} - {cross_b[31],cross_b};
    wire decision = !cross_difference[32];
    reg previous_decision, have_decision;
    reg [SYMBOL_BITS-1:0] symbol_phase;
    reg [7:0] stable_count;
    // synthesis translate_off
    initial begin
        if(DECIMATION<1 || DECIMATION>1024 || SAMPLES_PER_SYMBOL<4 ||
           MIN_MAGNITUDE<1 || IQ_RATE_HZ<1 || IQ_RATE_HZ>1000000)
            $fatal(1,"invalid rx_channel profile");
    end
    // synthesis translate_on
    always @(posedge clk) begin
        if(rst) begin
            frequency_offset_hz<=0; previous_quadrant<=0; phase_sum<=0; frequency_count<=0;
            phase<=0; mix_valid<=0; mixed_i<=0; mixed_q<=0;
            sum_i<=0; sum_q<=0; decimation_count<=0;
            iq_valid<=0; iq_i<=0; iq_q<=0;
            previous_i<=0; previous_q<=0; previous_valid<=0;
            cross_valid<=0; cross_a<=0; cross_b<=0; cross_magnitude<=0;
            bit_valid<=0; bit_data<=0; discriminator<=0; magnitude<=0;
            quality<=0; signal_present<=0; previous_decision<=0;
            have_decision<=0; symbol_phase<=0; stable_count<=0;
        end else begin
            mix_valid<=sample_valid;
            iq_valid<=0; bit_valid<=0;
            if(sample_valid) begin
                phase<=phase+nco_step;
                mixed_i <= sample_data * sine(phase[31:27]+5'd8);
                mixed_q <= -(sample_data * sine(phase[31:27]));
            end
            if(mix_valid) begin
                if(decimation_count == DECIMATION-1) begin
                    iq_i<=scale(accumulated_i); iq_q<=scale(accumulated_q);
                    iq_valid<=1; sum_i<=0; sum_q<=0; decimation_count<=0;
                end else begin
                    sum_i<=accumulated_i; sum_q<=accumulated_q;
                    decimation_count<=decimation_count+1;
                end
            end
            cross_valid<=iq_valid && previous_valid;
            if(iq_valid) begin
                previous_quadrant<=quadrant;
                if(previous_valid) begin
                    if(frequency_count==1023) begin
                        frequency_offset_hz<=($signed(next_phase_sum)*IQ_RATE_HZ) >>> 12;
                        phase_sum<=0; frequency_count<=0;
                    end else begin
                        phase_sum<=next_phase_sum; frequency_count<=frequency_count+1'b1;
                    end
                end
                // Q[n]I[n-1] - I[n]Q[n-1] is positive above the NCO.
                cross_a<=iq_q*previous_i; cross_b<=iq_i*previous_q;
                cross_magnitude <= {1'b0,absolute(iq_i)}+{1'b0,absolute(iq_q)};
                previous_i<=iq_i; previous_q<=iq_q; previous_valid<=1;
            end
            if(cross_valid) begin
                discriminator <= cross_difference >>> 8;
                magnitude <= cross_magnitude[16] ? 16'hffff : cross_magnitude[15:0];
                signal_present <= cross_magnitude >= MIN_MAGNITUDE;
                if(cross_magnitude < MIN_MAGNITUDE) begin
                    have_decision<=0; symbol_phase<=0; stable_count<=0; quality<=0;
                end else begin
                    previous_decision<=decision; have_decision<=1;
                    if(!have_decision || decision != previous_decision) begin
                        // A transition identifies a symbol boundary. Sampling
                        // half a symbol later gives phase recovery from preamble.
                        symbol_phase<=1; stable_count<=1;
                    end else begin
                        if(stable_count < 255) stable_count<=stable_count+1;
                        if(symbol_phase == SAMPLES_PER_SYMBOL-1) symbol_phase<=0;
                        else symbol_phase<=symbol_phase+1;
                        if(symbol_phase == MIDPOINT) begin
                            bit_valid<=1; bit_data<=decision ^ (INVERT_BITS != 0);
                            quality <= stable_count >= MIDPOINT ? 255 : (stable_count*255)/MIDPOINT;
                        end
                    end
                end
            end
        end
    end
endmodule
