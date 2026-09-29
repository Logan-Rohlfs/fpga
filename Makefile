PROJECT ?= blink
BIT := build/$(PROJECT)/$(PROJECT).bit

.PHONY: sim build program flash clean

sim:
	@mkdir -p build/$(PROJECT)
	@if [ "$(PROJECT)" = blink ]; then \
		iverilog -g2012 -s blink_tb -o build/blink/sim.vvp projects/blink/rtl/blink.sv projects/blink/sim/blink_tb.sv && \
		vvp build/blink/sim.vvp; \
	elif [ "$(PROJECT)" = sdr ]; then \
		iverilog -g2012 -Wall -s uart_tx_tb -o build/sdr/uart_tx_tb.vvp projects/sdr/rtl/uart_tx.sv projects/sdr/sim/uart_tx_tb.sv && \
		vvp build/sdr/uart_tx_tb.vvp && \
		iverilog -g2012 -Wall -s sdr_top_tb -o build/sdr/sdr_top_tb.vvp projects/sdr/rtl/uart_tx.sv projects/sdr/rtl/sdr_top.sv projects/sdr/sim/sdr_top_tb.sv && \
		vvp build/sdr/sdr_top_tb.vvp; \
	else echo "Unknown project: $(PROJECT)"; exit 1; fi

build:
	vivado -mode batch -source scripts/build.tcl -tclargs $(PROJECT)

program:
	@test -f "$(BIT)" || (echo "Missing $(BIT). Build in Vivado first."; exit 1)
	openFPGALoader -b basys3 "$(BIT)"

flash:
	@test -f "$(BIT)" || (echo "Missing $(BIT). Build in Vivado first."; exit 1)
	openFPGALoader -b basys3 -f "$(BIT)"

clean:
	rm -rf build
