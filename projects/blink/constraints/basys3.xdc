# Digilent Basys 3 master XDC: 100 MHz oscillator and LED 0.
set_property -dict { PACKAGE_PIN W5 IOSTANDARD LVCMOS33 } [get_ports clk]
create_clock -name sys_clk -period 10.000 [get_ports clk]
set_property -dict { PACKAGE_PIN U16 IOSTANDARD LVCMOS33 } [get_ports led]

