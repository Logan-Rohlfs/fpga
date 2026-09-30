`timescale 1ns/1ps
module rx_channel_tb;
    reg clk=0; always #5 clk=~clk;
    reg rst=1, sample_valid=0;
    reg signed [11:0] sample_data=0;
    reg [31:0] nco_step=32'd429496730;
    wire iq_valid,bit_valid,bit_data,signal_present;
    wire signed [15:0] iq_i,iq_q;
    wire signed [31:0] discriminator,frequency_offset_hz;
    wire [15:0] magnitude;
    wire [7:0] quality;
    rx_channel dut(.*);
    real phase=0.0, frequency=100000.0;
    integer random_state=32'h516187, samples, iq_count=0,bits=0,match_count=0;
    reg [63:0] received=0;
    localparam [63:0] PAYLOAD=64'hD391A65CF00F827D;
    always @(posedge clk) begin
        #1;
        if(!rst) begin
            if(iq_valid) iq_count=iq_count+1;
            if(bit_valid) begin
                bits=bits+1;
                received={received[62:0],bit_data};
                if(received==PAYLOAD) match_count=match_count+1;
            end
        end
    end
    task reset;
        begin
            @(negedge clk); rst=1; sample_valid=0;
            repeat(5) @(negedge clk);
            rst=0; phase=0; frequency=100000; received=0;
        end
    endtask
    task adc;
        input real target;
        input integer amplitude;
        input integer noisy;
        integer noise;
        begin
            @(negedge clk);
            random_state=(random_state*1664525)+1013904223;
            noise=noisy ? ((random_state>>16)&31)-16 : 0;
            // Independent real-valued oscillator and gradual frequency shaping.
            frequency=frequency+0.18*(target-frequency);
            sample_data=$rtoi(amplitude*$cos(phase))+noise;
            phase=phase+6.283185307179586*frequency/1000000.0;
            if(phase>6.283185307179586) phase=phase-6.283185307179586;
            sample_valid=1;
        end
    endtask
    task packet;
        input real center;
        input integer amplitude;
        input integer symbol_samples;
        integer b,s,old_match_count;
        reg value;
        begin
            old_match_count=match_count;
            for(b=0;b<160;b=b+1) begin
                if(b<64) value=b&1;
                else if(b<128) value=PAYLOAD[127-b];
                else value=b&1;
                for(s=0;s<symbol_samples;s=s+1)
                    adc(center+(value ? 20000.0 : -20000.0),amplitude,1);
            end
            if(match_count!=old_match_count+1) $fatal(1,"payload recovery failed center=%f amplitude=%d symbol_samples=%d match_count=%d",center,amplitude,symbol_samples,match_count-old_match_count);
        end
    endtask
    integer old_iq,old_bits;
    initial begin
        reset;
        old_iq=iq_count;
        for(samples=0;samples<2000;samples=samples+1) adc(120000,1200,0);
        @(negedge clk); sample_valid=0;
        repeat(6) @(negedge clk);
        if(iq_count-old_iq!=200) $fatal(1,"decimation count mismatch %d",iq_count-old_iq);
        if(discriminator<=0 || !signal_present || magnitude<1000) $fatal(1,"positive tone metrics wrong");
        for(samples=0;samples<2000;samples=samples+1) adc(80000,1200,0);
        repeat(6) @(negedge clk);
        if(discriminator>=0) $fatal(1,"negative tone polarity wrong");
        reset; packet(100000,1200,100);
        reset; packet(102000,250,101);
        reset; packet(98000,900,99);
        reset; nco_step=32'd558345748; packet(130000,1100,100);
        // Dropout clears timing confidence and stops bit production.
        for(samples=0;samples<1000;samples=samples+1) adc(130000,0,0);
        old_bits=bits;
        for(samples=0;samples<1000;samples=samples+1) adc(130000,0,0);
        if(signal_present || quality!=0 || bits!=old_bits) $fatal(1,"silence produced bits/confidence");
        @(negedge clk); sample_valid=0;
        repeat(10) @(negedge clk);
        old_iq=iq_count;
        repeat(50) @(negedge clk);
        if(iq_count!=old_iq) $fatal(1,"output without input strobe");
        $display("rx_channel_tb PASS: four shaped/noisy packet recoveries, frequency/rate/amplitude changes, silence and decimation");
        $finish;
    end
    initial begin #10000000; $fatal(1,"timeout"); end
endmodule
