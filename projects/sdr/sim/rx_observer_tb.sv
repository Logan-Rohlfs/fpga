`timescale 1ns/1ps
module rx_observer_tb;
    reg clk=0; always #5 clk=~clk;
    reg rst=1,iq_valid=0,trigger=0,ready=0;
    reg signed [15:0] iq_i=0,iq_q=0;
    wire valid,busy;
    reg [31:0] t_us=0;
    wire [31:0] capture_t_us;
    reg [31:0] expected_t_us;
    always @(posedge clk)t_us<=t_us+1;
    wire [511:0] spectrum;
    wire [2047:0] iq;
    wire signed [15:0] power_dbfs_x10,noise_dbfs_x10,snr_db_x10;
    wire [31:0] dropped_count;
    rx_observer dut(.*);
    reg [2047:0] expected_iq;
    reg [511:0] saved_spectrum;
    integer n,k,peak,peak_value,value;
    task capture(input integer tone,input integer amplitude);
      begin
        @(negedge clk); trigger=1;
        @(negedge clk); trigger=0;
        expected_iq=0;expected_t_us=t_us;
        for(n=0;n<64;n=n+1) begin
          iq_i=$rtoi(amplitude*$cos(6.283185307179586*tone*n/64.0));
          iq_q=$rtoi(amplitude*$sin(6.283185307179586*tone*n/64.0));
          expected_iq[32*n +: 32]={iq_q,iq_i};
          iq_valid=1;@(negedge clk);
        end
        iq_valid=0;
        wait(valid);@(negedge clk);
        if(capture_t_us!==expected_t_us)$fatal(1,"capture timestamp not first sample");
        if(iq!==expected_iq) $fatal(1,"IQ snapshot changed samples");
      end
    endtask
    task check_tone(input integer expected_bin);
      begin
        peak=-1;peak_value=-1;
        for(k=0;k<64;k=k+1) begin
          value=spectrum[8*k +: 8];
          if(value>peak_value) begin peak_value=value;peak=k;end
        end
        if(peak!=expected_bin || peak_value<226 || peak_value>229)
          $fatal(1,"tone bin/scaling mismatch bin %0d power %0d",peak,peak_value);
        if(power_dbfs_x10 < -64 || power_dbfs_x10 > -58)
          $fatal(1,"time power scaling incorrect %0d",power_dbfs_x10);
      end
    endtask
    task consume;
      begin
        ready=1;@(negedge clk);ready=0;
        if(valid || busy) $fatal(1,"result did not clear");
      end
    endtask
    initial begin
      repeat(3) @(negedge clk);rst=0;
      capture(8,8192);check_tone(40);
      if(noise_dbfs_x10>-600 || snr_db_x10<500) $fatal(1,"inband pure tone contaminated noise estimator");
      saved_spectrum=spectrum;
      // Results survive arbitrary input and triggers while blocked.
      trigger=1;repeat(3) @(negedge clk);trigger=0;
      iq_valid=1;iq_i=123;repeat(5) @(negedge clk);iq_valid=0;
      if(!valid || spectrum!==saved_spectrum || iq!==expected_iq || dropped_count!=3)
        $fatal(1,"stalled output or busy-trigger accounting failed");
      consume();
      capture(-8,8192);check_tone(24);consume();
      capture(0,0);
      if(spectrum!==512'd0 || power_dbfs_x10!=-1200 || noise_dbfs_x10!=-1200 || snr_db_x10!=0)
        $fatal(1,"zero sample floor incorrect power %0d noise %0d",power_dbfs_x10,noise_dbfs_x10);
      consume();
      capture(24,8192);check_tone(56);
      if(noise_dbfs_x10<power_dbfs_x10+45 || snr_db_x10!=0)
        $fatal(1,"outer-bin integrated noise estimate incorrect");
      // Reset clears held data and accounting.
      rst=1;repeat(2) @(negedge clk);rst=0;
      if(valid || busy || dropped_count || spectrum || iq) $fatal(1,"reset failed");
      $display("PASS rx_observer: positive/negative tone bins, dBFS scaling, zero floor, noise estimate, IQ capture and output stalls");$finish;
    end
    initial begin #1000000; $fatal(1,"observer timeout");end
endmodule
