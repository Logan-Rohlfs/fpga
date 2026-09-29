`timescale 1ns/1ps

module uart_tx_tb;
    localparam integer BIT_NS = 80; // 8 clocks at 10 ns per clock.
    reg clk = 0;
    reg rst = 1;
    reg [7:0] data = 0;
    reg valid = 0;
    wire ready;
    wire tx;

    always #5 clk = ~clk;

    uart_tx #(.CLK_HZ(100), .BAUD_RATE(12)) dut (
        .clk(clk), .rst(rst), .data(data), .valid(valid), .ready(ready), .tx(tx)
    );

    task automatic transmit_and_check(input [7:0] expected);
        integer bit_num;
        begin
            wait (ready);
            @(negedge clk);
            data = expected;
            valid = 1;
            fork
                begin
                    @(posedge clk);
                    @(negedge clk);
                    valid = 0;
                end
                begin
                    @(negedge tx);
                    #(BIT_NS / 2);
                    if (tx !== 0 || ready !== 0)
                        $fatal(1, "Bad UART start bit or ready state");
                    for (bit_num = 0; bit_num < 8; bit_num = bit_num + 1) begin
                        #(BIT_NS);
                        if (tx !== expected[bit_num])
                            $fatal(1, "Byte %02x bit %0d: expected %b, got %b", expected, bit_num, expected[bit_num], tx);
                    end
                    #(BIT_NS);
                    if (tx !== 1)
                        $fatal(1, "Missing UART stop bit for %02x", expected);
                end
            join
        end
    endtask

    initial begin
        $dumpfile("build/sdr/uart_tx.vcd");
        $dumpvars(0, uart_tx_tb);
        repeat (3) @(posedge clk);
        @(negedge clk);
        rst = 0;

        transmit_and_check(8'h00);
        transmit_and_check(8'ha5);
        transmit_and_check(8'hff);

        // Reset while a character is underway; the line must return idle.
        wait (ready);
        @(negedge clk);
        data = 8'h55;
        valid = 1;
        @(posedge clk);
        @(negedge clk);
        valid = 0;
        repeat (9) @(posedge clk);
        @(negedge clk);
        rst = 1;
        if (tx !== 1 || ready !== 0)
            $fatal(1, "Reset did not return UART to idle");
        @(negedge clk);
        rst = 0;
        #1;
        if (ready !== 1)
            $fatal(1, "UART did not become ready after reset");

        $display("PASS: UART frames 00, A5, FF and resets cleanly");
        $finish;
    end

    initial begin
        #100000;
        $fatal(1, "UART test timed out");
    end
endmodule
