`timescale 1ns/1ps
// Stand-in producers for every host-link message type. All messages carry the
// SYNTHETIC flag: nothing here is measured. Each block is replaced by a real
// receiver stage later, keeping its link_tx port and message layout.
//
// Port order is link_tx priority (0 highest):
//   0 BEST_TELEM   1-2 CHAN_FRAME A/B   3-4 CHAN_METRICS A/B   5 LINK_STATS
//   6 STATUS       7-8 SPECTRUM A/B     9-10 IQ_SNAPSHOT A/B
// Periods are in ticks of TICK_CYCLES clocks (default 10 ms). Layouts follow
// docs/superpowers/specs/2026-09-29-host-link-layer-design.md, little-endian.
module link_test_sources #(
    parameter integer CLK_HZ = 100_000_000,
    parameter integer TICK_CYCLES = CLK_HZ / 100,
    parameter [31:0]  BUILD_ID = 32'h0,
    parameter integer TELEM_TICKS = 5,
    parameter integer METRICS_TICKS = 10,
    parameter integer SPECTRUM_TICKS = 10,
    parameter integer IQ_TICKS = 20,
    parameter integer STATUS_TICKS = 100,
    parameter integer FAIL_A_EVERY = 11,
    parameter integer FAIL_B_EVERY = 7,
    parameter integer N = 11
) (
    input  wire            clk,
    input  wire            rst,
    output wire [N-1:0]    req,
    output wire [8*N-1:0]  p_type,
    output wire [8*N-1:0]  p_flags,
    output wire [16*N-1:0] p_len,
    input  wire [N-1:0]    grant,
    output wire [8*N-1:0]  p_data,
    output wire [N-1:0]    p_valid,
    input  wire [N-1:0]    p_ready
);
    localparam [7:0] SYNTHETIC = 8'h01;
    localparam [7:0] T_STATUS = 8'h01, T_BEST = 8'h10, T_FRAME = 8'h11, T_METRICS = 8'h20,
                     T_LINK = 8'h21, T_SPECTRUM = 8'h30, T_IQ = 8'h31;
    localparam integer P_BEST = 0, P_FRAME = 1, P_METRICS = 3, P_LINK = 5, P_STATUS = 6,
                       P_SPECTRUM = 7, P_IQ = 9;
    localparam [7:0] APEX_LEN = 8'd19;      // type + seq + 15 text bytes + CRC16
    localparam integer US_CYCLES = (CLK_HZ >= 2_000_000) ? CLK_HZ / 1_000_000 : 1;
    localparam integer SPECTRUM_BINS = 256, IQ_PAIRS = 64;

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

    wire due_telem = tick && ph_telem == 0;
    wire due_metrics = tick && ph_metrics == 0;
    wire due_spectrum = tick && ph_spectrum == 0;
    wire due_iq = tick && ph_iq == 0;
    wire due_status = tick && ph_status == 0;

    // ------------------------------------------------------------ APEX TEST frame slots
    // Each slot builds one frame "type 0x01, seq, APEX RADIO TEST, CRC16 BE" and
    // pretends channel A and/or B received it. CRC is computed over 17 cycles.
    function automatic [7:0] apex_byte(input [4:0] i, input [7:0] seq);
        reg [8*15-1:0] text;
        begin
            text = "APEX RADIO TEST";
            case (i)
                0: apex_byte = 8'h01;
                1: apex_byte = seq;
                default: apex_byte = (i < 17) ? text[8*(16 - i) +: 8] : 8'h00;
            endcase
        end
    endfunction

    reg [31:0] slot = 0;
    reg [7:0] apex_seq = 0;
    reg [4:0] crc_i = 0;
    reg crc_busy = 1'b0;
    reg [15:0] crc = 16'hffff, frame_crc = 0;
    reg telem_go = 1'b0;
    reg fail_a = 1'b0, fail_b = 1'b0;
    reg [31:0] crc_good [0:1];
    reg [31:0] crc_bad [0:1];
    reg [31:0] from_a = 0, from_b = 0, both_ok = 0, neither_ok = 0, best_sent = 0;
    wire [15:0] crc_next;

    crc16_ccitt frame_crc_step (.crc(crc), .data(apex_byte(crc_i, apex_seq)), .next(crc_next));

    always @(posedge clk) begin
        telem_go <= 1'b0;
        if (rst) begin
            slot <= 0;
            crc_busy <= 1'b0;
            ph_fail_a <= 0;
            ph_fail_b <= 0;
            crc_good[0] <= 0;
            crc_good[1] <= 0;
            crc_bad[0] <= 0;
            crc_bad[1] <= 0;
            {from_a, from_b, both_ok, neither_ok, best_sent} <= 0;
        end else if (due_telem) begin
            apex_seq <= slot[7:0];
            fail_a <= (ph_fail_a == FAIL_A_EVERY - 1);
            fail_b <= (ph_fail_b == FAIL_B_EVERY - 1);
            ph_fail_a <= (ph_fail_a == FAIL_A_EVERY - 1) ? 0 : ph_fail_a + 1'b1;
            ph_fail_b <= (ph_fail_b == FAIL_B_EVERY - 1) ? 0 : ph_fail_b + 1'b1;
            crc <= 16'hffff;
            crc_i <= 0;
            crc_busy <= 1'b1;
        end else if (crc_busy) begin
            crc <= crc_next;
            if (crc_i == 16) begin
                crc_busy <= 1'b0;
                frame_crc <= crc_next;
                telem_go <= 1'b1;
                slot <= slot + 1;
                if (fail_a) crc_bad[0] <= crc_bad[0] + 1; else crc_good[0] <= crc_good[0] + 1;
                if (fail_b) crc_bad[1] <= crc_bad[1] + 1; else crc_good[1] <= crc_good[1] + 1;
                if (!fail_a) from_a <= from_a + 1;
                else if (!fail_b) from_b <= from_b + 1;
                if (!fail_a && !fail_b) both_ok <= both_ok + 1;
                if (fail_a && fail_b) neither_ok <= neither_ok + 1;
                else best_sent <= best_sent + 1;
            end else begin
                crc_i <= crc_i + 1'b1;
            end
        end
    end

    // Slowly drifting fake RF numbers derived from the slot counter.
    wire signed [15:0] rssi_now [0:1];
    wire signed [15:0] noise_now [0:1];
    wire [7:0] quality_now [0:1];
    wire signed [31:0] fo_now [0:1];
    assign rssi_now[0] = -16'sd716 + $signed({11'd0, slot[6:2]});
    assign rssi_now[1] = -16'sd781 + $signed({11'd0, slot[5:1]});
    assign noise_now[0] = -16'sd1000 + $signed({13'd0, slot[2:0]});
    assign noise_now[1] = -16'sd998 + $signed({13'd0, slot[3:1]});
    assign quality_now[0] = 8'd210 - {4'd0, slot[3:0]};
    assign quality_now[1] = 8'd175 - {3'd0, slot[4:0]};
    assign fo_now[0] = 32'sd10272 + $signed({24'd0, slot[5:0], 2'b00});
    assign fo_now[1] = 32'sd10272 + $signed({24'd0, slot[4:0], 3'b000});

    // ------------------------------------------------------------ ports
    // data[g] is the payload byte at idx[g]. It may use up to two internal
    // register stages (link_msg_port LATENCY 3); idx is stable while it settles.
    wire [N-1:0] accept, drop;
    wire [15:0] idx [0:N-1];
    wire [7:0] data [0:N-1];
    wire [N-1:0] trigger;
    wire [15:0] len [0:N-1];
    wire [7:0] mtype [0:N-1];
    reg [15:0] dropped = 0;

    genvar g;
    generate
        for (g = 0; g < N; g = g + 1) begin : port
            link_msg_port #(.LATENCY(3)) msg (
                .clk(clk), .rst(rst), .trigger(trigger[g]), .len(len[g]), .byte_in(data[g]), .grant(grant[g]),
                .ready(p_ready[g]), .req(req[g]), .idx(idx[g]), .data(p_data[8*g +: 8]), .valid(p_valid[g]),
                .accept(accept[g]), .drop(drop[g])
            );
            assign p_type[8*g +: 8] = mtype[g];
            assign p_flags[8*g +: 8] = SYNTHETIC;
            assign p_len[16*g +: 16] = len[g];
        end
    endgenerate

    always @(posedge clk) begin
        if (rst) dropped <= 0;
        else if (|drop) dropped <= dropped + 1'b1;
    end

    // ---- BEST_TELEM: source A unless A failed, then B; skipped when both failed.
    reg [7:0] best_seq = 0, best_source = 0;
    reg [15:0] best_crc = 0;
    reg [31:0] best_t = 0;
    assign mtype[P_BEST] = T_BEST;
    assign len[P_BEST] = 16'd6 + APEX_LEN;
    assign trigger[P_BEST] = telem_go && !(fail_a && fail_b);
    always @(posedge clk) if (accept[P_BEST]) begin
        best_seq <= apex_seq;
        best_crc <= frame_crc;
        best_source <= fail_a ? 8'd1 : 8'd0;
        best_t <= t_us;
    end
    wire [8*6-1:0] best_hdr = {APEX_LEN, best_source, best_t};
    function automatic [7:0] frame_byte(input [4:0] i, input [7:0] seq, input [15:0] c, input bad);
        begin
            if (i < 17) frame_byte = apex_byte(i, seq);
            else if (i == 17) frame_byte = c[15:8];
            else frame_byte = c[7:0] ^ {7'd0, bad};
        end
    endfunction
    assign data[P_BEST] = (idx[P_BEST] < 6) ? best_hdr[8*idx[P_BEST][2:0] +: 8]
                                            : frame_byte(idx[P_BEST] - 16'd6, best_seq, best_crc, 1'b0);

    generate
        for (g = 0; g < 2; g = g + 1) begin : channel
            localparam [7:0] CH = g;
            // ---- CHAN_FRAME
            localparam integer PF = P_FRAME + g;
            reg [7:0] f_seq = 0;
            reg [15:0] f_crc = 0;
            reg f_bad = 1'b0;
            reg [31:0] f_t = 0;
            reg [15:0] f_rssi = 0;
            reg [7:0] f_q = 0;
            reg [31:0] f_fo = 0;
            assign mtype[PF] = T_FRAME;
            assign len[PF] = 16'd14 + APEX_LEN;
            assign trigger[PF] = telem_go;
            always @(posedge clk) if (accept[PF]) begin
                f_seq <= apex_seq;
                f_crc <= frame_crc;
                f_bad <= (g == 0) ? fail_a : fail_b;
                f_t <= t_us;
                f_rssi <= rssi_now[g];
                f_q <= quality_now[g];
                f_fo <= fo_now[g];
            end
            wire [8*14-1:0] f_hdr = {APEX_LEN, f_fo, f_q, f_rssi, f_t, {7'd0, !f_bad}, CH};
            assign data[PF] = (idx[PF] < 14) ? f_hdr[8*idx[PF][3:0] +: 8]
                                             : frame_byte(idx[PF] - 16'd14, f_seq, f_crc, f_bad);

            // ---- CHAN_METRICS
            localparam integer PM = P_METRICS + g;
            reg [8*24-1:0] m_payload = 0;
            assign mtype[PM] = T_METRICS;
            assign len[PM] = 16'd24;
            assign trigger[PM] = due_metrics;
            always @(posedge clk) if (accept[PM])
                m_payload <= {crc_bad[g], crc_good[g], slot, fo_now[g], rssi_now[g] - noise_now[g],
                              noise_now[g], rssi_now[g], 8'd0, CH};
            assign data[PM] = m_payload[8*idx[PM][4:0] +: 8];

            // ---- SPECTRUM: noise floor, two FSK lobes (±25 bins), and a walking tone.
            localparam integer PS = P_SPECTRUM + g;
            reg [15:0] s_row = 0, s_row_now = 0;
            assign mtype[PS] = T_SPECTRUM;
            assign len[PS] = 16'd6 + SPECTRUM_BINS;
            assign trigger[PS] = due_spectrum;
            always @(posedge clk) begin
                if (rst) s_row_now <= 0;
                else if (accept[PS]) begin
                    s_row <= s_row_now;
                    s_row_now <= s_row_now + 1'b1;
                end
            end
            wire [8*6-1:0] s_hdr = {16'd256, s_row, 8'd0, CH};
            wire [7:0] k = idx[PS][7:0] - 8'd6;
            wire [7:0] hash = (k * 8'd37 + s_row[7:0] * 8'd13 + CH * 8'd7) ^ {2'd0, k[7:2]};
            wire [7:0] noise = 8'd24 + {4'd0, hash[3:0]};
            wire [7:0] d_lo = (k > 8'd103) ? k - 8'd103 : 8'd103 - k;
            wire [7:0] d_hi = (k > 8'd153) ? k - 8'd153 : 8'd153 - k;
            wire [7:0] d_lobe = (d_lo < d_hi) ? d_lo : d_hi;
            wire [7:0] lobe = (d_lobe == 0) ? 8'd140 : (d_lobe == 1) ? 8'd128 : (d_lobe == 2) ? 8'd110 :
                              (d_lobe == 3) ? 8'd90 : 8'd0;
            wire [7:0] lobe_ch = (lobe > 8'd24 && g == 1) ? lobe - 8'd24 : lobe;
            wire [7:0] tone_at = s_row[7:0] * 8'd3 + CH * 8'd64;
            wire [7:0] tone = (k == tone_at) ? 8'd180 : ((k == tone_at + 8'd1) || (k + 8'd1 == tone_at)) ? 8'd120 : 8'd0;
            reg [7:0] lobe_q = 0, tone_q = 0, noise_q = 0;
            always @(posedge clk) begin
                lobe_q <= lobe_ch;
                tone_q <= tone;
                noise_q <= noise;
            end
            wire [7:0] peak = (lobe_q > tone_q) ? lobe_q : tone_q;
            assign data[PS] = (idx[PS] < 6) ? s_hdr[8*idx[PS][2:0] +: 8] : ((peak > noise_q) ? peak : noise_q);

            // ---- IQ_SNAPSHOT: points on a noisy constant-envelope circle.
            localparam integer PI = P_IQ + g;
            reg [15:0] q_snap = 0, q_snap_now = 0;
            assign mtype[PI] = T_IQ;
            assign len[PI] = 16'd4 + 4 * IQ_PAIRS;
            assign trigger[PI] = due_iq;
            always @(posedge clk) begin
                if (rst) q_snap_now <= 0;
                else if (accept[PI]) begin
                    q_snap <= q_snap_now;
                    q_snap_now <= q_snap_now + 1'b1;
                end
            end
            wire [15:0] b = idx[PI] - 16'd4;
            wire [7:0] j = b[9:2];
            wire [5:0] angle = j[5:0] * 6'd5 + q_snap[5:0] * 6'd3 + CH[5:0] * 6'd8;
            wire [7:0] ni8 = j * 8'd29 + q_snap[7:0] * 8'd7 + CH * 8'd3;
            wire [7:0] nq8 = j * 8'd53 + q_snap[7:0] * 8'd11;
            wire signed [15:0] n_i = $signed({8'd0, ni8}) - 16'sd128;
            wire signed [15:0] n_q = $signed({8'd0, nq8}) - 16'sd128;
            wire signed [15:0] i_val = (sine(angle + 6'd16) >>> g) + n_i;
            wire signed [15:0] q_val = (sine(angle) >>> g) + n_q;
            reg [15:0] part = 0;
            always @(posedge clk) part <= b[1] ? q_val : i_val;
            wire [8*4-1:0] q_hdr = {16'd64, 8'd0, CH};
            assign data[PI] = (idx[PI] < 4) ? q_hdr[8*idx[PI][1:0] +: 8] : (b[0] ? part[15:8] : part[7:0]);
        end
    endgenerate

    // ---- LINK_STATS
    reg [8*20-1:0] l_payload = 0;
    assign mtype[P_LINK] = T_LINK;
    assign len[P_LINK] = 16'd20;
    assign trigger[P_LINK] = due_status;
    always @(posedge clk) if (accept[P_LINK]) l_payload <= {best_sent, neither_ok, both_ok, from_b, from_a};
    assign data[P_LINK] = l_payload[8*idx[P_LINK][4:0] +: 8];

    // ---- STATUS (first one right after reset)
    reg [8*12-1:0] st_payload = 0;
    assign mtype[P_STATUS] = T_STATUS;
    assign len[P_STATUS] = 16'd12;
    assign trigger[P_STATUS] = due_status;
    always @(posedge clk) if (accept[P_STATUS]) st_payload <= {dropped, BUILD_ID, uptime_ms, 8'd3, 8'd1};
    assign data[P_STATUS] = st_payload[8*idx[P_STATUS][3:0] +: 8];

    // 8000 * sin(2*pi*a/64), quarter-wave table.
    function automatic signed [15:0] sine(input [5:0] a);
        reg [4:0] n;
        reg signed [15:0] v;
        begin
            n = a[4] ? (5'd16 - {1'b0, a[3:0]}) : {1'b0, a[3:0]};
            case (n)
                0: v = 0;       1: v = 784;     2: v = 1561;    3: v = 2322;
                4: v = 3061;    5: v = 3771;    6: v = 4445;    7: v = 5075;
                8: v = 5657;    9: v = 6184;    10: v = 6652;   11: v = 7055;
                12: v = 7391;   13: v = 7656;   14: v = 7846;   15: v = 7961;
                default: v = 8000;
            endcase
            sine = a[5] ? -v : v;
        end
    endfunction
endmodule
