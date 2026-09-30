PROJECT ?= blink
BIT := build/$(PROJECT)/$(PROJECT).bit
SDR_RTL := $(sort $(wildcard projects/sdr/rtl/*.sv))
# Unit testbenches first, then the full top-level link test.
SDR_TESTS := uart_tx_tb crc16_ccitt_tb cobs_encoder_tb link_tx_tb source_combiner_tb adc_signal_source_tb rx_channel_tb rx_frame_decoder_tb rx_observer_tb receiver_control_tb rx_pipeline_tb sdr_top_tb receiver_top_tb receiver_signal_loss_tb receiver_control_top_tb

.PHONY: sim build program flash clean

sim:
	@mkdir -p build/$(PROJECT)
	@if [ "$(PROJECT)" = blink ]; then \
		iverilog -g2012 -s blink_tb -o build/blink/sim.vvp projects/blink/rtl/blink.sv projects/blink/sim/blink_tb.sv && \
		vvp build/blink/sim.vvp; \
	elif [ "$(PROJECT)" = sdr ]; then \
		python3 projects/sdr/sim/generate_adc_vectors.py build/sdr/adc_reference.hex --packets 2 && \
		python3 projects/sdr/sim/generate_adc_vectors.py build/sdr/adc_noisy.hex --packets 2 --noise 80 --cfo 2500 && \
		python3 projects/sdr/sim/generate_adc_vectors.py build/sdr/adc_bad.hex --packets 2 --corrupt || exit 1; \
		for tb in $(SDR_TESTS); do \
			iverilog -g2012 -Wall -s $$tb -o build/sdr/$$tb.vvp $(SDR_RTL) projects/sdr/sim/$$tb.sv && \
			vvp -n build/sdr/$$tb.vvp || exit 1; \
		done; \
		vvp -n build/sdr/rx_pipeline_tb.vvp +VECTOR=build/sdr/adc_noisy.hex && \
		vvp -n build/sdr/rx_pipeline_tb.vvp +VECTOR=build/sdr/adc_bad.hex +GOOD=0 +BAD=2 && \
		vvp -n build/sdr/rx_pipeline_tb.vvp +VECTOR=build/sdr/adc_source.hex && \
		vvp -n build/sdr/rx_pipeline_tb.vvp +STALL=1 && \
		PYTHONPATH=tools python3 -m sdr_cli.protocol --check build/sdr/link_capture.bin && \
		PYTHONPATH=tools python3 -m sdr_cli.protocol --check build/sdr/receiver_capture.bin && \
		python3 projects/sdr/host/check_receiver.py --file build/sdr/receiver_capture.bin && \
		python3 projects/sdr/host/check_receiver.py --file build/sdr/receiver_control_capture.bin; \
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
