PROJECT ?= blink
BIT := build/$(PROJECT)/$(PROJECT).bit
SDR_RTL := $(sort $(wildcard projects/sdr/rtl/*.sv))
# Unit testbenches first, then the full top-level link test.
SDR_TESTS := uart_tx_tb crc16_ccitt_tb cobs_encoder_tb link_tx_tb source_combiner_tb sdr_top_tb

.PHONY: sim build program flash clean

sim:
	@mkdir -p build/$(PROJECT)
	@if [ "$(PROJECT)" = blink ]; then \
		iverilog -g2012 -s blink_tb -o build/blink/sim.vvp projects/blink/rtl/blink.sv projects/blink/sim/blink_tb.sv && \
		vvp build/blink/sim.vvp; \
	elif [ "$(PROJECT)" = sdr ]; then \
		for tb in $(SDR_TESTS); do \
			iverilog -g2012 -Wall -s $$tb -o build/sdr/$$tb.vvp $(SDR_RTL) projects/sdr/sim/$$tb.sv && \
			vvp -n build/sdr/$$tb.vvp || exit 1; \
		done; \
		PYTHONPATH=tools python3 -m sdr_cli.protocol --check build/sdr/link_capture.bin; \
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
