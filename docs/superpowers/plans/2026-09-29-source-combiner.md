# Source combiner continuation plan

1. Audit the mapped next stage and current link interfaces (read-only subagent).
2. Specify the bounded configurable contract; preserve protocol/provenance.
3. Implement source_combiner RTL (implementation subagent) and independent
   self-checking bench/integration assertions (verification subagent).
4. Integrate the synthetic frame harness and counters (primary agent).
5. Run all simulations and host tests; review the implementation with a fresh
   subagent and resolve concrete findings.
6. Remote Vivado build, timing/DRC inspection, volatile program and hardware
   link check when available. Do not flash.
7. Update SDR README and HANDOFF with newly verified evidence and limitations.

Contract: [source combiner design](../specs/2026-09-29-source-combiner-design.md).
No DSP/RF constants or actual receiver timing are selected by this work.

Completed 2026-09-29. All seven steps are complete; fresh simulation, host,
Vivado timing/DRC and programmed-board evidence is in [HANDOFF](../../HANDOFF.md#source-combiner-implementation-status).
Actual frame decoder timing and radio settings remain undecided.
