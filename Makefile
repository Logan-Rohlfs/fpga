PROJECT ?= blink
BIT := build/$(PROJECT)/$(PROJECT).bit

.PHONY: sim build program flash clean

sim:
	@test "$(PROJECT)" = blink || (echo "No simulation target yet for $(PROJECT)"; exit 1)
	@mkdir -p build/blink
	iverilog -g2012 -s blink_tb -o build/blink/sim.vvp projects/blink/rtl/blink.sv projects/blink/sim/blink_tb.sv
	vvp build/blink/sim.vvp

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

