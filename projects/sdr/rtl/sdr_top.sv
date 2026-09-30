`timescale 1ns/1ps
// SDR board top: real receiver processing synthetic ADC-boundary samples.
//
// ADC sample source -> receiver/observations -> link_tx -> COBS -> UART.
// Synthetic provenance follows the ADC source even though downstream logic is real.
// LED0 toggles each time a STATUS message is sent (about once per second).
// btnC resets the design; a short power-on reset also runs after configuration.
module sdr_top #(
    parameter integer CLK_HZ = 100_000_000,
    parameter integer BAUD_RATE = 1_000_000,
    parameter integer TICK_CYCLES = CLK_HZ / 100,
    parameter integer STATUS_TICKS = 100,
    parameter [31:0] BUILD_ID = 32'h53445231,
    parameter integer LEGACY_LINK_TEST=0,
    parameter [31:0] ADC_CARRIER_FTW=32'd429496730,
    parameter [31:0] RX_NCO_FTW=32'd429496730,
    parameter integer ADC_ENABLE=1
) (
    input  wire clk,
    input  wire btnC,
    input  wire uart_rx,
    output wire uart_tx,
    output reg  led = 1'b0
);
    localparam integer N = LEGACY_LINK_TEST ? 11 : 12;
    localparam [7:0] T_STATUS = 8'h01;

    reg [1:0] btn_sync = 2'b00;
    reg [3:0] por = 0;
    wire rst = (por != 4'hf) || btn_sync[1];

    always @(posedge clk) begin
        btn_sync <= {btn_sync[0], btnC};
        if (por != 4'hf) por <= por + 1'b1;
    end

    wire [N-1:0] req, grant, p_valid, p_ready;
    wire [8*N-1:0] p_type, p_flags, p_data;
    wire [16*N-1:0] p_len;
    wire [7:0] msg_data, sent_type, enc_data;
    wire msg_valid, msg_last, msg_ready, sent_pulse, enc_valid, enc_ready;

    generate if(LEGACY_LINK_TEST) begin: legacy
    link_test_sources #(
        .CLK_HZ(CLK_HZ), .TICK_CYCLES(TICK_CYCLES), .STATUS_TICKS(STATUS_TICKS), .BUILD_ID(BUILD_ID), .N(N)
    ) sources (
        .clk(clk), .rst(rst), .req(req), .p_type(p_type), .p_flags(p_flags), .p_len(p_len),
        .grant(grant), .p_data(p_data), .p_valid(p_valid), .p_ready(p_ready)
    );
    end else begin: receiver
        localparam RUN=0,DRAIN=1,ACK=2;
        reg [1:0] control_state;
        wire command_valid,command_ready;
        wire [7:0] cmd_seq;
        wire [31:0] requested_carrier,requested_nco;
        wire requested_enable;
        wire [31:0] rejected_commands,dropped_commands;
        reg [31:0] applied_carrier,applied_nco;
        reg applied_enable,cfg_reset;
        wire quiesce=command_valid || control_state!=RUN;
        // req drops only after the final producer byte. The framer still emits
        // CRC until msg_valid drops; msg_ready then proves COBS has drained, and
        // enc_ready proves even the final UART delimiter's stop bit has ended.
        wire drained=(req==0) && (grant==0) && !msg_valid && msg_ready && !enc_valid && enc_ready;
        assign command_ready=control_state==DRAIN && drained;
        receiver_control #(.CLK_HZ(CLK_HZ),.BAUD_RATE(BAUD_RATE)) control(
            .clk(clk),.rst(rst),.uart_rx(uart_rx),.command_valid(command_valid),.command_ready(command_ready),
            .cmd_seq(cmd_seq),.carrier_ftw(requested_carrier),.nco_ftw(requested_nco),.enable(requested_enable),
            .rejected_count(rejected_commands),.dropped_count(dropped_commands));
        receiver_link_sources #(.CLK_HZ(CLK_HZ),.TICK_CYCLES(TICK_CYCLES),
            .STATUS_TICKS(STATUS_TICKS),.BUILD_ID(BUILD_ID),.N(11)) sources(
            .clk(clk),.rst(rst),.cfg_reset(cfg_reset),.pause(quiesce),.carrier_ftw(applied_carrier),.nco_step(applied_nco),
            .adc_enable(applied_enable),.req(req[N-1:1]),.p_type(p_type[8*N-1:8]),.p_flags(p_flags[8*N-1:8]),.p_len(p_len[16*N-1:16]),
            .grant(grant[N-1:1]),.p_data(p_data[8*N-1:8]),.p_valid(p_valid[N-1:1]),.p_ready(p_ready[N-1:1]));
        reg report_pending;
        reg [7:0] report_sequence;
        reg [31:0] report_timer;
        reg [87:0] config_payload;
        wire config_accept;
        wire [15:0] config_index;
        wire config_trigger=report_pending && !req[0] && (control_state==ACK || (control_state==RUN && !command_valid));
        wire [7:0] config_byte=config_payload[config_index*8 +: 8];
        link_msg_port #(.LATENCY(3)) config_port(
            .clk(clk),.rst(rst),.trigger(config_trigger),.len(16'd11),.byte_in(config_byte),
            .grant(grant[0]),.ready(p_ready[0]),.req(req[0]),.idx(config_index),
            .data(p_data[7:0]),.valid(p_valid[0]),.accept(config_accept));
        assign p_type[7:0]=8'h02;
        assign p_flags[7:0]=8'h01;
        assign p_len[15:0]=16'd11;
        always @(posedge clk) begin
            if(rst) begin
                applied_carrier<=ADC_CARRIER_FTW;applied_nco<=RX_NCO_FTW;applied_enable<=ADC_ENABLE!=0;
                cfg_reset<=0;control_state<=RUN;report_pending<=1;report_sequence<=255;report_timer<=0;
                config_payload<=0;
            end else begin
                cfg_reset<=0;
                if(config_accept) begin
                    config_payload<={7'd0,applied_enable,applied_nco,applied_carrier,8'd0,report_sequence};
                    report_pending<=0;
                end
                if(report_timer==TICK_CYCLES*STATUS_TICKS-1) begin
                    report_timer<=0;
                    if(!report_pending && !req[0] && control_state==RUN && !command_valid) begin
                        report_pending<=1;report_sequence<=255;
                    end
                end else report_timer<=report_timer+1'b1;
                case(control_state)
                    RUN: if(command_valid) control_state<=DRAIN;
                    DRAIN: if(drained && command_valid) begin
                        applied_carrier<=requested_carrier;applied_nco<=requested_nco;applied_enable<=requested_enable;
                        cfg_reset<=1;report_pending<=1;report_sequence<=cmd_seq;control_state<=ACK;
                    end
                    ACK: if(config_accept) control_state<=RUN;
                    default: control_state<=RUN;
                endcase
            end
        end
    end endgenerate

    link_tx #(.N(N)) framer (
        .clk(clk), .rst(rst), .req(req), .p_type(p_type), .p_flags(p_flags), .p_len(p_len), .grant(grant),
        .p_data(p_data), .p_valid(p_valid), .p_ready(p_ready), .out_data(msg_data), .out_valid(msg_valid),
        .out_last(msg_last), .out_ready(msg_ready), .sent_type(sent_type), .sent_pulse(sent_pulse)
    );

    cobs_encoder #(.DEPTH(1024)) encoder (
        .clk(clk), .rst(rst), .in_data(msg_data), .in_valid(msg_valid), .in_last(msg_last), .in_ready(msg_ready),
        .out_data(enc_data), .out_valid(enc_valid), .out_ready(enc_ready)
    );

    uart_tx #(.CLK_HZ(CLK_HZ), .BAUD_RATE(BAUD_RATE)) transmitter (
        .clk(clk), .rst(rst), .data(enc_data), .valid(enc_valid), .ready(enc_ready), .tx(uart_tx)
    );

    always @(posedge clk) begin
        if (rst) led <= 1'b0;
        else if (sent_pulse && sent_type == T_STATUS) led <= ~led;
    end
endmodule
