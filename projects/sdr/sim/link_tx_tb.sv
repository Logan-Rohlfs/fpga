`timescale 1ns/1ps
// Two scripted producers: simultaneous requests, priority order, whole-message
// atomicity, zero-length payloads, seq increments, and CRC over header+payload.
module link_tx_tb;
    localparam integer N = 2;
    reg clk = 0;
    reg rst = 1;
    reg [N-1:0] req = 0;
    reg [8*N-1:0] p_type = 0, p_flags = 0;
    reg [16*N-1:0] p_len = 0;
    wire [N-1:0] grant, p_ready;
    reg [8*N-1:0] p_data = 0;
    reg [N-1:0] p_valid = 0;
    wire [7:0] out_data, sent_type;
    wire out_valid, out_last, sent_pulse;
    reg out_ready = 0;
    integer seed = 3;
    integer idx [0:N-1];
    reg [7:0] msg [0:63];
    integer n, m, expected_seq;
    integer sent_count = 0;

    always #5 clk = ~clk;

    link_tx #(.N(N)) dut (
        .clk(clk), .rst(rst), .req(req), .p_type(p_type), .p_flags(p_flags), .p_len(p_len), .grant(grant),
        .p_data(p_data), .p_valid(p_valid), .p_ready(p_ready), .out_data(out_data), .out_valid(out_valid),
        .out_last(out_last), .out_ready(out_ready), .sent_type(sent_type), .sent_pulse(sent_pulse)
    );

    function automatic [15:0] crc_step(input [15:0] c, input [7:0] d);
        integer b;
        begin
            c = c ^ {d, 8'h00};
            for (b = 0; b < 8; b = b + 1) c = c[15] ? ((c << 1) ^ 16'h1021) : (c << 1);
            crc_step = c;
        end
    endfunction

    // Payload byte k of port i is {i, k}: distinguishable per producer.
    genvar g;
    generate
        for (g = 0; g < N; g = g + 1) begin : producers
            always @(posedge clk) begin
                if (grant[g] && p_valid[g] && p_ready[g]) begin
                    idx[g] = idx[g] + 1;
                    if (idx[g] == p_len[16*g +: 16]) req[g] <= 1'b0;
                end
                p_valid[g] <= grant[g] && (idx[g] < p_len[16*g +: 16]) && ($random(seed) & 1);
                p_data[8*g +: 8] <= {g[3:0], idx[g][3:0]};
            end
        end
    endgenerate

    always @(posedge clk) out_ready <= $random(seed) & 1;
    always @(posedge clk) if (sent_pulse) sent_count <= sent_count + 1;

    task automatic post(input integer port, input [7:0] mtype, input [15:0] len);
        begin
            idx[port] = 0;
            p_type[8*port +: 8] <= mtype;
            p_flags[8*port +: 8] <= 8'h01;
            p_len[16*port +: 16] <= len;
            req[port] <= 1'b1;
        end
    endtask

    task automatic expect_message(input integer port, input [7:0] mtype, input [15:0] len);
        reg [15:0] crc;
        integer k;
        begin
            n = 0;
            while (1) begin
                @(posedge clk);
                if (out_valid && out_ready) begin
                    msg[n] = out_data;
                    n = n + 1;
                    if (out_last) break;
                end
            end
            if (n != len + 7) $fatal(1, "port %0d: %0d bytes, expected %0d", port, n, len + 7);
            if (msg[0] !== mtype || msg[1] !== 8'h01 || msg[2] !== expected_seq[7:0] ||
                {msg[4], msg[3]} !== len)
                $fatal(1, "port %0d: bad header %02x %02x %02x %02x%02x", port, msg[0], msg[1], msg[2], msg[4], msg[3]);
            for (k = 0; k < len; k = k + 1)
                if (msg[5 + k] !== {port[3:0], k[3:0]}) $fatal(1, "port %0d: payload byte %0d is %02x", port, k, msg[5 + k]);
            crc = 16'hffff;
            for (k = 0; k < len + 5; k = k + 1) crc = crc_step(crc, msg[k]);
            if ({msg[n - 1], msg[n - 2]} !== crc) $fatal(1, "port %0d: CRC %02x%02x, expected %04x", port, msg[n - 1], msg[n - 2], crc);
            expected_seq = expected_seq + 1;
        end
    endtask

    initial begin
        idx[0] = 0;
        idx[1] = 0;
        expected_seq = 0;
        repeat (3) @(posedge clk);
        rst <= 0;
        // Simultaneous requests: port 0 wins, port 1 follows intact.
        post(1, 8'h30, 9);
        post(0, 8'h10, 4);
        expect_message(0, 8'h10, 4);
        // Port 0 requests again while port 1 is in progress: must wait for it.
        fork
            expect_message(1, 8'h30, 9);
            begin
                wait (grant[1]);
                post(0, 8'h11, 3);
            end
        join
        expect_message(0, 8'h11, 3);
        // Zero-length payload.
        post(1, 8'h21, 0);
        expect_message(1, 8'h21, 0);
        // seq wraps: send enough messages to pass 255.
        for (m = 0; m < 260; m = m + 1) begin
            post(m % 2, 8'h01, 1);
            expect_message(m % 2, 8'h01, 1);
        end
        repeat (3) @(posedge clk);
        if (sent_count != 264) $fatal(1, "sent_pulse count %0d", sent_count);
        $display("PASS: link_tx priority, atomic messages, empty payload, seq wrap, CRC");
        $finish;
    end

    initial begin
        #2000000;
        $fatal(1, "link_tx test timed out");
    end
endmodule
