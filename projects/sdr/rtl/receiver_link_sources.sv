`timescale 1ns/1ps
// Entire receiver consumes ADC samples. Only adc_signal_source is a stand-in.
// Whole-message snapshots isolate held transport records from live DSP updates.
module receiver_link_sources #(
    parameter integer CLK_HZ=100000000,
    parameter integer TICK_CYCLES=CLK_HZ/100,
    parameter integer STATUS_TICKS=100,
    parameter [31:0] BUILD_ID=32'h53445231,
    parameter integer N=11,
    parameter integer SAMPLE_RATE_HZ=1000000,
    parameter integer BIT_RATE=10000,
    parameter integer DEVIATION_HZ=20000,
    parameter integer ADC_AMPLITUDE_A=1400,
    parameter integer ADC_AMPLITUDE_B=1000
)(
    input wire clk,rst,
    input wire cfg_reset,
    input wire pause, // drain transport before atomically applying new tuning
    input wire [31:0] carrier_ftw,nco_step,
    input wire adc_enable,
    output wire [N-1:0] req,
    output wire [8*N-1:0] p_type,p_flags,
    output wire [16*N-1:0] p_len,
    input wire [N-1:0] grant,
    output wire [8*N-1:0] p_data,
    output wire [N-1:0] p_valid,
    input wire [N-1:0] p_ready
);
    localparam integer P_BEST=0,P_FRAME=1,P_METRICS=3,P_LINK=5,P_STATUS=6,P_SPECTRUM=7,P_IQ=9;
    localparam integer US_CYCLES=CLK_HZ/1000000;
    localparam integer METRICS_TICKS=10,SPECTRUM_TICKS=10,IQ_TICKS=10,TELEM_TICKS=5;
    localparam integer IQ_RATE=SAMPLE_RATE_HZ/10;
    localparam [7:0] T_BEST=8'h10,T_FRAME=8'h11,T_METRICS=8'h20,T_LINK=8'h21,T_STATUS=1,T_SPECTRUM=8'h30,T_IQ=8'h31;
    // ------------------------------------------------------------ timebase
    reg [31:0] tick_div = 0;
    reg tick = 1'b0;
    reg [15:0] us_div = 0;
    reg [9:0] ms_div = 0;
    reg [31:0] t_us = 0, uptime_ms = 0;
    reg [7:0] ph_telem = 0, ph_metrics = 0, ph_spectrum = 0, ph_iq = 0, ph_status = 0;
    reg [7:0] ph_fail_a = 0, ph_fail_b = 0;

    always @(posedge clk) begin
        if (rst) begin
            tick_div <= 0;
            tick <= 1'b0;
            us_div <= 0;
            ms_div <= 0;
            t_us <= 0;
            uptime_ms <= 0;
            {ph_telem, ph_metrics, ph_spectrum, ph_iq, ph_status} <= 0;
        end else begin
            tick <= (tick_div == 0);
            tick_div <= (tick_div == TICK_CYCLES - 1) ? 0 : tick_div + 1;
            if (us_div == US_CYCLES - 1) begin
                us_div <= 0;
                t_us <= t_us + 1;
                ms_div <= (ms_div == 999) ? 0 : ms_div + 1'b1;
                if (ms_div == 999) uptime_ms <= uptime_ms + 1;
            end else begin
                us_div <= us_div + 1'b1;
            end
            if (tick) begin
                ph_telem <= (ph_telem == TELEM_TICKS - 1) ? 0 : ph_telem + 1'b1;
                ph_metrics <= (ph_metrics == METRICS_TICKS - 1) ? 0 : ph_metrics + 1'b1;
                ph_spectrum <= (ph_spectrum == SPECTRUM_TICKS - 1) ? 0 : ph_spectrum + 1'b1;
                ph_iq <= (ph_iq == IQ_TICKS - 1) ? 0 : ph_iq + 1'b1;
                ph_status <= (ph_status == STATUS_TICKS - 1) ? 0 : ph_status + 1'b1;
            end
        end
    end

    wire due_telem = !pause && tick && ph_telem == 0;
    wire due_metrics = !pause && tick && ph_metrics == 0;
    wire due_spectrum = !pause && tick && ph_spectrum == 0;
    wire due_iq = !pause && tick && ph_iq == 0;
    wire due_status = !pause && tick && ph_status == 0;

    // ------------------------------------------------------------ ports
    // data[g] is the payload byte at idx[g]. It may use up to two internal
    // register stages (link_msg_port LATENCY 3); idx is stable while it settles.
    wire [N-1:0] accept, drop;
    wire [15:0] idx [0:N-1];
    wire [7:0] data [0:N-1];
    wire [N-1:0] trigger;
    wire [15:0] len [0:N-1];
    wire [7:0] mtype [0:N-1];
    wire [15:0] dropped;

    genvar g;
    generate
        for (g = 0; g < N; g = g + 1) begin : port
            link_msg_port #(.LATENCY(3)) msg (
                .clk(clk), .rst(rst), .trigger(trigger[g]), .len(len[g]), .byte_in(data[g]), .grant(grant[g]),
                .ready(p_ready[g]), .req(req[g]), .idx(idx[g]), .data(p_data[8*g +: 8]), .valid(p_valid[g]),
                .accept(accept[g]), .drop(drop[g])
            );
            assign p_type[8*g +: 8] = mtype[g];
            assign p_flags[8*g +: 8] = (g==P_FRAME || g==P_FRAME+1 || g==P_METRICS || g==P_METRICS+1) ? 8'h05 : 8'h01;
            assign p_len[16*g +: 16] = len[g];
        end
    endgenerate


    wire datapath_rst=rst | cfg_reset;
    wire sample_valid;
    wire signed [11:0] sample_a,sample_b;
    adc_signal_source #(.CLK_HZ(CLK_HZ),.SAMPLE_RATE_HZ(SAMPLE_RATE_HZ),.BIT_RATE(BIT_RATE),
        .DEVIATION_HZ(DEVIATION_HZ),.PACKET_SAMPLES(SAMPLE_RATE_HZ/20),
        .AMPLITUDE_A(ADC_AMPLITUDE_A),.AMPLITUDE_B(ADC_AMPLITUDE_B)) adc(
        .clk(clk),.rst(datapath_rst),.enable(adc_enable),.carrier_ftw(carrier_ftw),
        .sample_valid(sample_valid),.sample_a(sample_a),.sample_b(sample_b));
    wire [1:0] frame_valid,frame_ready,frame_crc_ok,comb_ready;
    wire [151:0] frame_data[0:1];
    wire [7:0] frame_len[0:1],frame_type[0:1],frame_quality[0:1];
    wire [15:0] frame_seq[0:1],frame_magnitude[0:1];
    wire [31:0] frame_t[0:1],frame_frequency[0:1];
    wire [31:0] good_count[0:1],bad_count[0:1],sync_count[0:1],frame_dropped[0:1],observer_dropped[0:1];
    wire signed [15:0] frame_power[0:1];
    function automatic signed [15:0] relative_dbfs(input [15:0] magnitude);
        integer b,leading;
        begin
            leading=-20;
            for(b=0;b<16;b=b+1) if(magnitude[b]) leading=b;
            relative_dbfs=leading<0 ? -1200 : (leading-13)*60;
        end
    endfunction
    wire signed [63:0] center_product=$signed(nco_step)*$signed(SAMPLE_RATE_HZ);
    wire signed [31:0] center_hz=center_product >>> 32;
    wire comb_valid,comb_synthetic,stats_synthetic;
    wire [7:0] comb_source,comb_len;
    wire [31:0] comb_t,from_a,from_b,both_ok,neither_ok,best_sent,duplicates,rejected;
    wire [151:0] comb_frame;
    source_combiner #(.MAX_FRAME_BYTES(19),.MATCH_CYCLES(CLK_HZ/100),
        .DEDUPE_CYCLES(CLK_HZ/25),.DEDUPE_ENTRIES(4)) combiner(
        .clk(clk),.rst(datapath_rst),.in_valid(frame_valid & {2{!pause}} & { !req[P_FRAME+1],!req[P_FRAME]}),.in_ready(comb_ready),
        .in_crc_ok(frame_crc_ok),.in_synthetic(2'b11),.in_type({frame_type[1],frame_type[0]}),
        .in_seq({frame_seq[1],frame_seq[0]}),.in_t_us({frame_t[1],frame_t[0]}),
        .in_rssi_x10({frame_power[1],frame_power[0]}),.in_quality({frame_quality[1],frame_quality[0]}),
        .in_len({frame_len[1],frame_len[0]}),.in_frame({frame_data[1],frame_data[0]}),
        .out_valid(comb_valid),.out_ready(!pause && !req[P_BEST]),.out_source(comb_source),
        .out_synthetic(comb_synthetic),.out_t_us(comb_t),.out_len(comb_len),.out_frame(comb_frame),
        .from_a(from_a),.from_b(from_b),.both_ok(both_ok),.neither_ok(neither_ok),.best_sent(best_sent),
        .duplicate_count(duplicates),.rejected_count(rejected),.stats_synthetic(stats_synthetic));
    reg [199:0] best_payload;
    assign mtype[P_BEST]=T_BEST;
    assign len[P_BEST]=25;
    assign trigger[P_BEST]=!pause && comb_valid && !req[P_BEST];
    always @(posedge clk) if(accept[P_BEST]) best_payload<={comb_frame,8'd19,comb_source,comb_t};
    assign data[P_BEST]=best_payload[8*idx[P_BEST]+:8];
    generate for(g=0;g<2;g=g+1) begin: channel
        localparam [7:0] CH=g;
        localparam integer PF=P_FRAME+g,PM=P_METRICS+g,PS=P_SPECTRUM+g,PI=P_IQ+g;
        wire iq_valid,signal_present,locked;
        wire signed [15:0] iq_i,iq_q;
        wire [31:0] frequency_offset;
        wire [7:0] quality;
        rx_pipeline #(.DECIMATION(10),.SAMPLES_PER_SYMBOL(SAMPLE_RATE_HZ/10/BIT_RATE),
            .IQ_RATE_HZ(IQ_RATE)) receiver(
            .clk(clk),.rst(datapath_rst),.t_us(t_us),.nco_step(nco_step),.sample_valid(sample_valid),
            .sample_data(g==0 ? sample_a : sample_b),.sample_synthetic(1'b1),
            .iq_valid(iq_valid),.iq_i(iq_i),.iq_q(iq_q),.quality(quality),
            .frequency_offset_hz(frequency_offset),.signal_present(signal_present),
            .frame_valid(frame_valid[g]),.frame_ready(frame_ready[g]),.frame_data(frame_data[g]),
            .frame_len(frame_len[g]),.frame_type(frame_type[g]),.frame_seq(frame_seq[g]),
            .frame_crc_ok(frame_crc_ok[g]),.frame_t_us(frame_t[g]),.frame_quality(frame_quality[g]),
            .frame_magnitude(frame_magnitude[g]),.frame_frequency_offset_hz(frame_frequency[g]),
            .sync_count(sync_count[g]),.good_count(good_count[g]),.bad_count(bad_count[g]),
            .dropped_count(frame_dropped[g]),.locked(locked));
        assign frame_power[g]=relative_dbfs(frame_magnitude[g]);
        assign frame_ready[g]=!pause && comb_ready[g] && !req[PF];
        assign trigger[PF]=frame_valid[g] && frame_ready[g];
        assign len[PF]=33;
        assign mtype[PF]=T_FRAME;
        reg [263:0] frame_payload;
        always @(posedge clk) if(accept[PF]) frame_payload <= {frame_data[g],8'd19,frame_frequency[g],
            frame_quality[g],frame_power[g],frame_t[g],7'd0,frame_crc_ok[g],CH};
        assign data[PF]=frame_payload[8*idx[PF]+:8];
        wire observation_valid;
        wire [31:0] capture_t_us;
        wire [7:0] spectrum_byte,iq_byte;
        wire signed [15:0] power_dbfs,noise_dbfs,snr_db;
        // The observer's RAMs are the held transport record: it stays blocked
        // (valid high) until both SPECTRUM and IQ have been fully streamed.
        reg observation_streaming;
        wire observation_start=observation_valid && !observation_streaming && !pause && !req[PS] && !req[PI];
        wire observation_release=observation_streaming && !req[PS] && !req[PI];
        wire [15:0] spectrum_index=idx[PS]-16'd22;
        wire [15:0] iq_index=idx[PI]-16'd12;
        rx_observer #(.SAMPLE_RATE_HZ(IQ_RATE),.FULL_SCALE(8192)) observer(
            .clk(clk),.rst(datapath_rst),.iq_valid(iq_valid),.iq_i(iq_i),.iq_q(iq_q),.trigger(due_spectrum),
            .t_us(t_us),.capture_t_us(capture_t_us),.valid(observation_valid),.ready(observation_release),
            .spectrum_addr(spectrum_index[5:0]),.spectrum_data(spectrum_byte),
            .iq_addr(iq_index[7:0]),.iq_data(iq_byte),
            .power_dbfs_x10(power_dbfs),.noise_dbfs_x10(noise_dbfs),.snr_db_x10(snr_db),
            .dropped_count(observer_dropped[g]));
        reg [191:0] metrics_payload;
        assign trigger[PM]=due_metrics;
        assign len[PM]=24;assign mtype[PM]=T_METRICS;
        always @(posedge clk) if(accept[PM]) metrics_payload <= {bad_count[g],good_count[g],
            sync_count[g],frequency_offset,snr_db,noise_dbfs,power_dbfs,7'd0,locked,CH};
        assign data[PM]=metrics_payload[8*idx[PM]+:8];
        reg [31:0] observation_t,saved_center;
        reg [15:0] row;
        assign trigger[PS]=observation_start;
        assign trigger[PI]=observation_start;
        assign len[PS]=86;assign mtype[PS]=T_SPECTRUM;
        assign len[PI]=268;assign mtype[PI]=T_IQ;
        always @(posedge clk) begin
            if(rst) row<=0;
            else if(accept[PS]) begin
                observation_t<=capture_t_us;saved_center<=center_hz;row<=row+1'b1;
            end
            // req rises on the edge after accept, so release waits for both
            // messages' final bytes rather than firing on the start edge.
            if(datapath_rst || observation_release) observation_streaming<=0;
            else if(observation_start) observation_streaming<=1;
        end
        wire [175:0] spectrum_header={8'd0,8'd50,-16'sd1200,32'd1562500,saved_center,
            observation_t,16'd64,row,8'd1,CH};
        // Header bytes use one register stage; body bytes come from the observer's
        // registered read port, within link_msg_port's LATENCY budget.
        reg spectrum_in_header,iq_in_header;
        reg [7:0] spectrum_header_byte,iq_header_byte;
        wire [95:0] iq_header={32'(IQ_RATE),observation_t,16'd64,8'd0,CH};
        always @(posedge clk) begin
            spectrum_in_header<=idx[PS]<22;spectrum_header_byte<=spectrum_header[8*idx[PS][4:0]+:8];
            iq_in_header<=idx[PI]<12;iq_header_byte<=iq_header[8*idx[PI][3:0]+:8];
        end
        assign data[PS]=spectrum_in_header ? spectrum_header_byte : spectrum_byte;
        assign data[PI]=iq_in_header ? iq_header_byte : iq_byte;
    end endgenerate
    reg [15:0] transport_dropped=0;
    wire [4:0] drop_sum[0:N];
    assign drop_sum[0]=0;
    generate for(g=0;g<N;g=g+1) begin: count_drops
        assign drop_sum[g+1]=drop_sum[g]+{4'd0,drop[g]};
    end endgenerate
    wire [4:0] drop_increment=drop_sum[N];
    always @(posedge clk) begin
        if(rst) transport_dropped<=0;
        else transport_dropped<=transport_dropped+drop_increment;
    end
    assign dropped=transport_dropped+frame_dropped[0]+frame_dropped[1]+observer_dropped[0]+observer_dropped[1];
    reg [159:0] link_payload;
    assign trigger[P_LINK]=due_status;assign mtype[P_LINK]=T_LINK;assign len[P_LINK]=20;
    always @(posedge clk) if(accept[P_LINK]) link_payload<={best_sent,neither_ok,both_ok,from_b,from_a};
    assign data[P_LINK]=link_payload[8*idx[P_LINK]+:8];
    reg [95:0] status_payload;
    assign trigger[P_STATUS]=due_status;assign mtype[P_STATUS]=T_STATUS;assign len[P_STATUS]=12;
    always @(posedge clk) if(accept[P_STATUS]) status_payload<={dropped,BUILD_ID,uptime_ms,8'd3,8'd2};
    assign data[P_STATUS]=status_payload[8*idx[P_STATUS]+:8];
endmodule
