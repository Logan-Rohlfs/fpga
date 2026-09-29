`timescale 1ns/1ns

module blink_tb;
    reg clk = 0;
    wire led;

    // Small divider makes the same design fast to test in simulation.
    blink #(.HALF_PERIOD(4)) dut (.clk(clk), .led(led));

    always #5 clk = ~clk;

    initial begin
        $dumpfile("build/blink/blink.vcd");
        $dumpvars(0, blink_tb);

        if (led !== 1'b0) $fatal(1, "LED should start off");
        repeat (3) @(negedge clk);
        if (led !== 1'b0) $fatal(1, "LED toggled too early");
        @(negedge clk);
        if (led !== 1'b1) $fatal(1, "LED did not turn on after four cycles");
        repeat (4) @(negedge clk);
        if (led !== 1'b0) $fatal(1, "LED did not turn off after eight cycles");

        $display("PASS: LED toggles every four clocks");
        $finish;
    end
endmodule

