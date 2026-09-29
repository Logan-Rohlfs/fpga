# SDR starter

This project is intentionally empty. Add `rtl/sdr_top.sv` with a module named `sdr_top`, then assign each top-level port in `constraints/basys3.xdc`. Add simulation tests under `sim/` and a Python board client under `host/` as the design takes shape.

Start by deciding how samples enter and leave the FPGA. The onboard USB-UART is useful for commands and small captured blocks; continuous SDR sample streams need a higher-throughput interface.

