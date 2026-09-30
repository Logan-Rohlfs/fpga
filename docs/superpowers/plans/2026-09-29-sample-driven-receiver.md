# End-to-end SDR work plan

Primary agent coordinates contracts, integration, review, and acceptance.
Implementation agents own separate files and report concise interface/results.

- [x] ADC-only synthetic input with independent Gaussian reference vectors
- [x] DDC, channel filtering, discriminator and symbol timing
- [x] Configurable synchronization, frame assembly and CRC
- [x] Independent sample-to-frame integration tests
- [x] Real sample-derived spectrum, I/Q, metrics and transport
- [x] Default board integration and applied tuning behavior (simulation verified)
- [ ] Regression and independent review
- [ ] Vivado and attached-board/GUI verification
- [ ] Documentation and explicit remaining limitations

See [contract](../specs/2026-09-29-sample-driven-receiver.md).
