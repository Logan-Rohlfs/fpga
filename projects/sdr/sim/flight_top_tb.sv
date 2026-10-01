`timescale 1ns/1ps
// Demo bitstream end to end: sdr_top DEMO_FLIGHT=1 -> UART line bytes written to
// build/sdr/flight_capture.bin for the host checks (protocol --check and
// check_receiver.py --demo --rom). The replay starts at slot 59 (simulation only)
// so the capture holds frame 59 from both antennas and frame 60, where antenna
// A is in its loss window and BEST must come from B.
module flight_top_tb;
    localparam integer CLK_HZ = 5_000_000;       // 5 clocks per bit at 1 Mbaud
    localparam integer BIT_NS = 50;              // 10 ns clock period in simulation
    reg clk = 0;
    always #5 clk = ~clk;
    wire uart_tx, led;
    // 10 ms ticks: the 10-tick SPECTRUM period also covers a 256-point capture plus DFT.
    sdr_top #(.CLK_HZ(CLK_HZ), .BAUD_RATE(1_000_000), .TICK_CYCLES(40_000), .STATUS_TICKS(10),
              .DEMO_FLIGHT(1)) dut (
        .clk(clk), .btnC(1'b0), .uart_rx(1'b1), .uart_tx(uart_tx), .led(led)
    );
    defparam dut.receiver.sources.adc.START_SLOT = 59;

    integer capture, bytes = 0, best = 0;
    always @(posedge clk) if (dut.sent_pulse && dut.sent_type == 8'h10) best = best + 1;

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

    initial begin : monitor
        reg [7:0] value;
        capture = $fopen("build/sdr/flight_capture.bin", "wb");
        forever begin
            read_byte(value);
            if (^value === 1'bx) $fatal(1, "Unknown UART byte");
            $fwrite(capture, "%c", value);
            bytes = bytes + 1;
        end
    end

    initial begin
        wait (best >= 2);
        // Let the UART finish the queued records before closing the capture.
        repeat (100_000) @(posedge clk);
        if (dut.receiver.sources.from_b < 1) $fatal(1, "A's loss window was not covered by B");
        $fclose(capture);
        $display("PASS flight_top: demo sdr_top sent %0d UART bytes, %0d BEST (from A %0d, from B %0d)",
                 bytes, best, dut.receiver.sources.from_a, dut.receiver.sources.from_b);
        $finish;
    end
    initial begin #40_000_000; $fatal(1, "flight_top timeout"); end
endmodule
