# GTO Postflop V3 — Kxs / kicker / pair+draw experiment

**Date:** 2026-10-16. Versioned heuristic research policy; **not solver GTO**, no claim of superior EV. GTO V1 and V2 preserved. **V2 remains the default** after the A/B result.

## Changes

1. `K♠2♠` on `K♦-7♥-7♣` is **top pair plus shared board pair**, not an automatic value monster. True two pair `K2` on `K-2-7`, sets/trips, and full houses are untouched.
2. `K♠2♠` versus `K♠Q♠` on `K♦-9♥-4♣`: top-pair bet and defend thresholds now vary with hole kicker. These are **heuristic thresholds**, not solved equity.
3. `K♠2♠` on `K♦-7♠-4♠`: top pair + nine nominal flush outs now uses a dedicated combined pair-plus-draw continuation. Outs are **nominal**, not necessarily clean; multipots discounted.
4. Baseline multiway `M = 1/(1+0.55*(N-1))` retained. Original small pocket pair 22–66 V2 fix retained.

## Paired A/B

[GitHub Actions benchmark run](https://github.com/Laosez/Texas-Holdem-AI/actions/runs/38844313470) using [source](./kxs_v3_ab.py).

11 classes `K2s–KQs` × 3 opponent profiles × 450 random physical deals = **14,850 unique hand scenarios**. Every scenario is replayed once with GTO V2, once with experimental V3, *same hole cards and board* and seeded action RNG. 20BB effective stack, standardized BTN hero preflop open to 2.5BB, opponents call. Equity has NO betting-policy dependence. No ICM or preflop range optimization.

| Opponent | Equal-class mean Δ chip EV (V3−V2), BB/hand | Classes with improved EV | Classes with reduced EV |
| --- | ---: | ---: | ---: |
| GTO V2 | **−0.0171** | 4 | 7 |
| TAG | **+0.0061** | 8 | 3 |
| LAG | **−0.1510** | 2 | 9 |

All 33 hand-specific 95% paired confidence-interval half-widths are approximately 0.17–0.38 BB, so *most individual hand-level differences are inconclusive*. The LAG negative signal warrants a holdout with bigger samples rather than shipping V3 as a default replacement.

Example rows (model outcomes, not field EV):

| Hand | Opponent | V2 chip EV | V3 chip EV | Δ BB | 95% CI half-width |
| --- | --- | ---: | ---: | ---: | ---: |
| K2s | GTO | +0.2633 | +0.1678 | −0.0956 | 0.2300 |
| K2s | TAG | −0.3978 | −0.2922 | +0.1056 | 0.3751 |
| K2s | LAG | −0.4367 | −0.8300 | −0.3933 | 0.2979 |
| KQs | GTO | −0.0300 | +0.0811 | +0.1111 | 0.3362 |
| KQs | TAG | +0.3133 | +0.1400 | −0.1733 | 0.2671 |
| KQs | LAG | +0.4933 | +0.2267 | −0.2667 | 0.2593 |

## How to view on Plan

In **01 / Моя стратегия**, choose an A17/PC preflop range, then select `GTO V2` or `GTO V3 · эксперимент` as the **postflop line**. In 02, choose opponents' ranges and postflop profiles. Click **«Рассчитать Equity + Postflop EV»**, then switch the matrix metric to **«EV розыгрыша · BB»**. Repeat the run with the other postflop version, keeping all other variables fixed. The rollout deals are paired at fixed trial settings.

Changing V2 to V3 cannot change initial multiway **showdown equity** for the same opponents and ranges; it changes **behavioral EV**, showdown reach and fold-win frequency. This simulator does not automatically present a delta overlay: note the EV results before switching versions.

**Interpretation:** V3 is a distinct experimental alternative, NOT a claimed improvement or replacement of V2. Future calibration should condition kicker protection on opponent ranges and blind effective stacks, and test independent seeds including 40–80BB and genuine preflop lines.
