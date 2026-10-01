`timescale 1ns/1ps
// Bit-level APEX FLIGHT framing: 16-bit sync 2DD4, type-implied 44-byte frame,
// seq u16 LE at byte 7, CRC16 over type+body. A wrong type byte must release the
// decoder at once so an immediately following frame is still caught.
module flight_decoder_tb;
    localparam integer FRAME_BYTES=44;
    reg clk=0; always #5 clk=~clk;
    reg rst=1, bit_valid=0, bit_in=0;
    wire frame_valid, frame_complete, frame_crc_ok, locked;
    wire [FRAME_BYTES*8-1:0] frame_data;
    wire [7:0] frame_len, frame_type;
    wire [15:0] frame_seq;
    wire [31:0] sync_count, good_count, bad_count, dropped_count, timeout_count;
    rx_frame_decoder #(.FRAME_BYTES(FRAME_BYTES),.SYNC_WORD(32'h00002dd4),.SYNC_BITS(16),
        .SEQ_OFFSET(7),.SEQ_BYTES(2),.SEQ_LITTLE_ENDIAN(1),.TYPE_FILTER(1),.FRAME_TYPE(8'h02),
        .BIT_TIMEOUT_CYCLES(1000)) dut(
        .clk(clk),.rst(rst),.bit_valid(bit_valid),.bit_in(bit_in),.frame_valid(frame_valid),
        .frame_ready(1'b1),.frame_complete(frame_complete),.frame_data(frame_data),.frame_len(frame_len),
        .frame_type(frame_type),.frame_seq(frame_seq),.frame_crc_ok(frame_crc_ok),.sync_count(sync_count),
        .good_count(good_count),.bad_count(bad_count),.dropped_count(dropped_count),
        .timeout_count(timeout_count),.locked(locked));

    reg [7:0] rom[0:1230*42-1];
    reg [7:0] frame[0:FRAME_BYTES-1];
    integer completes=0, last_seq=-1, last_ok=0, i;

    function automatic [15:0] crc_step(input [15:0] c, input [7:0] d);
        integer b;
        begin
            c=c^{d,8'h00};
            for(b=0;b<8;b=b+1) c=c[15] ? ((c<<1)^16'h1021) : (c<<1);
            crc_step=c;
        end
    endfunction
    task send_bit(input b);
        begin @(negedge clk); bit_in=b; bit_valid=1; @(negedge clk); bit_valid=0; end
    endtask
    task send_byte(input [7:0] v);
        integer k;
        begin for(k=7;k>=0;k=k-1) send_bit(v[k]); end
    endtask
    task preamble_sync;
        integer k;
        begin
            for(k=0;k<8;k=k+1) send_byte(8'haa);
            send_byte(8'h2d); send_byte(8'hd4);
        end
    endtask
    // ROM frame n (type+body) plus big-endian CRC; corrupt flips a CRC bit.
    task send_rom_frame(input integer n, input corrupt);
        integer k;
        reg [15:0] c;
        begin
            c=16'hffff;
            for(k=0;k<42;k=k+1) begin frame[k]=rom[n*42+k]; c=crc_step(c,frame[k]); end
            frame[42]=c[15:8]; frame[43]=c[7:0]^corrupt;
            for(k=0;k<FRAME_BYTES;k=k+1) send_byte(frame[k]);
        end
    endtask
    always @(posedge clk) if(frame_complete) begin
        completes=completes+1;
        last_seq=frame_seq; last_ok=frame_crc_ok;
        if(frame_len!=FRAME_BYTES || frame_type!=8'h02) $fatal(1,"FLIGHT length/type wrong");
    end
    task expect_frame(input integer n, input ok);
        integer k;
        begin
            repeat(4) @(negedge clk);
            if(last_seq!=n || last_ok!=ok) $fatal(1,"frame %0d: seq=%0d crc_ok=%0d",n,last_seq,last_ok);
            for(k=0;k<FRAME_BYTES;k=k+1)
                if(frame_data[8*k +: 8]!==frame[k]) $fatal(1,"frame %0d byte %0d differs",n,k);
        end
    endtask

    initial begin
        $readmemh("projects/sdr/rom/apex_flight.mem", rom);
        repeat(4) @(negedge clk); rst=0;
        preamble_sync; send_rom_frame(0,0); expect_frame(0,1);
        preamble_sync; send_rom_frame(150,1); expect_frame(150,0);
        // A sync with an unknown type byte (HK 0x03 here) is dropped after the
        // type byte; the next frame follows with no idle gap and still decodes.
        preamble_sync; send_byte(8'h03);
        repeat(2) @(negedge clk);
        if(locked) $fatal(1,"decoder stayed locked after a non-FLIGHT type byte");
        preamble_sync; send_rom_frame(1229,0); expect_frame(1229,1);
        if(completes!=3 || good_count!=2 || bad_count!=1 || sync_count!=4 || dropped_count!=0)
            $fatal(1,"counters completes=%0d good=%0d bad=%0d sync=%0d",completes,good_count,bad_count,sync_count);
        $display("PASS flight_decoder: 16-bit sync, 44-byte FLIGHT frames exact, CRC fail counted, foreign type released");
        $finish;
    end
endmodule
