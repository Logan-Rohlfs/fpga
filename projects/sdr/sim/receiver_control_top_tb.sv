`timescale 1ns/1ps
// Full-duplex control acceptance: real ADC->receiver->UART data continues across
// configuration, with an on-wire acknowledgment as the old/new sample barrier.
module receiver_control_top_tb;
    reg clk=0;always #5 clk=~clk;
    reg btnC=0,uart_rx=1;
    wire uart_tx,led;
    sdr_top #(.CLK_HZ(4000000),.BAUD_RATE(1000000),.TICK_CYCLES(20000),.STATUS_TICKS(20)) dut(.*);
    reg [7:0] enc[0:1023],msg[0:1023],command_bytes[0:14];
    integer capture;
    integer n_enc=0,n_msg,messages=0,expected_seq=-1,best_count=0,metrics_count=0,applies=0;
    integer acknowledgments[0:255];
    reg [31:0] ack_carrier[0:255],ack_nco[0:255];
    reg ack_enable[0:255];
    reg [31:0] current_nco=429496730;
    reg disabled=0;
    reg pre_drained,pre_ready;
    function automatic [15:0] crc_step(input [15:0] c,input [7:0] d);
      integer b;
      begin
        c=c^{d,8'd0};
        for(b=0;b<8;b=b+1)c=c[15]?(c<<1)^16'h1021:c<<1;
        crc_step=c;
      end
    endfunction
    function automatic [31:0] get_word(input integer offset);
      get_word={msg[offset+3],msg[offset+2],msg[offset+1],msg[offset]};
    endfunction
    task automatic handle_message;
      integer i,k,code,len,seq;
      reg [15:0] c;
      reg signed [63:0] axis;
      begin
        n_msg=0;i=0;
        while(i<n_enc) begin
          code=enc[i];
          if(code==0 || i+code>n_enc)$fatal(1,"torn COBS during tuning");
          for(k=1;k<code;k=k+1)begin msg[n_msg]=enc[i+k];n_msg=n_msg+1;end
          i=i+code;
          if(code<255 && i<n_enc)begin msg[n_msg]=0;n_msg=n_msg+1;end
        end
        len={msg[4],msg[3]};
        if(n_msg<7 || n_msg!=len+7)$fatal(1,"torn length during tuning");
        c=16'hffff;
        for(i=0;i<n_msg-2;i=i+1)c=crc_step(c,msg[i]);
        if(c!={msg[n_msg-1],msg[n_msg-2]})$fatal(1,"torn CRC during tuning");
        if(expected_seq>=0 && msg[2]!=expected_seq[7:0])$fatal(1,"link sequence reset/gap during tuning");
        expected_seq=(msg[2]+1)%256;messages=messages+1;
        if(msg[0]==1 && {msg[16],msg[15]}!==16'd0)$fatal(1,"STATUS drops during control acceptance");
        if(msg[0]==2)begin
          if(len!=11 || msg[6]!=0)$fatal(1,"invalid CONFIG acknowledgment");
          seq=msg[5];acknowledgments[seq]=acknowledgments[seq]+1;
          ack_carrier[seq]=get_word(7);ack_nco[seq]=get_word(11);ack_enable[seq]=msg[15];
          if(seq!=255)begin
            if(ack_carrier[seq]!==dut.receiver.applied_carrier || ack_nco[seq]!==dut.receiver.applied_nco || ack_enable[seq]!==dut.receiver.applied_enable)
              $fatal(1,"ACK did not report applied words");
            current_nco=ack_nco[seq];disabled=!ack_enable[seq];
          end
        end
        if(msg[0]==8'h10)begin
          if(disabled)$fatal(1,"old BEST crossed disabled ACK barrier");
          c=16'hffff;
          for(i=11;i<28;i=i+1)c=crc_step(c,msg[i]);
          if(c!={msg[28],msg[29]})$fatal(1,"BEST bad APEX CRC");
          best_count=best_count+1;
        end
        if(msg[0]==8'h11 && disabled)$fatal(1,"old channel frame crossed disabled ACK barrier");
        if(msg[0]==8'h20)metrics_count=metrics_count+1;
        if(msg[0]==8'h30)begin
          axis=$signed(current_nco)*64'sd1000000;
          if(get_word(15)!=(axis>>>32))$fatal(1,"old spectrum reference crossed ACK barrier");
        end
      end
    endtask
    task automatic read_byte(output reg [7:0] value);
      integer b;
      begin
        @(negedge uart_tx);#20;
        if(uart_tx!==0)$fatal(1,"bad UART start");
        for(b=0;b<8;b=b+1)begin #40;value[b]=uart_tx;end
        #40;if(uart_tx!==1)$fatal(1,"bad UART stop during tuning");
      end
    endtask
    task automatic write_byte(input [7:0] value);
      integer b;
      begin
        uart_rx=0;repeat(4)@(negedge clk);
        for(b=0;b<8;b=b+1)begin uart_rx=value[b];repeat(4)@(negedge clk);end
        uart_rx=1;repeat(4)@(negedge clk);
      end
    endtask
    task automatic command(input [7:0] seq,input [31:0] carrier,input [31:0] nco,input reg enable,input reg corrupt);
      integer j;reg [15:0] c;
      begin
        @(negedge clk);
        command_bytes[0]=8'h53;command_bytes[1]=8'h52;command_bytes[2]=1;command_bytes[3]=seq;
        for(j=0;j<4;j=j+1)begin command_bytes[4+j]=carrier[8*j+:8];command_bytes[8+j]=nco[8*j+:8];end
        command_bytes[12]=enable;c=16'hffff;
        for(j=0;j<13;j=j+1)c=crc_step(c,command_bytes[j]);
        command_bytes[13]=c[7:0];command_bytes[14]=c[15:8]^corrupt;
        for(j=0;j<15;j=j+1)write_byte(command_bytes[j]);
      end
    endtask
    always @(posedge clk)begin
      pre_drained=dut.receiver.drained;pre_ready=dut.receiver.command_ready;
      #1;
      if(!dut.rst && dut.receiver.cfg_reset)begin
        if(!pre_drained || !pre_ready)$fatal(1,"configuration applied before transport drained");
        applies=applies+1;
      end
    end
    initial begin:monitor
      reg [7:0] value;
      capture=$fopen("build/sdr/receiver_control_capture.bin","wb");
      for(integer t=0;t<256;t=t+1)acknowledgments[t]=0;
      forever begin
        read_byte(value);
        if(^value===1'bx)$fatal(1,"Unknown byte on receiver UART");
        $fwrite(capture,"%c",value);
        if(value==0)begin handle_message();n_enc=0;end
        else begin
          if(n_enc>=1024)$fatal(1,"no delimiter");enc[n_enc]=value;n_enc=n_enc+1;
        end
      end
    end
    initial begin:test
      integer before_best,before_metrics;
      wait(acknowledgments[255]>0 && best_count>=1);
      // Start while a long observation is queued, forcing a real drain.
      wait(dut.req[10] || dut.req[11]);
      before_best=best_count;
      command(7,32'd536870912,32'd536870912,1,0); // matched retune to 125 kHz
      wait(acknowledgments[7]==1);
      if(ack_carrier[7]!=536870912 || ack_nco[7]!=536870912 || !ack_enable[7])$fatal(1,"retune ACK mismatch");
      wait(best_count>before_best+1);
      command(9,32'h12345678,32'habcdef12,0,1);
      repeat(5000)@(negedge clk);
      if(acknowledgments[9] || dut.receiver.applied_carrier!=536870912 || dut.receiver.applied_nco!=536870912 || !dut.receiver.applied_enable)
        $fatal(1,"corrupt command altered tuning");
      command(8,32'd536870912,32'd536870912,0,0);
      wait(acknowledgments[8]==1);
      before_best=best_count;before_metrics=metrics_count;
      repeat(500000)@(negedge clk);
      if(best_count!=before_best || metrics_count<before_metrics+2)$fatal(1,"disabled source froze measurements or decoded phantom frames");
      command(10,32'd429496730,32'd429496730,1,0);
      wait(acknowledgments[10]==1);
      wait(best_count>before_best);
      if(applies!=3)$fatal(1,"expected three atomic applies, got %0d",applies);
      $fclose(capture);
      $display("PASS receiver_control_top: %0d clean UART messages, retune/reacquire, corrupt rejection, disabled live metrics, ACK barrier, uninterrupted link sequence",messages);$finish;
    end
    initial begin #40000000;$fatal(1,"control top timeout: messages %0d best %0d",messages,best_count);end
endmodule
