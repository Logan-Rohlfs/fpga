`timescale 1ns/1ps
// End-to-end ADC transmitter off/on; receiver and observers continue sampling.
module receiver_signal_loss_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst=1,adc_enable=1;
    wire [10:0] req,grant,p_valid,p_ready;
    wire [87:0] p_type,p_flags,p_data;
    wire [175:0] p_len;
    wire [7:0] out_data,sent_type;
    wire out_valid,out_last,sent_pulse;
    receiver_link_sources #(.CLK_HZ(4000000),.TICK_CYCLES(2000),.STATUS_TICKS(200)) dut(
        .clk(clk),.rst(rst),.cfg_reset(1'b0),.pause(1'b0),.carrier_ftw(32'd429496730),.nco_step(32'd429496730),
        .adc_enable(adc_enable),.req(req),.p_type(p_type),.p_flags(p_flags),.p_len(p_len),
        .grant(grant),.p_data(p_data),.p_valid(p_valid),.p_ready(p_ready));
    link_tx #(.N(11)) framer(.clk(clk),.rst(rst),.req(req),.p_type(p_type),.p_flags(p_flags),.p_len(p_len),
        .grant(grant),.p_data(p_data),.p_valid(p_valid),.p_ready(p_ready),.out_data(out_data),
        .out_valid(out_valid),.out_last(out_last),.out_ready(1'b1),.sent_type(sent_type),.sent_pulse(sent_pulse));
    integer best_count=0,start_count;
    integer initial_power=-1200,quiet_power;
    always @(posedge clk) if(!rst) begin
        if(sent_pulse && sent_type==8'h10) best_count=best_count+1;
        if(adc_enable && dut.channel[0].observation_valid && $signed(dut.channel[0].power_dbfs)>initial_power)
            initial_power=$signed(dut.channel[0].power_dbfs);
    end
    initial begin
        repeat(5) @(negedge clk);rst=0;
        wait(best_count>=2);
        @(negedge clk);adc_enable=0;
        // Allow an already completed frame/record to drain before silence assertions.
        repeat(80000) @(negedge clk);
        start_count=best_count;
        repeat(400000) @(negedge clk);
        quiet_power=$signed(dut.channel[0].power_dbfs);
        if(best_count!=start_count) $fatal(1,"Noise-only ADC fabricated BEST frames");
        if(dut.channel[0].signal_present) $fatal(1,"Noise-only ADC signal gate remains active");
        if(quiet_power>=initial_power-200) $fatal(1,"Power failed to fall signal=%0d quiet=%0d",initial_power,quiet_power);
        adc_enable=1;
        wait(best_count>=start_count+2);
        $display("PASS receiver_signal_loss: silence stops BEST, power falls %0d -> %0d dBFSx10, reacquires two frames",initial_power,quiet_power);
        $finish;
    end
    initial begin #20000000;$fatal(1,"Signal loss/recovery timeout");end
endmodule
