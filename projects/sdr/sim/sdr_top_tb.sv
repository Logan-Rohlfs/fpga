`timescale 1ns/1ps
// End-to-end link test: decodes the UART line, un-COBSes each message, checks
// CRC, length per type, seq continuity, APEX frame CRCs, and that every message
// type (and both CHAN_FRAME CRC outcomes) appears. Raw line bytes are written to
// build/sdr/link_capture.bin so the host decoder can cross-check them.
module sdr_top_tb;
    localparam integer CLK_HZ = 4_000_000;       // 4 clocks per bit at 1 Mbaud
    localparam integer BIT_NS = 40;              // 10 ns clock period in simulation
    reg clk = 0;
    reg btnC = 0;
    wire uart_tx;
    wire led;

    always #5 clk = ~clk;

    sdr_top #(.CLK_HZ(CLK_HZ), .BAUD_RATE(1_000_000), .TICK_CYCLES(20_000), .STATUS_TICKS(60)) dut (
        .clk(clk), .btnC(btnC), .uart_tx(uart_tx), .led(led)
    );

    reg [7:0] enc [0:1023];
    reg [7:0] msg [0:1023];
    integer n_enc = 0, n_msg, capture, messages = 0, expected_seq = -1, led_toggles = 0;
    integer count [0:255];
    integer frame_ok = 0, frame_bad = 0, best_ok = 0;
    reg last_led = 0;
    reg all_seen = 0;

    function automatic [15:0] crc_step(input [15:0] c, input [7:0] d);
        integer b;
        begin
            c = c ^ {d, 8'h00};
            for (b = 0; b < 8; b = b + 1) c = c[15] ? ((c << 1) ^ 16'h1021) : (c << 1);
            crc_step = c;
        end
    endfunction

    function automatic integer expected_len(input [7:0] t);
        case (t)
            8'h01: expected_len = 12;
            8'h10: expected_len = 6 + 19;
            8'h11: expected_len = 14 + 19;
            8'h20: expected_len = 24;
            8'h21: expected_len = 20;
            8'h30: expected_len = 22 + 256;
            8'h31: expected_len = 12 + 256;
            default: expected_len = -1;
        endcase
    endfunction

    // APEX frame at msg[at..at+18]: CRC16 big-endian over the first 17 bytes.
    function automatic apex_crc_ok(input integer at);
        reg [15:0] c;
        integer k;
        begin
            c = 16'hffff;
            for (k = 0; k < 17; k = k + 1) c = crc_step(c, msg[at + k]);
            apex_crc_ok = (c == {msg[at + 17], msg[at + 18]}) && msg[at] == 8'h01;
        end
    endfunction

    task automatic handle_message;
        integer i, code, len;
        reg [15:0] c;
        begin
            // COBS decode enc[0..n_enc-1] into msg[].
            n_msg = 0;
            i = 0;
            while (i < n_enc) begin
                code = enc[i];
                if (code == 0 || i + code > n_enc) $fatal(1, "bad COBS block at %0d", i);
                for (int k = 1; k < code; k = k + 1) begin
                    msg[n_msg] = enc[i + k];
                    n_msg = n_msg + 1;
                end
                i = i + code;
                if (code < 255 && i < n_enc) begin
                    msg[n_msg] = 8'h00;
                    n_msg = n_msg + 1;
                end
            end
            if (n_msg < 7) $fatal(1, "message too short (%0d)", n_msg);
            len = {msg[4], msg[3]};
            if (n_msg != len + 7) $fatal(1, "type %02x: len %0d but %0d bytes", msg[0], len, n_msg);
            if (len != expected_len(msg[0])) $fatal(1, "type %02x: unexpected len %0d", msg[0], len);
            if (msg[1] !== 8'h01) $fatal(1, "type %02x: SYNTHETIC flag missing", msg[0]);
            c = 16'hffff;
            for (i = 0; i < n_msg - 2; i = i + 1) c = crc_step(c, msg[i]);
            if (c !== {msg[n_msg - 1], msg[n_msg - 2]}) $fatal(1, "type %02x: CRC mismatch", msg[0]);
            if (expected_seq >= 0 && msg[2] != expected_seq[7:0]) $fatal(1, "seq %0d, expected %0d", msg[2], expected_seq);
            expected_seq = (msg[2] + 1) % 256;
            if (msg[0] == 8'h11) begin
                if (apex_crc_ok(5 + 14) != msg[6]) $fatal(1, "CHAN_FRAME crc_ok flag disagrees with frame");
                if (msg[6]) frame_ok = frame_ok + 1; else frame_bad = frame_bad + 1;
            end
            if (msg[0] == 8'h10) begin
                if (!apex_crc_ok(5 + 6)) $fatal(1, "BEST_TELEM carries a bad frame");
                best_ok = best_ok + 1;
            end
            if (msg[0] == 8'h01 && {msg[16], msg[15]} != 0) $fatal(1, "STATUS reports %0d dropped", {msg[16], msg[15]});
            if (msg[0] == 8'h01 && msg[5] != 2) $fatal(1, "STATUS protocol version %0d, expected 2", msg[5]);
            // SPECTRUM axis: center 100 kHz, 390.625 Hz bins (390625 mHz), -120.0 dBFS ref, 0.5 dB step.
            // Payload starts at msg[5]: channel, averages, row u16, bins u16, t_us u32, center_hz, bin_mhz...
            if (msg[0] == 8'h30 && ({msg[18], msg[17], msg[16], msg[15]} != 100000 ||
                                    {msg[22], msg[21], msg[20], msg[19]} != 390625 ||
                                    {msg[24], msg[23]} != 16'hfb50 || msg[25] != 50))
                $fatal(1, "SPECTRUM axis metadata wrong");
            // channel, rsvd, pairs u16, t_us u32, sample_rate_hz u32
            if (msg[0] == 8'h31 && {msg[16], msg[15], msg[14], msg[13]} != 100000)
                $fatal(1, "IQ_SNAPSHOT sample rate wrong");
            count[msg[0]] = count[msg[0]] + 1;
            messages = messages + 1;
            all_seen = count[8'h01] >= 2 && count[8'h10] > 0 && count[8'h20] >= 2 && count[8'h21] >= 2 &&
                       count[8'h30] >= 2 && count[8'h31] >= 2 && frame_ok > 0 && frame_bad >= 2;
        end
    endtask

    task automatic read_byte(output [7:0] value);
        integer b;
        begin
            @(negedge uart_tx);
            #(BIT_NS / 2);
            if (uart_tx !== 0) $fatal(1, "bad start bit");
            for (b = 0; b < 8; b = b + 1) begin
                #(BIT_NS);
                value[b] = uart_tx;
            end
            #(BIT_NS);
            if (uart_tx !== 1) $fatal(1, "bad stop bit");
        end
    endtask

    always @(posedge clk) if (led !== last_led) begin
        last_led <= led;
        led_toggles <= led_toggles + 1;
    end

    initial begin : monitor
        reg [7:0] value;
        for (int t = 0; t < 256; t = t + 1) count[t] = 0;
        capture = $fopen("build/sdr/link_capture.bin", "wb");
        forever begin
            read_byte(value);
            $fwrite(capture, "%c", value);
            if (value == 8'h00) begin
                handle_message;
                n_enc = 0;
            end else begin
                if (n_enc == 1024) $fatal(1, "no delimiter within 1024 bytes");
                enc[n_enc] = value;
                n_enc = n_enc + 1;
            end
        end
    end

    initial begin
        wait (all_seen);
        $fclose(capture);
        if (led_toggles < 2) $fatal(1, "LED toggled %0d times", led_toggles);
        $display("PASS: %0d link messages: STATUS %0d, BEST %0d, CHAN_FRAME %0d ok/%0d bad, METRICS %0d, LINK %0d, SPECTRUM %0d, IQ %0d",
                 messages, count[8'h01], count[8'h10], frame_ok, frame_bad, count[8'h20], count[8'h21],
                 count[8'h30], count[8'h31]);
        $finish;
    end

    initial begin
        #40_000_000;
        $fatal(1, "link test timed out after %0d messages", messages);
    end
endmodule
