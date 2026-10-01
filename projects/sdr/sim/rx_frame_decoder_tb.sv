`timescale 1ns/1ps
module rx_frame_decoder_case #(parameter integer VARIANT=0)(output reg done=0);
    reg clk=0; always #5 clk=~clk;
    reg rst=1, bit_valid=0, bit_in=0, frame_ready=0;
    wire frame_valid,frame_crc_ok,frame_complete,locked;
    wire [39:0] frame_data;
    wire [7:0] frame_len,frame_type;
    wire [15:0] frame_seq;
    wire [31:0] sync_count,good_count,bad_count,dropped_count,timeout_count;
    rx_frame_decoder #(.FRAME_BYTES(5),.BIT_TIMEOUT_CYCLES(12),
      .LSB_FIRST(VARIANT),.INVERT_BITS(VARIANT),.WHITEN_ENABLE(VARIANT)) dut(.*);
    reg [8:0] white;
    task send_bit(input reg b);
      begin
        @(negedge clk); bit_valid=1; bit_in=b ^ (VARIANT!=0);
        @(negedge clk); bit_valid=0;
      end
    endtask
    task send_sync;
      integer i; reg [31:0] sync;
      begin
        sync=32'hd391d391;
        for(i=31;i>=0;i=i-1) send_bit(sync[i]);
        white=9'h1ff;
      end
    endtask
    task send_byte(input reg [7:0] b);
      integer i; reg v;
      begin
        for(i=0;i<8;i=i+1) begin
          v=VARIANT ? b[i] : b[7-i];
          if(VARIANT) begin
            v=v^white[0];
            white=(white>>1) ^ (white[0] ? 9'h021 : 9'd0);
          end
          send_bit(v);
        end
      end
    endtask
    task packet(input reg corrupt);
      begin
        send_sync(); send_byte(1);send_byte(42);send_byte(165);
        // Independently generated binascii.crc_hqx([1,42,165],65535)=f7ce.
        send_byte(8'hf7);send_byte(corrupt ? 8'hcf : 8'hce);
        @(negedge clk);
      end
    endtask
    task consume;
      begin
        frame_ready=1; @(negedge clk); frame_ready=0;
        if(frame_valid) $fatal(1,"output failed handshake");
      end
    endtask
    initial begin
      repeat(3) @(negedge clk); rst=0;
      // Noise and partial sync cannot fabricate a packet.
      repeat(47) send_bit(0);
      if(frame_valid || sync_count) $fatal(1,"noise falsely synchronized");
      packet(0);
      if(!frame_valid || !frame_crc_ok || frame_data!==40'hcef7a52a01 ||
        frame_type!=1 || frame_seq!=42 || frame_len!=5 || good_count!=1)
        $fatal(1,"valid frame mismatch variant %0d data %h",VARIANT,frame_data);
      repeat(20) @(negedge clk);
      if(!frame_valid || frame_data!==40'hcef7a52a01) $fatal(1,"stalled output changed");
      // Full next frame is decoded and counted but cannot overwrite held output.
      packet(1);
      if(dropped_count!=1 || bad_count!=1 || !frame_crc_ok || frame_data!==40'hcef7a52a01)
        $fatal(1,"backpressure/drop accounting failed");
      consume();
      packet(1);
      if(!frame_valid || frame_crc_ok || frame_data!==40'hcff7a52a01 || bad_count!=2)
        $fatal(1,"corrupt packet not surfaced");
      consume();
      // Truncated frame times out, then hunt recovers without reset.
      send_sync();send_byte(1);send_bit(0);
      repeat(14) @(negedge clk);
      if(locked || timeout_count!=1 || frame_valid) $fatal(1,"timeout failed");
      packet(0);
      if(!frame_valid || !frame_crc_ok || good_count!=2 || sync_count!=5)
        $fatal(1,"resynchronization failed");
      consume();
      // Reset abandons partial capture and held output, and clears statistics.
      send_sync();send_byte(1);
      rst=1; repeat(2) @(negedge clk); rst=0;
      if(locked || frame_valid || good_count || bad_count || sync_count || dropped_count || timeout_count)
        $fatal(1,"reset failed");
      packet(0); consume();
      done=1;
    end
endmodule
module rx_frame_decoder_tb;
  wire a,b;
  rx_frame_decoder_case #(.VARIANT(0)) normal(a);
  rx_frame_decoder_case #(.VARIANT(1)) options(b);
  initial begin
    wait(a&&b); $display("PASS rx_frame_decoder: CRC, corruption, stalls, timeout, recovery, reset, inversion, bit order and whitening"); $finish;
  end
  initial begin #1000000; $fatal(1,"test timeout");end
endmodule
