`timescale 1ns/1ps
// Host-link message framer with fixed-priority arbitration (port 0 highest).
//
// Producer port i: hold req[i] with a stable type/flags/len header until the
// message completes. grant[i] rises for the whole message; supply exactly len
// payload bytes on p_valid/p_ready, then drop req after the final accepted byte.
// Arbitration happens only between messages, so messages are never interleaved.
//
// Output (unencoded, to cobs_encoder): type, flags, seq, len[7:0], len[15:8],
// payload, crc[7:0], crc[15:8]; out_last marks the final CRC byte.
// CRC-16-CCITT (init 0xFFFF) covers the header and payload. seq increments per message.
module link_tx #(
    parameter integer N = 2
) (
    input  wire          clk,
    input  wire          rst,
    input  wire [N-1:0]  req,
    input  wire [8*N-1:0] p_type,
    input  wire [8*N-1:0] p_flags,
    input  wire [16*N-1:0] p_len,
    output reg  [N-1:0]  grant = 0,
    input  wire [8*N-1:0] p_data,
    input  wire [N-1:0]  p_valid,
    output wire [N-1:0]  p_ready,
    output reg  [7:0]    out_data,
    output reg           out_valid,
    output wire          out_last,
    input  wire          out_ready,
    output reg  [7:0]    sent_type = 0,
    output reg           sent_pulse = 0
);
    localparam integer SW = (N <= 1) ? 1 : $clog2(N);
    localparam [2:0] IDLE = 0, HEADER = 1, PAYLOAD = 2, CRC_LO = 3, CRC_HI = 4;

    reg [2:0] state = IDLE;
    reg [SW-1:0] sel = 0;
    reg [7:0] m_type = 0, m_flags = 0, seq = 0;
    reg [15:0] m_len = 0, count = 0;
    reg [2:0] hidx = 0;
    reg [15:0] crc = 16'hffff;
    wire [15:0] crc_next;

    crc16_ccitt crc_step (.crc(crc), .data(out_data), .next(crc_next));

    integer i;
    reg found;
    reg [SW-1:0] winner;
    always @* begin
        found = 1'b0;
        winner = 0;
        for (i = N - 1; i >= 0; i = i - 1)
            if (req[i]) begin
                found = 1'b1;
                winner = i[SW-1:0];
            end
    end

    wire fire = out_valid && out_ready;
    assign out_last = (state == CRC_HI);
    assign p_ready = (state == PAYLOAD) ? (out_ready << sel) : {N{1'b0}};

    always @* begin
        out_valid = 1'b0;
        out_data = 8'h00;
        case (state)
            HEADER: begin
                out_valid = 1'b1;
                case (hidx)
                    0: out_data = m_type;
                    1: out_data = m_flags;
                    2: out_data = seq;
                    3: out_data = m_len[7:0];
                    default: out_data = m_len[15:8];
                endcase
            end
            PAYLOAD: begin
                out_valid = p_valid[sel];
                out_data = p_data[8*sel +: 8];
            end
            CRC_LO: begin
                out_valid = 1'b1;
                out_data = crc[7:0];
            end
            CRC_HI: begin
                out_valid = 1'b1;
                out_data = crc[15:8];
            end
            default: ;
        endcase
    end

    always @(posedge clk) begin
        sent_pulse <= 1'b0;
        if (rst) begin
            state <= IDLE;
            grant <= 0;
            seq <= 0;
        end else begin
            case (state)
                IDLE: if (found) begin
                    sel <= winner;
                    m_type <= p_type[8*winner +: 8];
                    m_flags <= p_flags[8*winner +: 8];
                    m_len <= p_len[16*winner +: 16];
                    grant <= {{(N-1){1'b0}}, 1'b1} << winner;
                    crc <= 16'hffff;
                    hidx <= 0;
                    count <= 0;
                    state <= HEADER;
                end
                HEADER: if (fire) begin
                    crc <= crc_next;
                    hidx <= hidx + 1'b1;
                    if (hidx == 4) state <= (m_len == 0) ? CRC_LO : PAYLOAD;
                end
                PAYLOAD: if (fire) begin
                    crc <= crc_next;
                    count <= count + 1'b1;
                    if (count == m_len - 1) begin
                        grant <= 0;
                        state <= CRC_LO;
                    end
                end
                CRC_LO: if (fire) state <= CRC_HI;
                CRC_HI: if (fire) begin
                    grant <= 0;
                    seq <= seq + 1'b1;
                    sent_type <= m_type;
                    sent_pulse <= 1'b1;
                    state <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
