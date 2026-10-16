# Pocket pairs 22–66: GTO V1 error audit and paired-hand A/B experiment

Date: 2026-10-16. **Experiment only, production code untouched.**

## Baseline error

In `bots/postflop_profiles.py/read_hand`, a pocket pair on a paired board
receives evaluator category `2` (two pair). Because `paired_hole=True` and
the board is only singly paired, the current rule often returns
`made="monster"` even with `55` on `A-A-9`. This triggers **80% bet**
and about **57% HU raise** despite vulnerable showdown strength.

The control intervention reclassifies *only* pocket `22–66` with evaluator
category two-pair and ≥1 board pair as `weak_pair`, retaining all other
GTO V1 frequencies. No edits to the current engine, shared evaluator, or
existing GTO v1 policy.

## A/B setup

- Existing `planner_postflop_ev._play_case` full betting engine and
  `_draw_case` range-weighted card samples.
- Five pocket classes × 650 identically dealt hands × 3 scenarios =
  **9,750 distinct sample scenarios** (each is replayed for each policy).
- Standardized hero preflop 2.5 BB open, fixed 20 BB stacks.
- HU TAG tight = `pc_gto_80bb` UTG with TAG V1 postflop.
- HU LAG wide = `any_two` UTG with LAG V1 postflop.
- Multiway = PC TAG UTG + Any Two LAG CO.
- Same physical hole cards and full boards for each variant; shared initial
  bot random seed; reported EV in BB per modeled opportunity.
- Per-class paired 95% CI half-width is typically 0.4–0.6 BB.
- NO ICM, solver, or genuine preflop strategic betting tree. Results are
  not cash-game or tournament performance guarantees.

## Corrected vs original GTO V1

Mean Δ EV (5 equally weighted hands):

| Scenario | Corrected | Bluffcatch | Probe |
| --- | ---: | ---: | ---: |
| HU TAG tight | **+1.6461** | +0.9056 | +1.6686 |
| HU LAG wide | +0.0538 | -0.0206 | +0.1234 |
| Multiway TAG+LAG | **+1.5215** | +0.6471 | +1.5169 |

The defensive **bluffcatch** variant raises the calling pot-odds ceiling
from 14% to 30% in HU paired-board cases. It performs **worse** than strict
correction against TAG and in multiway, and does not consistently help
against LAG. The **probe** variant additionally bets about 35% in eligible
HU checked-to paired-board two-pair spots and uses 24% call limit; its
marginal average gain over strict correction (~0.02–0.07 BB in HU) is much
smaller than the sample uncertainty and should not be over-interpreted.

Important exception: `66` versus HU LAG wide. Strict correction yields
Δ=-0.7031 BB (95% half-width 0.4165). Probe Δ=-0.6469 BB.
Over-simplistic passive play can discard profitable aggression and bluff
catching on *low paired boards*. A better next experiment should distinguish
`66` on `2-2-3` from `66` on `A-A-9`: board rank, relative pair
strength, range and opponent behavior matter.

## Per-hand corrected Δ EV (BB)

| Hand | HU TAG tight | HU LAG wide | Multiway TAG+LAG |
| --- | ---: | ---: | ---: |
| 22 | +1.6915 | +0.6592 | +1.9469 |
| 33 | +2.3092 | +0.2362 | +1.5969 |
| 44 | +1.5915 | +0.1554 | +1.5038 |
| 55 | +1.2962 | -0.0785 | +1.0923 |
| 66 | +1.3423 | -0.7031 | +1.4677 |

## Recommended outcome

1. Treat the mislabeling of pocket-pair two pair as a **verified
   classification error**; avoid changing GTO V1 without a version bump.
2. The conservative correction is a strong experimental GTO V2 candidate
   for TAG and multiway environments; keep V1 as control.
3. Do not universally raise bluffcatch calling thresholds. Optimize paired
   board relative rank and size by action/position/opponent first, then
   validate against independent seeds and deeper stacks (20/40/80 BB).
4. Keep the experiment **out of Railway production** until improvements are
   confirmed on holdout scenarios and preflop rollout assumptions refined.

GitHub Actions runs:
- [Strict correction vs baseline](https://github.com/Laosez/Texas-Holdem-AI/actions/runs/38837263009)
- [Strict, bluffcatch and probe variants](https://github.com/Laosez/Texas-Holdem-AI/actions/runs/38837538079)

## GTO V1 vs GTO V1 mirror opponent (additional holdout)

[GitHub Actions experiment](https://github.com/Laosez/Texas-Holdem-AI/actions/runs/38837938906). Run 2026-10-16, 1,200 independent physical deal scenarios per hand per match: 5 hands × 2 opposing lineups × 1,200 = **12,000 distinct deals**. Each deal is replayed under baseline, corrected, bluffcatch and probe hero, **opponents always remain unchanged GTO V1**. Preflop is the same scripted 2.5 BB BTN hero open and calls, 20 BB effective stack. This is a *best response to this bot*, not a solver Nash convergence test.

| Hand | HU GTO baseline EV | HU corrected Δ | HU bluffcatch Δ | HU probe Δ | 3-way GTO corrected Δ |
| --- | ---: | ---: | ---: | ---: | ---: |
| 22 | -2.2992 | +1.6442 | +0.8333 | +1.6575 | +2.1000 |
| 33 | -2.3775 | +1.8125 | +1.1979 | +1.8583 | +2.0888 |
| 44 | -2.2667 | +1.6550 | +0.9838 | +1.6358 | +2.2163 |
| 55 | -2.0758 | +1.6375 | +1.0783 | +1.5813 | +1.8458 |
| 66 | -1.6617 | +1.2658 | +0.8512 | +1.2767 | +1.7279 |
| **Mean (class equal-weight)** | — | **+1.6030** | +0.9889 | +1.6019 | **+1.9958** |

The 95% paired CI half-width for each corrected HU class is ~0.35–0.39 BB; for corrected three-way each ~0.44–0.47 BB. Therefore all individual corrected-vs-original paired tests are clearly positive in this fixed model. **However absolute corrected HU EV is still negative**, from -0.6550 to -0.3958 BB per standardized *forced-open* opportunity. These are NOT inferred recommendations to open these hands preflop at 20 BB.

### Opponent count implementation

`_opponents(view)` counts players in `view.opponents`, which are surviving players not in `folded`; includes all-ins. Therefore this updates on each betting decision. `multi = 1/(1 + .55*(n-1))`: HU 1.000, 2 opponents 0.645, 3 opponents 0.476, 4 opponents 0.377. Weak-pair no-bet frequencies fall from 9% to 5.81%, 4.29%, 3.40% respectively; top-pair no-bet frequencies 58% → 37.4%, 27.6%, 21.9%. Ordinary air/draw bluffs stop entirely above three opponents. **Monster no-bet frequency 80% does not adjust for n**, and neither do fixed one-pair pot-odds thresholds. Thus the pocket-pair/two-pair categorization bug is especially pronounced in multiway scenarios. No exact equity vs surviving ranges is calculated inside this heuristic bot.

**Production GTO V1 remains unchanged.** A genuine symmetric self-play test where *both* players simultaneously adopt the same policy cannot establish improved overall chip EV in zero-sum rake-free poker; this compares a changed hero against a fixed V1 reference. Next: board-relative strength buckets, independent seeds, 40/80 BB, villain range-conditioned thresholding.
