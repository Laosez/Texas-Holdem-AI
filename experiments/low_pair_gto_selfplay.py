#!/usr/bin/env python3
"""GTO V1 small pocket pairs vs the SAME GTO V1, HU and 3-way.

Controls: fixed hero preflop 2.5BB open and opponent calls, shared physical
deals and identical initial policy RNG across baseline/corrected/defense/probe.
Not GTO solver equilibrium. Production code is not touched.
"""
from experiments import low_pair_gto_variants as study

study.SCENARIOS = {
    "HU_GTO_selfplay": [
        study.opponent("builtin:pc_gto_80bb", "9", "gto"),
    ],
    "Threeway_GTO_selfplay": [
        study.opponent("builtin:pc_gto_80bb", "9", "gto"),
        study.opponent("builtin:pc_gto_80bb", "4", "gto"),
    ],
}

if __name__ == "__main__":
    study.main()
