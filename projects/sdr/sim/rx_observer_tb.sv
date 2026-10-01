`timescale 1ns/1ps
// One observer length: hand-built tone/stall/reset checks plus an independent
// floating-point DFT reference block (generate_dft_vectors.py).
module rx_observer_check #(parameter integer POINTS=64,parameter VECTOR="")(output reg done);
    localparam integer S=POINTS/64,LOG2N=$clog2(POINTS);
    localparam integer READ=POINTS>256 ? POINTS : 256;
    reg clk=0; always #5 clk=~clk;
    reg rst=1,iq_valid=0,trigger=0,ready=0;
    reg signed [15:0] iq_i=0,iq_q=0;
    wire valid,busy;
    reg [31:0] t_us=0;
    wire [31:0] capture_t_us;
    reg [31:0] expected_t_us;
    always @(posedge clk)t_us<=t_us+1;
    // Reconstructed from the observer's registered byte read ports.
    reg [8*POINTS-1:0] spectrum;
    reg [2047:0] iq;
    reg [LOG2N-1:0] spectrum_addr=0;
    reg [7:0] iq_addr=0;
    wire [7:0] spectrum_data,iq_data;
    wire signed [15:0] power_dbfs_x10,noise_dbfs_x10,snr_db_x10;
    wire [31:0] dropped_count;
    rx_observer #(.POINTS(POINTS)) dut(.*);
    reg [2047:0] expected_iq;
    reg [8*POINTS-1:0] saved_spectrum;
    reg [31:0] vector[0:2*POINTS+1];
    integer n,k,peak,peak_value,value,expected,difference,worst_strong,worst_weak;
    initial done=0;
    task read_results;
      begin
        for(k=0;k<READ;k=k+1) begin
          spectrum_addr=k[LOG2N-1:0];iq_addr=k[7:0];@(negedge clk);
          if(k<POINTS) spectrum[8*k +: 8]=spectrum_data;
          if(k<256) iq[8*k +: 8]=iq_data;
        end
      end
    endtask
    // tone<0 replays the reference vector's samples instead of a test tone.
    task capture(input integer tone,input integer amplitude);
      begin
        @(negedge clk); trigger=1;
        @(negedge clk); trigger=0;
        expected_iq=0;expected_t_us=t_us;
        for(n=0;n<POINTS;n=n+1) begin
          if(amplitude<0) {iq_q,iq_i}=vector[n];
          else begin
            iq_i=$rtoi(amplitude*$cos(6.283185307179586*tone*n/POINTS));
            iq_q=$rtoi(amplitude*$sin(6.283185307179586*tone*n/POINTS));
          end
          if(n<64) expected_iq[32*n +: 32]={iq_q,iq_i};
          iq_valid=1;@(negedge clk);
        end
        iq_valid=0;
        wait(valid);@(negedge clk);read_results();
        if(capture_t_us!==expected_t_us)$fatal(1,"%0d-point capture timestamp not first sample",POINTS);
        if(iq!==expected_iq) $fatal(1,"%0d-point IQ snapshot changed the first 64 samples",POINTS);
      end
    endtask
    task check_tone(input integer expected_bin);
      begin
        peak=-1;peak_value=-1;
        for(k=0;k<POINTS;k=k+1) begin
          value=spectrum[8*k +: 8];
          if(value>peak_value) begin peak_value=value;peak=k;end
        end
        if(peak!=expected_bin || peak_value<226 || peak_value>229)
          $fatal(1,"%0d-point tone bin/scaling mismatch bin %0d power %0d",POINTS,peak,peak_value);
        if(power_dbfs_x10 < -64 || power_dbfs_x10 > -58)
          $fatal(1,"%0d-point time power scaling incorrect %0d",POINTS,power_dbfs_x10);
      end
    endtask
    // Tolerances: the coarse log is within ~0.4 dB and quantizes to 0.5 dB
    // steps (1 byte each side); truncating normalization adds error to weak
    // bins, so bins below -60 dBFS (byte 120) may differ by 3 bytes (1.5 dB).
    task check_reference;
      begin
        worst_strong=0;worst_weak=0;
        for(k=0;k<POINTS;k=k+1) begin
          value=spectrum[8*k +: 8];expected=vector[POINTS+k];
          difference=value>expected ? value-expected : expected-value;
          if(expected>=120 && difference>worst_strong) worst_strong=difference;
          if(expected<120 && difference>worst_weak) worst_weak=difference;
          if(difference>(expected>=120 ? 1 : 3))
            $fatal(1,"%0d-point bin %0d byte %0d, float reference %0d",POINTS,k,value,expected);
        end
        expected=$signed(vector[2*POINTS][15:0]);
        if(power_dbfs_x10<expected-5 || power_dbfs_x10>expected+5)
          $fatal(1,"%0d-point power %0d, float reference %0d",POINTS,power_dbfs_x10,expected);
        value=$signed(vector[2*POINTS+1][15:0]);
        if(noise_dbfs_x10<value-5 || noise_dbfs_x10>value+5)
          $fatal(1,"%0d-point noise %0d, float reference %0d",POINTS,noise_dbfs_x10,value);
        if(snr_db_x10!=(power_dbfs_x10>noise_dbfs_x10 ? power_dbfs_x10-noise_dbfs_x10 : 0))
          $fatal(1,"%0d-point SNR inconsistent",POINTS);
        $display("%0d-point vs float DFT: worst byte error %0d (>= -60 dBFS), %0d (weaker); power %0d/%0d, noise %0d/%0d dBFS x10",
          POINTS,worst_strong,worst_weak,power_dbfs_x10,expected,noise_dbfs_x10,value);
      end
    endtask
    task consume;
      begin
        ready=1;@(negedge clk);ready=0;
        if(valid || busy) $fatal(1,"%0d-point result did not clear",POINTS);
      end
    endtask
    initial begin
      $readmemh(VECTOR,vector);
      repeat(3) @(negedge clk);rst=0;
      capture(8*S,8192);check_tone(40*S);
      if(noise_dbfs_x10>-600 || snr_db_x10<500) $fatal(1,"%0d-point inband pure tone contaminated noise estimator",POINTS);
      saved_spectrum=spectrum;
      // Results survive arbitrary input and triggers while blocked.
      trigger=1;repeat(3) @(negedge clk);trigger=0;
      iq_valid=1;iq_i=123;repeat(5) @(negedge clk);iq_valid=0;read_results();
      if(!valid || spectrum!==saved_spectrum || iq!==expected_iq || dropped_count!=3)
        $fatal(1,"%0d-point stalled output or busy-trigger accounting failed",POINTS);
      consume();
      capture(-8*S,8192);check_tone(24*S);consume();
      capture(0,0);
      if(spectrum!=0 || power_dbfs_x10!=-1200 || noise_dbfs_x10!=-1200 || snr_db_x10!=0)
        $fatal(1,"%0d-point zero sample floor incorrect power %0d noise %0d",POINTS,power_dbfs_x10,noise_dbfs_x10);
      consume();
      capture(24*S,8192);check_tone(56*S);
      if(noise_dbfs_x10<power_dbfs_x10+45 || snr_db_x10!=0)
        $fatal(1,"%0d-point outer-bin integrated noise estimate incorrect",POINTS);
      consume();
      capture(0,-1);check_reference();
      // Reset clears held data and accounting.
      rst=1;repeat(2) @(negedge clk);rst=0;read_results();
      if(valid || busy || dropped_count || spectrum || iq) $fatal(1,"%0d-point reset failed",POINTS);
      done=1;
    end
endmodule

module rx_observer_tb;
    wire done_64,done_128,done_256;
    rx_observer_check #(.POINTS(64),.VECTOR("projects/sdr/sim/vectors/dft_64.hex")) points_64(.done(done_64));
    rx_observer_check #(.POINTS(128),.VECTOR("projects/sdr/sim/vectors/dft_128.hex")) points_128(.done(done_128));
    rx_observer_check #(.POINTS(256),.VECTOR("projects/sdr/sim/vectors/dft_256.hex")) points_256(.done(done_256));
    initial begin
      wait(done_64 && done_128 && done_256);
      $display("PASS rx_observer (64, 128 and 256 points): tone bins, dBFS scaling, zero floor, noise estimate, float DFT reference, IQ capture and output stalls");$finish;
    end
    initial begin #30000000; $fatal(1,"observer timeout");end
endmodule
