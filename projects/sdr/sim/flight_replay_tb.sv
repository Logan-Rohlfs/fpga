`timescale 1ns/1ps
// APEX flight replay through the real receiver: ROM -> RTL GFSK transmitter ->
// A/B ADC samples (noise, per-antenna loss windows) -> two rx_pipelines -> combiner.
// Every CRC-good frame must equal ROM[seq] plus its CRC, bit for bit. Outside its
// loss window each channel must decode every frame; inside it, none. The
// combiner must emit every frame exactly once, from the surviving antenna when
// one is lost. Whole loops are too long for event simulation (~16 s of air
// time), so each lane starts at a chosen slot (START_SLOT) on one edge of a
// loss window or at the loop wrap. The gate inside a window is a slot compare.
module flight_lane #(
    parameter integer START_SLOT=0,
    parameter integer SLOTS=1,
    parameter integer GAP_SLOTS=20
)(input wire clk, input wire rst, output reg done);
    // Demo profile values; flight_replay_tb checks them against the
    // elaborated receiver_link_sources DEMO_FLIGHT instance.
    localparam integer CLK_HZ=5_000_000, FRAME_BYTES=44, DATA_BYTES=42, ROM_FRAMES=293;
    localparam integer LOSS_A_FIRST=60, LOSS_A_LAST=69, LOSS_B_FIRST=228, LOSS_B_LAST=237;
    localparam integer LOOP=ROM_FRAMES+GAP_SLOTS;
    wire sample_valid;
    wire signed [11:0] sample_a, sample_b;
    adc_signal_source #(.CLK_HZ(CLK_HZ),.DEVIATION_HZ(25000),.PACKET_SAMPLES(50000),
        .AMPLITUDE_A(1400),.AMPLITUDE_B(1000),.NOISE_A(256),.NOISE_B(256),
        .PREAMBLE_FIRST_BIT(1),.SYNC_WORD(32'h00002dd4),.SYNC_BITS(16),
        .PAYLOAD_ROM(1),.DATA_BYTES(DATA_BYTES),.ROM_FILE("projects/sdr/rom/apex_flight.mem"),
        .ROM_FRAMES(ROM_FRAMES),.GAP_SLOTS(GAP_SLOTS),
        .LOSS_A_FIRST(LOSS_A_FIRST),.LOSS_A_LAST(LOSS_A_LAST),
        .LOSS_B_FIRST(LOSS_B_FIRST),.LOSS_B_LAST(LOSS_B_LAST),.START_SLOT(START_SLOT)) adc(
        .clk(clk),.rst(rst),.enable(1'b1),.carrier_ftw(32'd429496730),
        .sample_valid(sample_valid),.sample_a(sample_a),.sample_b(sample_b));
    wire [1:0] frame_valid, frame_ready, crc_ok, comb_ready;
    wire [FRAME_BYTES*8-1:0] data [0:1];
    wire [7:0] len [0:1], ftype [0:1], quality [0:1];
    wire [15:0] seq [0:1], magnitude [0:1];
    wire [31:0] t_us [0:1];
    genvar g;
    generate for(g=0;g<2;g=g+1) begin: channel
        wire [31:0] unused_count [0:4];
        wire iq_valid, bit_valid, bit_data, signal_present, locked, synthetic;
        wire signed [15:0] iq_i, iq_q;
        wire signed [31:0] discriminator, offset, frame_offset;
        wire [15:0] live_magnitude;
        wire [7:0] live_quality;
        rx_pipeline #(.DECIMATION(10),.SAMPLES_PER_SYMBOL(10),.IQ_RATE_HZ(100000),.FRAME_BYTES(FRAME_BYTES),
            .SYNC_WORD(32'h00002dd4),.SYNC_BITS(16),.SEQ_OFFSET(7),.SEQ_BYTES(2),
            .TYPE_FILTER(1),.FRAME_TYPE(8'h02),.BIT_TIMEOUT_CYCLES(CLK_HZ/100)) receiver(
            .clk(clk),.rst(rst),.nco_step(32'd429496730),.sample_valid(sample_valid),
            .sample_data(g==0 ? sample_a : sample_b),.sample_synthetic(1'b1),.t_us(32'd0),
            .synthetic(synthetic),.iq_valid(iq_valid),.iq_i(iq_i),.iq_q(iq_q),.bit_valid(bit_valid),
            .bit_data(bit_data),.discriminator(discriminator),.frequency_offset_hz(offset),
            .magnitude(live_magnitude),.quality(live_quality),.signal_present(signal_present),
            .frame_valid(frame_valid[g]),.frame_ready(frame_ready[g]),.frame_t_us(t_us[g]),
            .frame_frequency_offset_hz(frame_offset),.frame_quality(quality[g]),.frame_magnitude(magnitude[g]),
            .frame_data(data[g]),.frame_len(len[g]),.frame_type(ftype[g]),.frame_seq(seq[g]),
            .frame_crc_ok(crc_ok[g]),.sync_count(unused_count[0]),.good_count(unused_count[1]),
            .bad_count(unused_count[2]),.dropped_count(unused_count[3]),.timeout_count(unused_count[4]),
            .locked(locked));
        assign frame_ready[g]=comb_ready[g];
    end endgenerate
    wire comb_valid, comb_synthetic, stats_synthetic;
    wire [7:0] comb_source, comb_len;
    wire [31:0] comb_t, from_a, from_b, both_ok, neither_ok, best_sent, duplicates, rejected;
    wire [FRAME_BYTES*8-1:0] comb_frame;
    source_combiner #(.MAX_FRAME_BYTES(FRAME_BYTES),.MATCH_CYCLES(CLK_HZ/100),
        .DEDUPE_CYCLES(CLK_HZ/25),.DEDUPE_ENTRIES(4)) combiner(
        .clk(clk),.rst(rst),.in_valid(frame_valid),.in_ready(comb_ready),.in_crc_ok(crc_ok),
        .in_synthetic(2'b11),.in_type({ftype[1],ftype[0]}),.in_seq({seq[1],seq[0]}),
        .in_t_us({t_us[1],t_us[0]}),.in_rssi_x10({magnitude[1],magnitude[0]}),
        .in_quality({quality[1],quality[0]}),.in_len({len[1],len[0]}),.in_frame({data[1],data[0]}),
        .out_valid(comb_valid),.out_ready(1'b1),.out_source(comb_source),.out_synthetic(comb_synthetic),
        .out_t_us(comb_t),.out_len(comb_len),.out_frame(comb_frame),.from_a(from_a),.from_b(from_b),
        .both_ok(both_ok),.neither_ok(neither_ok),.best_sent(best_sent),.duplicate_count(duplicates),
        .rejected_count(rejected),.stats_synthetic(stats_synthetic));

    reg [7:0] rom [0:ROM_FRAMES*DATA_BYTES-1];
    initial $readmemh("projects/sdr/rom/apex_flight.mem", rom);
    function automatic [15:0] crc_step(input [15:0] c, input [7:0] d);
        integer b;
        begin
            c=c^{d,8'h00};
            for(b=0;b<8;b=b+1) c=c[15] ? ((c<<1)^16'h1021) : (c<<1);
            crc_step=c;
        end
    endfunction
    // Exact comparison of a received low-byte-first frame with ROM[n] + CRC.
    function automatic integer matches_rom(input integer n, input [FRAME_BYTES*8-1:0] frame);
        integer k;
        reg [15:0] c;
        begin
            matches_rom=1; c=16'hffff;
            for(k=0;k<DATA_BYTES;k=k+1) begin
                if(frame[8*k +: 8]!==rom[n*DATA_BYTES+k]) matches_rom=0;
                c=crc_step(c,rom[n*DATA_BYTES+k]);
            end
            if(frame[8*DATA_BYTES +: 16]!=={c[7:0],c[15:8]}) matches_rom=0;
        end
    endfunction
    function automatic integer lost(input integer ch, input integer slot);
        lost = ch==0 ? (slot>=LOSS_A_FIRST && slot<=LOSS_A_LAST) : (slot>=LOSS_B_FIRST && slot<=LOSS_B_LAST);
    endfunction

    integer got [0:1][0:ROM_FRAMES-1];
    integer best [0:ROM_FRAMES-1];
    integer best_src [0:ROM_FRAMES-1];
    integer ch, n, s, slot, expected, frames=0, a_only=0, b_only=0, i;
    initial begin
        done=0;
        for(i=0;i<ROM_FRAMES;i=i+1) begin got[0][i]=0; got[1][i]=0; best[i]=0; best_src[i]=-1; end
    end
    always @(posedge clk) if(!rst) begin
        for(ch=0;ch<2;ch=ch+1) if(frame_valid[ch] && frame_ready[ch] && crc_ok[ch]) begin
            n=seq[ch];
            if(n>=ROM_FRAMES || !matches_rom(n,data[ch])) $fatal(1,"lane %0d ch %0d: CRC-good frame seq %0d differs from ROM",START_SLOT,ch,n);
            got[ch][n]=got[ch][n]+1;
        end
        if(comb_valid) begin
            n=comb_frame[8*7 +: 16];
            if(n>=ROM_FRAMES || !matches_rom(n,comb_frame) || comb_len!=FRAME_BYTES || !comb_synthetic)
                $fatal(1,"lane %0d: BEST seq %0d differs from ROM",START_SLOT,n);
            best[n]=best[n]+1; best_src[n]=comb_source;
        end
    end
    // adc.replay.slot is the next slot to start. Once slot START+SLOTS has
    // started, every frame in the window (43.5 ms into a 50 ms slot) is over.
    wire [31:0] next_slot=adc.replay.slot;
    initial begin
        wait(!rst);
        wait(next_slot==(START_SLOT+SLOTS+1)%LOOP);
        // A lone frame waits MATCH_CYCLES for its counterpart before BEST.
        repeat(CLK_HZ/100+5000) @(posedge clk);
        for(s=START_SLOT;s<START_SLOT+SLOTS;s=s+1) begin
            slot=s%LOOP;
            if(slot<ROM_FRAMES) begin
                frames=frames+1;
                for(ch=0;ch<2;ch=ch+1) begin
                    expected=lost(ch,slot) ? 0 : 1;
                    if(got[ch][slot]!=expected)
                        $fatal(1,"lane %0d slot %0d ch %0d: %0d good frames, expected %0d",START_SLOT,slot,ch,got[ch][slot],expected);
                end
                if(best[slot]!=1) $fatal(1,"lane %0d slot %0d: %0d BEST frames",START_SLOT,slot,best[slot]);
                if(lost(0,slot) && best_src[slot]!=1) $fatal(1,"slot %0d: A lost but BEST not from B",slot);
                if(lost(1,slot) && best_src[slot]!=0) $fatal(1,"slot %0d: B lost but BEST not from A",slot);
                a_only=a_only+lost(1,slot); b_only=b_only+lost(0,slot);
            end
        end
        $display("lane start %0d: %0d frames exact; %0d covered by A, %0d covered by B; best_sent=%0d",
                 START_SLOT,frames,a_only,b_only,best_sent);
        done=1;
    end
endmodule

module flight_replay_tb;
    reg clk=0; always #5 clk=~clk;
    reg rst=1;
    wire [4:0] done;
    // A finished lane stops its clock so it costs no further simulation time.
    wire [4:0] lane_clk={5{clk}} & ~done;
    // Entry and exit of A's window (60-69, coast) and of B's (228-237, across
    // the COAST->DESCENT change at 233), and the end of the ROM through a
    // shortened one-slot gap back to frame 0.
    flight_lane #(.START_SLOT(59),.SLOTS(2)) lane_a(.clk(lane_clk[0]),.rst(rst),.done(done[0]));
    flight_lane #(.START_SLOT(69),.SLOTS(2)) lane_a_exit(.clk(lane_clk[1]),.rst(rst),.done(done[1]));
    flight_lane #(.START_SLOT(227),.SLOTS(2)) lane_b(.clk(lane_clk[2]),.rst(rst),.done(done[2]));
    flight_lane #(.START_SLOT(237),.SLOTS(2)) lane_b_exit(.clk(lane_clk[3]),.rst(rst),.done(done[3]));
    flight_lane #(.START_SLOT(292),.SLOTS(3),.GAP_SLOTS(1)) lane_wrap(.clk(lane_clk[4]),.rst(rst),.done(done[4]));

    // Idle (unclocked) reference instance: the lanes must use the demo profile
    // that receiver_link_sources elaborates for the board.
    wire [10:0] ref_req, ref_valid;
    wire [87:0] ref_type, ref_flags, ref_data;
    wire [175:0] ref_len;
    receiver_link_sources #(.CLK_HZ(5_000_000),.DEMO_FLIGHT(1)) profile(
        .clk(1'b0),.rst(1'b1),.cfg_reset(1'b0),.pause(1'b0),.carrier_ftw(32'd0),.nco_step(32'd0),
        .adc_enable(1'b0),.req(ref_req),.p_type(ref_type),.p_flags(ref_flags),.p_len(ref_len),
        .grant(11'd0),.p_data(ref_data),.p_valid(ref_valid),.p_ready(11'd0));
    initial begin
        if(profile.FRAME_BYTES!=lane_a.FRAME_BYTES || profile.FLIGHT_ROM_FRAMES!=lane_a.ROM_FRAMES ||
           profile.FLIGHT_GAP_SLOTS!=lane_a.GAP_SLOTS ||
           profile.FLIGHT_LOSS_A_FIRST!=lane_a.LOSS_A_FIRST || profile.FLIGHT_LOSS_A_LAST!=lane_a.LOSS_A_LAST ||
           profile.FLIGHT_LOSS_B_FIRST!=lane_a.LOSS_B_FIRST || profile.FLIGHT_LOSS_B_LAST!=lane_a.LOSS_B_LAST ||
           profile.adc.DEVIATION_HZ!=lane_a.adc.DEVIATION_HZ || profile.adc.NOISE_A!=lane_a.adc.NOISE_A ||
           profile.adc.NOISE_B!=lane_a.adc.NOISE_B || profile.adc.SYNC_WORD!=lane_a.adc.SYNC_WORD ||
           profile.adc.SYNC_BITS!=lane_a.adc.SYNC_BITS || profile.adc.PREAMBLE_FIRST_BIT!=lane_a.adc.PREAMBLE_FIRST_BIT ||
           profile.adc.AMPLITUDE_A!=lane_a.adc.AMPLITUDE_A || profile.adc.AMPLITUDE_B!=lane_a.adc.AMPLITUDE_B ||
           profile.adc.ROM_FILE!=lane_a.adc.ROM_FILE ||
           profile.channel[0].receiver.SYNC_WORD!=lane_a.channel[0].receiver.SYNC_WORD ||
           profile.channel[0].receiver.SEQ_OFFSET!=lane_a.channel[0].receiver.SEQ_OFFSET ||
           profile.channel[0].receiver.SEQ_BYTES!=lane_a.channel[0].receiver.SEQ_BYTES ||
           profile.channel[0].receiver.TYPE_FILTER!=lane_a.channel[0].receiver.TYPE_FILTER ||
           profile.channel[0].receiver.FRAME_TYPE!=lane_a.channel[0].receiver.FRAME_TYPE)
            $fatal(1,"flight_lane profile differs from receiver_link_sources DEMO_FLIGHT");
        repeat(5) @(negedge clk); rst=0;
        wait(&done);
        $display("PASS flight_replay: ROM frames bit-exact through GFSK ADC, noise and A/B loss windows; combiner covers each dropout");
        $finish;
    end
endmodule
