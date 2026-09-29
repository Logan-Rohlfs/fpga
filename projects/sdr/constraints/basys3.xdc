# Basys 3 pin template. Uncomment only ports that exist in sdr_top.sv.
# Source: https://github.com/Digilent/digilent-xdc/blob/master/Basys-3-Master.xdc

# 100 MHz clock
# set_property -dict { PACKAGE_PIN W5 IOSTANDARD LVCMOS33 } [get_ports clk]
# create_clock -name sys_clk -period 10.000 [get_ports clk]

# LED 0
# set_property -dict { PACKAGE_PIN U16 IOSTANDARD LVCMOS33 } [get_ports led]

# USB-UART: from host and to host
# set_property -dict { PACKAGE_PIN B18 IOSTANDARD LVCMOS33 } [get_ports uart_rx]
# set_property -dict { PACKAGE_PIN A18 IOSTANDARD LVCMOS33 } [get_ports uart_tx]

# Add further pins from Digilent's master XDC as hardware is chosen.

