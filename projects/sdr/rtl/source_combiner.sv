// Bounded whole-frame A/B selector. Timing parameters describe clock counts,
// not RF settings. Payload bytes are opaque to this block.
module source_combiner #(
    parameter integer MAX_FRAME_BYTES = 255,
    parameter integer MATCH_CYCLES = 16,
    parameter integer DEDUPE_CYCLES = 64,
    parameter integer DEDUPE_ENTRIES = 4
) (
    input wire clk,
    input wire rst,
    input wire [1:0] in_valid,
    output wire [1:0] in_ready,
    input wire [1:0] in_crc_ok,
    input wire [1:0] in_synthetic,
    input wire [15:0] in_type,
    input wire [31:0] in_seq,
    input wire [63:0] in_t_us,
    input wire [31:0] in_rssi_x10,
    input wire [15:0] in_quality,
    input wire [15:0] in_len,
    input wire [2*MAX_FRAME_BYTES*8-1:0] in_frame,
    output reg out_valid,
    input wire out_ready,
    output reg [7:0] out_source,
    output reg out_synthetic,
    output reg [31:0] out_t_us,
    output reg [7:0] out_len,
    output reg [MAX_FRAME_BYTES*8-1:0] out_frame,
    output reg [31:0] from_a,
    output reg [31:0] from_b,
    output reg [31:0] both_ok,
    output reg [31:0] neither_ok,
    output reg [31:0] best_sent,
    output reg [31:0] duplicate_count,
    output reg [31:0] rejected_count,
    output reg stats_synthetic
);
    localparam integer FRAME_BITS = MAX_FRAME_BYTES * 8;
    localparam integer AGE_BITS = (MATCH_CYCLES < 2) ? 1 : $clog2(MATCH_CYCLES + 1);
    localparam integer TTL_BITS = (DEDUPE_CYCLES < 2) ? 1 : $clog2(DEDUPE_CYCLES + 1);
    localparam integer INDEX_BITS = (DEDUPE_ENTRIES < 2) ? 1 : $clog2(DEDUPE_ENTRIES);

    reg [1:0] occupied;
    reg [23:0] frame_key [0:1];
    reg crc_ok [0:1];
    reg synthetic [0:1];
    reg [31:0] timestamp [0:1];
    reg signed [15:0] rssi [0:1];
    reg [7:0] quality [0:1];
    reg [7:0] length [0:1];
    reg [FRAME_BITS-1:0] frame [0:1];
    // Saturating expiry age plus an order bit retain oldest-first retirement
    // even if both ages saturate while the output is stalled.
    reg [AGE_BITS-1:0] age [0:1];
    reg a_older;
    reg [23:0] history_key [0:DEDUPE_ENTRIES-1];
    reg [TTL_BITS-1:0] history_ttl [0:DEDUPE_ENTRIES-1];
    reg [INDEX_BITS-1:0] history_next;
    reg [23:0] output_key;

    reg [1:0] buffered_duplicate;
    reg [1:0] consume;
    reg [1:0] participants;
    reg select_valid;
    reg selected;
    reg [1:0] intake_duplicate;
    reg [1:0] store_input;
    reg [2:0] duplicate_increment;
    reg [1:0] reject_increment;
    reg [23:0] incoming_key [0:1];
    reg [1:0] incoming_matches_slot [0:1];
    integer c, h;

    // Deliberately no fall-through into a retiring slot. This makes the
    // accepted descriptor boundary explicit and avoids a long ready chain.
    assign in_ready = {2{!rst}} & ~occupied;

    always @* begin
        buffered_duplicate = 0;
        intake_duplicate = 0;
        store_input = 0;
        consume = 0;
        participants = 0;
        select_valid = 0;
        selected = 0;
        duplicate_increment = 0;
        reject_increment = 0;
        for (c = 0; c < 2; c = c + 1) begin
            incoming_key[c] = {in_type[c*8 +: 8], in_seq[c*16 +: 16]};
            // Compare against both slots before selection is known, so the
            // late select only drives a 2:1 mux rather than a key compare.
            incoming_matches_slot[c] = {incoming_key[c] == frame_key[1],
                                        incoming_key[c] == frame_key[0]};
            // The existing output remains a duplicate guard on its handshake
            // edge, including when its finite history entry has expired.
            buffered_duplicate[c] = occupied[c] && out_valid && frame_key[c] == output_key;
            intake_duplicate[c] = out_valid && incoming_key[c] == output_key;
            for (h = 0; h < DEDUPE_ENTRIES; h = h + 1) begin
                // ttl=1 expires on this edge, exactly DEDUPE_CYCLES clocks
                // after the edge that selected the key.
                if (history_ttl[h] > 1) begin
                    if (occupied[c] && frame_key[c] == history_key[h])
                        buffered_duplicate[c] = 1;
                    if (incoming_key[c] == history_key[h])
                        intake_duplicate[c] = 1;
                end
            end
        end
        consume = buffered_duplicate;
        if (!out_valid || out_ready) begin
            if ((occupied & ~buffered_duplicate) == 2'b11 && frame_key[0] == frame_key[1]) begin
                participants = 2'b11;
            end else if (occupied[0] && !buffered_duplicate[0] &&
                         age[0] >= MATCH_CYCLES-1 &&
                         (!occupied[1] || buffered_duplicate[1] ||
                          age[1] < MATCH_CYCLES-1 || a_older)) begin
                participants = 2'b01;
            end else if (occupied[1] && !buffered_duplicate[1] && age[1] >= MATCH_CYCLES-1) begin
                participants = 2'b10;
            end
        end
        consume = consume | participants;
        if (participants == 2'b11) begin
            selected = !crc_ok[0] || (crc_ok[1] &&
                       (quality[1] > quality[0] ||
                        (quality[1] == quality[0] && rssi[1] > rssi[0])));
            select_valid = crc_ok[0] || crc_ok[1];
        end else if (participants != 0) begin
            selected = participants[1];
            select_valid = crc_ok[selected];
        end
        for (c = 0; c < 2; c = c + 1) begin
            if (buffered_duplicate[c]) duplicate_increment = duplicate_increment + 1'b1;
            // Includes a counterpart first presented on the retirement edge.
            if (select_valid && incoming_matches_slot[c][selected]) intake_duplicate[c] = 1;
            if (in_valid[c] && in_ready[c]) begin
                if (in_len[c*8 +: 8] == 0 || in_len[c*8 +: 8] > MAX_FRAME_BYTES)
                    reject_increment = reject_increment + 1'b1;
                else if (intake_duplicate[c]) duplicate_increment = duplicate_increment + 1'b1;
                else store_input[c] = 1;
            end
        end
    end

    integer i;
    always @(posedge clk) begin
        if (rst) begin
            occupied <= 0;
            a_older <= 1;
            out_valid <= 0;
            out_source <= 0;
            out_synthetic <= 0;
            out_t_us <= 0;
            out_len <= 0;
            out_frame <= 0;
            output_key <= 0;
            history_next <= 0;
            from_a <= 0;
            from_b <= 0;
            both_ok <= 0;
            neither_ok <= 0;
            best_sent <= 0;
            duplicate_count <= 0;
            rejected_count <= 0;
            stats_synthetic <= 0;
            for (i = 0; i < 2; i = i + 1) begin
                age[i] <= 0;
                frame_key[i] <= 0;
                crc_ok[i] <= 0;
                synthetic[i] <= 0;
                timestamp[i] <= 0;
                rssi[i] <= 0;
                quality[i] <= 0;
                length[i] <= 0;
                frame[i] <= 0;
            end
            for (i = 0; i < DEDUPE_ENTRIES; i = i + 1) begin
                history_key[i] <= 0;
                history_ttl[i] <= 0;
            end
        end else begin
            // New entries follow any retained counterpart. Simultaneous
            // acceptance is an equal-age tie and favors A.
            if (store_input == 2'b11) a_older <= 1;
            else if (store_input[0]) a_older <= !(occupied[1] && !consume[1]);
            else if (store_input[1]) a_older <= occupied[0] && !consume[0];
            duplicate_count <= duplicate_count + duplicate_increment;
            rejected_count <= rejected_count + reject_increment;
            if (out_valid && out_ready) begin
                out_valid <= 0;
                best_sent <= best_sent + 1'b1;
            end
            for (i = 0; i < DEDUPE_ENTRIES; i = i + 1)
                if (history_ttl[i] != 0) history_ttl[i] <= history_ttl[i] - 1'b1;
            for (i = 0; i < 2; i = i + 1) begin
                if (occupied[i] && age[i] < MATCH_CYCLES) age[i] <= age[i] + 1'b1;
                if (consume[i]) occupied[i] <= 0;
                if (in_valid[i] && in_ready[i]) begin
                    if (in_synthetic[i]) stats_synthetic <= 1;
                    // Empty-slot descriptors may capture even when rejected or
                    // suppressed. Only occupancy makes them visible to selection;
                    // keep the dedupe path off payload/metadata write enables.
                    occupied[i] <= store_input[i];
                    age[i] <= 0;
                    frame_key[i] <= incoming_key[i];
                    crc_ok[i] <= in_crc_ok[i];
                    synthetic[i] <= in_synthetic[i];
                    timestamp[i] <= in_t_us[i*32 +: 32];
                    rssi[i] <= in_rssi_x10[i*16 +: 16];
                    quality[i] <= in_quality[i*8 +: 8];
                    length[i] <= in_len[i*8 +: 8];
                    frame[i] <= in_frame[i*FRAME_BITS +: FRAME_BITS];
                end
            end
            if (participants != 0 && !select_valid) neither_ok <= neither_ok + 1'b1;
            if (select_valid) begin
                out_valid <= 1;
                out_source <= {7'b0, selected};
                out_synthetic <= (participants[0] && synthetic[0]) || (participants[1] && synthetic[1]);
                out_t_us <= timestamp[selected];
                out_len <= length[selected];
                out_frame <= frame[selected];
                output_key <= frame_key[selected];
                if (selected) from_b <= from_b + 1'b1;
                else from_a <= from_a + 1'b1;
                if (participants == 2'b11 && crc_ok[0] && crc_ok[1]) both_ok <= both_ok + 1'b1;
                history_key[history_next] <= frame_key[selected];
                history_ttl[history_next] <= DEDUPE_CYCLES;
                if (history_next == DEDUPE_ENTRIES-1) history_next <= 0;
                else history_next <= history_next + 1'b1;
            end
        end
    end
endmodule
