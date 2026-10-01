`timescale 1ns/1ps
module source_combiner_tb;
    wire max_params_done, min_params_done;
    source_combiner_param_smoke #(.M(255)) max_params (.done(max_params_done));
    source_combiner_param_smoke #(.M(1)) min_params (.done(min_params_done));
    localparam M=8, MATCH=8, DEDUPE=40;
    reg clk=0, rst=1;
    always #5 clk=~clk;
    reg [1:0] in_valid=0, in_crc_ok=0, in_synthetic=0;
    wire [1:0] in_ready;
    reg [15:0] in_type=0, in_quality=0, in_len=0;
    reg [31:0] in_seq=0, in_rssi_x10=0;
    reg [63:0] in_t_us=0;
    reg [2*M*8-1:0] in_frame=0;
    wire out_valid, out_synthetic, stats_synthetic;
    reg out_ready=0;
    wire [7:0] out_source, out_len;
    wire [31:0] out_t_us;
    wire [M*8-1:0] out_frame;
    wire [31:0] from_a,from_b,both_ok,neither_ok,best_sent,duplicate_count,rejected_count;
    source_combiner #(.MAX_FRAME_BYTES(M),.MATCH_CYCLES(MATCH),.DEDUPE_CYCLES(DEDUPE),.DEDUPE_ENTRIES(4)) dut (.*);
    integer checks=0;
    task automatic cycles(input integer n);
        repeat(n) begin @(posedge clk); #1; end
    endtask
    task automatic reset;
        @(negedge clk); rst=1; in_valid=0; out_ready=0;
        cycles(2); @(negedge clk); rst=0; cycles(1);
        if (out_valid || stats_synthetic || from_a || from_b || both_ok || neither_ok || best_sent || duplicate_count || rejected_count)
            $fatal(1,"reset state/counters");
    endtask
    task automatic desc(input integer ch,seq,typ,good,q,rssi,len,synth);
        in_seq[ch*16+:16]=seq;
        in_type[ch*8+:8]=typ;
        in_crc_ok[ch]=good;
        in_quality[ch*8+:8]=q;
        in_rssi_x10[ch*16+:16]=rssi;
        in_len[ch*8+:8]=len;
        in_synthetic[ch]=synth;
        in_t_us[ch*32+:32]=1000+seq*2+ch;
        for(integer j=0;j<M;j=j+1) in_frame[ch*M*8+j*8+:8]=seq+j+ch*64;
    endtask
    task automatic send(input [1:0] mask);
        integer timeout;
        begin
            @(negedge clk); in_valid=mask; timeout=0;
            while(in_valid!=0) begin
                @(posedge clk);
                // Sample ready before sequential updates.
                in_valid <= in_valid & ~in_ready;
                #1; timeout=timeout+1;
                if(timeout>80) $fatal(1,"input blocked");
            end
            @(negedge clk); in_valid=0;
        end
    endtask
    task automatic output_check(input integer ch,seq,len,synth);
        integer timeout;
        begin
            timeout=0;
            while(!out_valid) begin cycles(1); timeout=timeout+1; if(timeout>40) $fatal(1,"missing output key %0d",seq); end
            if(out_source!==ch || out_len!==len || out_t_us!==1000+seq*2+ch || out_synthetic!==synth)
                $fatal(1,"output metadata key %0d source %0d len %0d time %0d synth %0d",seq,out_source,out_len,out_t_us,out_synthetic);
            for(integer j=0;j<len;j=j+1)
                if(out_frame[j*8+:8]!==((seq+j+ch*64)&255)) $fatal(1,"output bytes key %0d byte %0d",seq,j);
            checks=checks+1;
            @(negedge clk); out_ready=1; cycles(1); @(negedge clk); out_ready=0;
        end
    endtask
    task automatic quiet(input integer n);
        repeat(n) begin cycles(1); if(out_valid) $fatal(1,"unexpected output"); end
    endtask
    task automatic pair_case(input integer ca,cb,qa,qb,ra,rb,winner);
        reset;
        desc(0,7,1,ca,qa,ra,M,0); desc(1,7,1,cb,qb,rb,M,1); send(3);
        if(winner<0) begin quiet(MATCH+3); if(neither_ok!=1) $fatal(1,"neither counter"); end
        else begin
            output_check(winner,7,M,1);
            if(from_a!=(winner==0) || from_b!=(winner==1) || best_sent!=1 || both_ok!=(ca&&cb)) $fatal(1,"selection counters");
        end
        if(!stats_synthetic) $fatal(1,"sticky provenance");
    endtask
    initial begin
        pair_case(0,0,1,255,-1,1,-1);
        pair_case(1,0,1,255,-32768,32767,0);
        pair_case(0,1,255,1,32767,-32768,1);
        pair_case(1,1,255,1,-900,-100,0);
        pair_case(1,1,1,255,-100,-900,1);
        pair_case(1,1,200,200,-32768,32767,1);
        pair_case(1,1,200,199,-900,-100,0);
        pair_case(1,1,199,200,-100,-900,1);
        pair_case(1,1,200,200,-100,-900,0);
        pair_case(1,1,200,200,-900,-100,1);
        pair_case(1,1,200,200,-1,1,1);
        pair_case(1,1,200,200,1,-1,0);
        pair_case(1,1,200,200,-700,-700,0);
        // Delayed counterpart before expiry pairs immediately.
        reset; desc(0,10,1,1,10,-700,3,0); send(1); quiet(2);
        desc(1,10,1,1,20,-800,3,0); send(2); output_check(1,10,3,0);
        if(both_ok!=1 || stats_synthetic) $fatal(1,"delayed real pair");
        // Retirement occurs exactly MATCH clocks after acceptance. A counterpart
        // accepted on that edge is late, even if it has higher quality.
        reset; desc(0,9,1,1,1,-900,2,0); send(1); quiet(MATCH-1);
        desc(1,9,1,1,255,-1,2,1); send(2);
        if(!out_valid || duplicate_count!=1) $fatal(1,"timeout/late counterpart boundary");
        output_check(0,9,2,0); quiet(MATCH+2);
        if(both_ok || !stats_synthetic) $fatal(1,"late counterpart provenance/group");
        // Lone and different sequence/type keys retire independently.
        reset; desc(0,11,1,1,1,-1,1,0); send(1); quiet(2); output_check(0,11,1,0);
        desc(0,12,1,1,1,-1,2,0); desc(1,13,1,1,1,-1,4,1); send(3);
        output_check(0,12,2,0); output_check(1,13,4,1);
        desc(0,14,1,1,1,-1,2,0); desc(1,14,2,1,1,-1,4,1); send(3);
        output_check(0,14,2,0); output_check(1,14,4,1);
        // Rejected lengths never produce output; provenance counts acceptance.
        reset; desc(0,1,1,1,1,-1,0,1); desc(1,2,1,1,1,-1,M+1,0); send(3); quiet(MATCH+3);
        if(rejected_count!=2 || from_a || from_b || !stats_synthetic) $fatal(1,"length rejection");
        // Failed-only key does not poison recovery; recent selected key suppresses.
        reset; desc(0,20,1,0,1,-1,2,0); send(1); quiet(MATCH+3);
        desc(1,20,1,1,1,-1,2,1); send(2); output_check(1,20,2,1);
        desc(0,20,1,1,1,-1,2,0); send(1); quiet(MATCH+3);
        if(duplicate_count!=1 || neither_ok!=1 || best_sent!=1) $fatal(1,"recovery/dedupe counters");
        quiet(DEDUPE+2); send(1); output_check(0,20,2,0);
        // Output remains immutable after inputs change, cache expiry and stalled duplicate.
        reset; desc(0,25,1,1,1,-1,M,1); send(1);
        while(!out_valid) cycles(1);
        if(best_sent!=0 || from_a!=1) $fatal(1,"handshake counter advanced early");
        desc(0,25,1,1,255,100,1,0); send(1);
        repeat(DEDUPE+MATCH+5) begin
            cycles(1);
            if(!out_valid || out_source!=0 || out_len!=M || out_t_us!=1050 || !out_synthetic || out_frame!=64'h201f1e1d1c1b1a19)
                $fatal(1,"stalled output changed");
        end
        output_check(0,25,M,1); quiet(MATCH+3);
        if(duplicate_count!=1 || best_sent!=1 || from_a!=1) $fatal(1,"pending-output duplicate escaped");
        // Both pending ages saturate behind a stalled output; preserve B's age priority.
        reset; desc(0,40,1,1,1,-1,2,0); send(1); while(!out_valid) cycles(1);
        desc(1,41,1,1,1,-1,2,0); send(2); cycles(2);
        desc(0,42,1,1,1,-1,2,0); send(1); cycles(MATCH+3);
        if(in_ready!=0) $fatal(1,"full input buffers failed backpressure");
        output_check(0,40,2,0); output_check(1,41,2,0); output_check(0,42,2,0);
        // Four-entry cache evicts oldest after five distinct immediate pairs.
        reset;
        for(integer k=50;k<55;k=k+1) begin
            desc(0,k,1,1,2,-1,2,0); desc(1,k,1,1,1,-1,2,0); send(3); output_check(0,k,2,0);
        end
        desc(0,50,1,1,2,-1,2,0); desc(1,50,1,1,1,-1,2,0); send(3); output_check(0,50,2,0);
        if(duplicate_count || best_sent!=6) $fatal(1,"bounded cache eviction/key reuse");
        // Full 16-bit sequence identity, including wrap, must remain distinct.
        reset;
        desc(0,65535,1,1,1,-1,2,0); desc(1,255,1,1,1,-1,2,0); send(3);
        output_check(0,65535,2,0); output_check(1,255,2,0);
        desc(0,0,1,1,1,-1,2,0); send(1); output_check(0,0,2,0);
        // Reset with selected output and pending inputs removes everything.
        desc(1,30,1,1,1,-1,2,0); send(2); while(!out_valid) cycles(1);
        reset; quiet(MATCH+3);
        wait(max_params_done && min_params_done);
        $display("PASS: source_combiner %0d checked selections, ranking, matching, dedupe, lengths, stalls, reset",checks);
        $finish;
    end
    initial begin #100000; $fatal(1,"source combiner timeout"); end
endmodule


// Width endpoints plus one-clock matching/history and a one-entry ring.
// Explicit edge checks catch zero-width counters and off-by-one expiry.
module source_combiner_param_smoke #(parameter integer M=255)(output reg done=0);
    reg clk=0, rst=1;
    always #5 clk=~clk;
    reg [1:0] in_valid=0, in_crc_ok=3, in_synthetic=2;
    wire [1:0] in_ready;
    reg [15:0] in_type=16'h0101, in_quality=16'h0201;
    reg [15:0] in_len={8'(M),8'(M)};
    reg [31:0] in_seq=32'h00070007, in_rssi_x10=0;
    reg [63:0] in_t_us={32'd456,32'd123};
    reg [2*M*8-1:0] in_frame=0;
    wire out_valid, out_synthetic, stats_synthetic;
    reg out_ready=0;
    wire [7:0] out_source,out_len;
    wire [31:0] out_t_us;
    wire [M*8-1:0] out_frame;
    wire [31:0] from_a,from_b,both_ok,neither_ok,best_sent,duplicate_count,rejected_count;
    source_combiner #(.MAX_FRAME_BYTES(M),.MATCH_CYCLES(1),.DEDUPE_CYCLES(1),.DEDUPE_ENTRIES(1)) dut (.*);
    task automatic edge_check;
        @(posedge clk); #1;
    endtask
    task automatic check_output(input integer ch);
        if(!out_valid || out_source!==ch || out_len!==M || out_t_us!==(ch ? 456:123) || out_synthetic!==(ch==1))
            $fatal(1,"parameter M=%0d output metadata",M);
        // Include every byte, especially the high byte of a 255-byte payload.
        for(integer j=0;j<M;j=j+1)
            if(out_frame[j*8+:8]!==((j*37+ch*83+17)&255))
                $fatal(1,"parameter M=%0d payload byte %0d",M,j);
    endtask
    initial begin
        for(integer ch=0;ch<2;ch=ch+1)
            for(integer j=0;j<M;j=j+1) in_frame[ch*M*8+j*8+:8]=j*37+ch*83+17;
        edge_check;
        @(negedge clk); rst=0; in_valid=1;
        edge_check; // Acceptance: registered descriptors cannot fall through.
        if(out_valid || in_ready[0]) $fatal(1,"parameter acceptance boundary M=%0d",M);
        @(negedge clk); in_valid=2;
        edge_check; // A retires exactly one clock later; B is late on this edge.
        check_output(0);
        if(duplicate_count!=1 || best_sent!=0 || both_ok!=0) $fatal(1,"parameter late copy M=%0d",M);
        @(negedge clk); out_ready=1; // Keep B valid for a second descriptor.
        edge_check; // History expires now; pending output still guards handshake.
        if(out_valid || duplicate_count!=2 || best_sent!=1) $fatal(1,"parameter handshake guard M=%0d",M);
        @(negedge clk); out_ready=0;
        edge_check; // Same key is now accepted, with expired history and no output.
        if(duplicate_count!=2 || out_valid || in_ready[1]) $fatal(1,"parameter expiry M=%0d",M);
        @(negedge clk); in_valid=0;
        edge_check; check_output(1);
        if(from_a!=1 || from_b!=1 || !stats_synthetic) $fatal(1,"parameter reuse counters M=%0d",M);
        @(negedge clk); out_ready=1;
        edge_check;
        if(out_valid || best_sent!=2 || rejected_count || neither_ok) $fatal(1,"parameter final handshake M=%0d",M);
        done=1;
        $display("PASS: source_combiner parameter endpoints M=%0d, MATCH=1, DEDUPE=1, ENTRIES=1",M);
    end
endmodule
