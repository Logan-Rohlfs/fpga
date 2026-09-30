`timescale 1ns/1ps
module receiver_control_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst=1,uart_rx=1,command_ready=0;
    wire command_valid,enable;
    wire [7:0] cmd_seq;
    wire [31:0] carrier_ftw,nco_ftw,rejected_count,dropped_count;
    receiver_control #(.CLK_HZ(4000000),.BAUD_RATE(1000000),.INTERBYTE_TIMEOUT_CYCLES(100)) dut(.*);
    reg [7:0] bytes[0:14];
    integer j;
    reg [15:0] check_crc;
    function [15:0] crc_bitwise(input [15:0] old,input [7:0] b);
      reg [15:0] c;integer k;
      begin
        c=old;
        for(k=7;k>=0;k=k-1) c={c[14:0],1'b0} ^ ((c[15]^b[k]) ? 16'h1021 : 16'd0);
        crc_bitwise=c;
      end
    endfunction
    task send_byte(input [7:0] b,input reg stop_bit);
      integer k;
      begin
        uart_rx=0;repeat(4) @(negedge clk);
        for(k=0;k<8;k=k+1) begin uart_rx=b[k];repeat(4) @(negedge clk);end
        uart_rx=stop_bit;repeat(4) @(negedge clk);
      end
    endtask
    task packet(input [7:0] seq,input [7:0] ena,input [7:0] version,input reg corrupt);
      begin
        bytes[0]=8'h53;bytes[1]=8'h52;bytes[2]=version;bytes[3]=seq;
        bytes[4]=8'h78;bytes[5]=8'h56;bytes[6]=8'h34;bytes[7]=8'h12;
        bytes[8]=8'hef;bytes[9]=8'hcd;bytes[10]=8'hab;bytes[11]=8'h89;bytes[12]=ena;
        check_crc=16'hffff;
        for(j=0;j<13;j=j+1) check_crc=crc_bitwise(check_crc,bytes[j]);
        // Golden Python receiver_control.command(7,12345678,89abcdef,True).
        if(seq==7 && ena==1 && version==1 && check_crc!=16'h6b1b) $fatal(1,"golden CRC mismatch");
        bytes[13]=check_crc[7:0];bytes[14]=check_crc[15:8] ^ corrupt;
        for(j=0;j<15;j=j+1) send_byte(bytes[j],1);
        repeat(8) @(negedge clk);
      end
    endtask
    task consume;
      begin command_ready=1;@(negedge clk);command_ready=0;if(command_valid)$fatal(1,"handshake failed");end
    endtask
    initial begin
      repeat(3) @(negedge clk);rst=0;
      send_byte(8'h99,1);send_byte(8'h53,1); // overlapping S S R resync
      packet(7,1,1,0);
      if(!command_valid || cmd_seq!=7 || carrier_ftw!=32'h12345678 || nco_ftw!=32'h89abcdef || !enable)
        $fatal(1,"golden command mismatch");
      packet(8,0,1,0);
      if(dropped_count!=1 || cmd_seq!=7 || !enable) $fatal(1,"stalled command overwritten");
      consume();
      packet(8,0,1,0);
      if(!command_valid || cmd_seq!=8 || enable) $fatal(1,"disable command failed");
      consume();
      packet(9,1,1,1);packet(9,2,1,0);packet(9,1,2,0);packet(255,1,1,0);
      if(command_valid || rejected_count!=4) $fatal(1,"invalid commands accepted or miscounted %0d",rejected_count);
      send_byte(8'h53,1);send_byte(8'h52,1);send_byte(1,1);
      repeat(110) @(negedge clk);
      if(command_valid || rejected_count!=5) $fatal(1,"truncated command timeout failed");
      packet(10,1,1,0);
      if(!command_valid || cmd_seq!=10) $fatal(1,"timeout recovery failed");consume();
      // A bad stop bit aborts reception and is never applied.
      send_byte(8'h53,0);uart_rx=1;repeat(110) @(negedge clk);
      if(command_valid || rejected_count<6) $fatal(1,"framing error ignored");
      packet(11,1,1,0);
      if(!command_valid || cmd_seq!=11) $fatal(1,"framing error recovery failed");consume();
      send_byte(8'h53,1);send_byte(8'h52,1);
      rst=1;repeat(3) @(negedge clk);rst=0;
      if(command_valid || rejected_count || dropped_count) $fatal(1,"reset failed");
      packet(12,1,1,0);
      if(!command_valid || cmd_seq!=12) $fatal(1,"post-reset receive failed");
      $display("PASS receiver_control: UART4clocks/bit, golden wire command, CRC/version/enable/sequence rejection, truncation, stalls, reset and recovery");$finish;
    end
    initial begin #200000; $fatal(1,"control timeout");end
endmodule
