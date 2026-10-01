`timescale 1ns/1ps
module adc_signal_source_tb;
    reg clk=0,rst=1,enable=1;
    always #5 clk=~clk;
    reg [31:0] carrier_ftw=32'd429496730;
    wire sample_valid;
    wire signed [11:0] sample_a,sample_b;
    adc_signal_source #(.CLK_HZ(4000000),.AMPLITUDE_A(1400),.AMPLITUDE_B(1400),
        .NOISE_A(0),.NOISE_B(0),.DELAY_B_SAMPLES(3)) dut(.*);
    integer count=0,cycles=0,last_cycle=0,peak=0,active_samples=0,idle_samples=0,fd;
    reg signed [11:0] history[0:2];
    integer i,disabled_samples;
    initial begin
        for(i=0;i<3;i=i+1) history[i]=0;
        fd=$fopen("build/sdr/adc_source.hex","w");
        if(!fd) $fatal(1,"Cannot write ADC source capture");
        repeat(4) @(negedge clk);
        rst=0;
        while(count<100000) begin
            @(negedge clk);
            cycles=cycles+1;
            if(sample_valid) begin
                if(count && cycles-last_cycle!=4) $fatal(1,"Sample cadence");
                last_cycle=cycles;
                if(^sample_a === 1'bx || ^sample_b === 1'bx) $fatal(1,"Unknown sample");
                if(sample_b!==history[2]) $fatal(1,"Antenna delay at sample %0d",count);
                history[2]=history[1];history[1]=history[0];history[0]=sample_a;
                if(sample_a>peak) peak=sample_a;
                if(count%50000>100 && count%50000<24000 && sample_a!=0) active_samples=active_samples+1;
                if(count%50000>25100) begin
                    if(sample_a!=0) $fatal(1,"Carrier leaked into packet guard at %0d",count);
                    idle_samples=idle_samples+1;
                end
                $fdisplay(fd,"%03x",sample_a);
                count=count+1;
            end
        end
        $fclose(fd);
        if(peak<1300 || active_samples<40000 || idle_samples<45000) $fatal(1,"Missing/modulation amplitude");
        enable=0;
        repeat(5) @(negedge clk);
        disabled_samples=0;
        repeat(32) begin
            @(negedge clk);
            if(sample_valid) disabled_samples=disabled_samples+1;
        end
        if(sample_a || sample_b) $fatal(1,"Disabled transmitter not quiet");
        if(disabled_samples!=8) $fatal(1,"Disabled transmitter stopped ADC cadence");
        carrier_ftw=-32'd429496730;
        enable=1;
        repeat(800) @(negedge clk);
        if(dut.phase===32'd0) $fatal(1,"Negative IF not running");
        $display("PASS adc_signal_source: 100000 samples, cadence, amplitude, antenna delay, idle, disable, negative IF");
        $finish;
    end
endmodule
