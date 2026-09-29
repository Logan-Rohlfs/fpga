`timescale 1ns/1ps

module sdr_top_tb;
    localparam integer BIT_NS = 40; // 4 clocks at 10 ns per clock.
    reg clk = 0;
    reg btnC = 1;
    wire uart_tx;
    wire led;
    integer frame;
    integer index;
    reg [7:0] received;

    always #5 clk = ~clk;

    sdr_top #(.CLK_HZ(100), .BAUD_RATE(25), .HEARTBEAT_CYCLES(8)) dut (
        .clk(clk), .btnC(btnC), .uart_tx(uart_tx), .led(led)
    );

    function [7:0] expected_byte(input integer n);
        case (n)
            0: expected_byte = "S";
            1: expected_byte = "D";
            2: expected_byte = "R";
            3: expected_byte = " ";
            4: expected_byte = "R";
            5: expected_byte = "E";
            6: expected_byte = "A";
            7: expected_byte = "D";
            8: expected_byte = "Y";
            9: expected_byte = 8'h0d;
            10: expected_byte = 8'h0a;
            default: expected_byte = 8'h00;
        endcase
    endfunction

    task automatic read_byte(output [7:0] value);
        integer bit_num;
        begin
            value = 0;
            @(negedge uart_tx);
            #(BIT_NS / 2);
            if (uart_tx !== 0) $fatal(1, "Bad start bit");
            for (bit_num = 0; bit_num < 8; bit_num = bit_num + 1) begin
                #(BIT_NS);
                value[bit_num] = uart_tx;
            end
            #(BIT_NS);
            if (uart_tx !== 1) $fatal(1, "Bad stop bit");
        end
    endtask

    initial begin
        $dumpfile("build/sdr/sdr_top.vcd");
        $dumpvars(0, sdr_top_tb);
        repeat (3) @(posedge clk);
        @(negedge clk);
        btnC = 0;

        for (frame = 0; frame < 2; frame = frame + 1) begin
            for (index = 0; index < 11; index = index + 1) begin
                read_byte(received);
                if (received !== expected_byte(index))
                    $fatal(1, "Frame %0d byte %0d: expected %02x, got %02x", frame, index, expected_byte(index), received);
            end
            wait (led === ((frame + 1) % 2));
        end

        $display("PASS: two complete SDR READY messages and LED heartbeat");
        $finish;
    end

    initial begin
        #100000;
        $fatal(1, "Top-level UART test timed out");
    end
endmodule
