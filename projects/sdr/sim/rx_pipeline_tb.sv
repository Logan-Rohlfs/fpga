`timescale 1ns/1ps
module rx_pipeline_tb;
    reg clk=0; always #5 clk=~clk;
    reg rst=1,sample_valid=0,sample_synthetic=1;
    reg signed [11:0] sample_data=0;
    reg [31:0] nco_step=32'd429496730,t_us=0;
    wire synthetic,iq_valid,bit_valid,bit_data,signal_present,frame_valid,frame_crc_ok,locked;
    wire signed [15:0] iq_i,iq_q;
    wire signed [31:0] discriminator,frequency_offset_hz,frame_frequency_offset_hz;
    wire [15:0] magnitude,frame_seq,frame_magnitude;
    wire [7:0] quality,frame_quality,frame_len,frame_type;
    wire [31:0] frame_t_us,sync_count,good_count,bad_count,dropped_count,timeout_count;
    wire [151:0] frame_data;
    reg frame_ready=1;
    rx_pipeline #(.BIT_TIMEOUT_CYCLES(20000)) dut(.*);
    reg [11:0] vector[0:199999];
    reg [1023:0] vector_file;
    integer vector_samples=100000,expected_good=2,expected_bad=0;
    integer sample_index,frame_count=0;
    reg corrupt=0;
    integer stall=0;
    reg held=0;
    reg [271:0] held_descriptor;
    wire [271:0] descriptor={frame_data,frame_t_us,frame_quality,frame_magnitude,frame_frequency_offset_hz,frame_seq,frame_len,frame_type};
    always @(posedge clk) begin
        if(rst || !frame_valid || frame_ready) held<=0;
        else begin
            if(held && descriptor!==held_descriptor) $fatal(1,"Held frame payload/metadata changed under backpressure");
            held<=1;held_descriptor<=descriptor;
        end
    end
    function [15:0] crc_byte;
        input [15:0] old_crc; input [7:0] value;
        reg [15:0] c; integer b;
        begin
            c=old_crc^{value,8'd0};
            for(b=0;b<8;b=b+1) c=c[15] ? (c<<1)^16'h1021 : c<<1;
            crc_byte=c;
        end
    endfunction
    function [151:0] expected_frame;
        input [7:0] seq;
        reg [151:0] f; reg [15:0] crc; integer b;
        begin
            f=0;f[7:0]=1;f[15:8]=seq;
            f[8*2+:120]="TSET OIDAR XEPA"; // low byte first: APEX RADIO TEST
            crc=16'hffff;
            for(b=0;b<17;b=b+1) crc=crc_byte(crc,f[8*b+:8]);
            f[8*17+:8]=crc[15:8];f[8*18+:8]=crc[7:0]^{7'd0,corrupt};
            expected_frame=f;
        end
    endfunction
    always @(posedge clk) begin
        if(!rst && frame_valid && frame_ready) begin
            if(frame_data!==expected_frame(frame_count))
                $fatal(1,"ADC recovered wrong payload: seq=%d bytes=%h expected=%h",frame_count,frame_data,expected_frame(frame_count));
            if(frame_len!=19 || frame_type!=1 || frame_seq!=frame_count || frame_crc_ok==corrupt || !synthetic)
                $fatal(1,"frame metadata mismatch");
            frame_count=frame_count+1;
        end
    end
    initial begin
        if(!$value$plusargs("VECTOR=%s",vector_file)) vector_file="build/sdr/adc_reference.hex";
        if($value$plusargs("SAMPLES=%d",vector_samples)) begin end
        if($value$plusargs("GOOD=%d",expected_good)) begin end
        if($value$plusargs("BAD=%d",expected_bad)) begin end
        corrupt=expected_bad!=0;
        if($value$plusargs("STALL=%d",stall)) begin end
        frame_ready=!stall;
        $readmemh(vector_file,vector,0,vector_samples-1);
        repeat(5) @(negedge clk); rst=0;
        for(sample_index=0;sample_index<vector_samples;sample_index=sample_index+1) begin
            @(negedge clk);sample_valid=1;sample_data=vector[sample_index];t_us=sample_index;
            if(stall && sample_index==90000) frame_ready=1;
        end
        @(negedge clk);sample_valid=0;
        repeat(100) @(negedge clk);
        if(good_count!=expected_good || bad_count!=expected_bad || dropped_count!=0 || frame_count!=expected_good+expected_bad)
            $fatal(1,"receiver counts good=%d bad=%d dropped=%d frames=%d sync=%d",good_count,bad_count,dropped_count,frame_count,sync_count);
        $display("rx_pipeline_tb PASS: %0d good/%0d bad exact frames recovered from %0d independent ADC samples",good_count,bad_count,vector_samples);
        $finish;
    end
endmodule
