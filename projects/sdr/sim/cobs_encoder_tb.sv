`timescale 1ns/1ps
// Feeds every golden vector (from sdr_cli.protocol --golden) with random
// handshake stalls on both sides and compares the encoded bytes exactly.
module cobs_encoder_tb;
    reg clk = 0;
    reg rst = 1;
    reg [7:0] in_data = 0;
    reg in_valid = 0;
    reg in_last = 0;
    wire in_ready;
    wire [7:0] out_data;
    wire out_valid;
    reg out_ready = 0;
    reg [15:0] golden [0:8191];
    integer base, n_in, n_out, i, k, vectors;
    integer seed = 7;

    always #5 clk = ~clk;

    cobs_encoder #(.DEPTH(1024)) dut (
        .clk(clk), .rst(rst), .in_data(in_data), .in_valid(in_valid), .in_last(in_last), .in_ready(in_ready),
        .out_data(out_data), .out_valid(out_valid), .out_ready(out_ready)
    );

    task automatic feed;
        begin
            for (i = 0; i < n_in; i = i + 1) begin
                while (($random(seed) & 3) == 0) @(posedge clk);
                in_data <= golden[base + 1 + i][7:0];
                in_last <= (i == n_in - 1);
                in_valid <= 1;
                @(posedge clk);
                while (!in_ready) @(posedge clk);
                in_valid <= 0;
                in_last <= 0;
            end
        end
    endtask

    task automatic collect;
        integer at;
        begin
            at = base + 2 + n_in;
            for (k = 0; k < n_out; k = k + 1) begin
                out_ready <= ($random(seed) & 1);
                @(posedge clk);
                while (!(out_valid && out_ready)) begin
                    out_ready <= ($random(seed) & 1);
                    @(posedge clk);
                end
                if (out_data !== golden[at + k][7:0])
                    $fatal(1, "vector %0d byte %0d: expected %02x, got %02x", vectors, k, golden[at + k][7:0], out_data);
            end
            out_ready <= 0;
        end
    endtask

    initial begin
        $readmemh("projects/sdr/sim/vectors/cobs_golden.hex", golden);
        repeat (3) @(posedge clk);
        rst <= 0;
        base = 0;
        vectors = 0;
        while (golden[base] !== 16'hffff) begin
            n_in = golden[base];
            n_out = golden[base + 1 + n_in];
            fork
                feed;
                collect;
            join
            repeat (3) @(posedge clk);
            if (out_valid) $fatal(1, "vector %0d: extra output byte %02x", vectors, out_data);
            base = base + 2 + n_in + n_out;
            vectors = vectors + 1;
        end
        if (vectors < 10) $fatal(1, "only %0d golden vectors read", vectors);
        $display("PASS: %0d COBS golden vectors with randomized handshakes", vectors);
        $finish;
    end

    initial begin
        #5000000;
        $fatal(1, "COBS encoder test timed out");
    end
endmodule
