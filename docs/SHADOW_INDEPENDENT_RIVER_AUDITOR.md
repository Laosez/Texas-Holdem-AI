# Shadow 2.0 · Independent River Auditor (MVP)

## Independent from GTO 4.1 — but not an independent GTO solver

Select **Independent River Auditor** in Shadow Mode and choose sampling (10%, 25%, 100%). The playing bot is unchanged. The legacy GTO-vs-GTO Shadow remains selectable. When Shadow=0%, the auditor is not attached to the tournament engine.

### Supported decision state (v1)

- Exactly two live players: Hero versus 1 active opponent, no remaining all-in opponent.
- The current street is **river**. Hero faces a bet (`to_call > 0`), can afford the full CALL, and both FOLD and CALL are legal.
- The Hero actually chooses FOLD or CALL. A RAISE is counted as out of scope; BET/CHECK, multiway, earlier streets and side-pot scenarios are not scored.

At the instant of the real action, **after** the bot's choice and before any fold mutates the hidden hand, the engine's optional hook evaluates the same deal with a hypothetical CALL. Only the independent terminal evaluator sees the opponent's true cards. Cards are never added to PlayerView, saved to report files, or passed to the bot. For a legal terminal heads-up river CALL:

`realized_call_delta_bb = (showdown_share * (pot + price_to_call) - price_to_call) / big_blind`

`realized_fold_delta_bb = 0`

`realized_policy_delta_bb = realized_call_delta_bb if chosen CALL else 0`

Showdown share is 1 / 0.5 / 0 for winning / tying / losing. This is the **realized counterfactual outcome against the actual dealt hand**. It is NOT a conditional expected value of a single decision. Picking the best action after seeing this hand is hindsight bias and is forbidden. No individual-hand regret score is assigned.

## Statistical comparison without seeing test-hand results in advance

Two baseline policies: always CALL and always FOLD on exactly the same observed opportunities. Their observed averages and the playing policy's result are reported in bb / sampled decision. An additional simple control policy is trained using only **other tournaments** (opposite parity of tournament ID): per opponent profile + Hero made-hand group + pot-odds bucket, falling back to coarser categories if fewer than 20 training examples. Each evaluated opportunity receives an out-of-sample control recommendation without consulting its hidden opponent cards.

`OOS Δ = mean(realized baseline-control payout - realized playing-policy payout)`

A positive OOS Δ means the tested control policy did better on this sample. A negative Δ means the tested strategy did better. It is **not GTO regret**, not exploitability and not an oracle. If there are too few examples, OOS Δ is **null**, not zero. Display approximate 95% tournament-cluster robust confidence intervals, when there are at least 30 observations from 8 tournaments. Policy differences across players facing different distributions of states are descriptive, not strictly causal.

Only 10/25/100% of eligible opportunities are sampled, using a deterministic hash of pre-action public identifiers (tournament ID, hand ID, actor ID, current-street history length). A bounded priority reservoir retains at most 128 samples per tournament; the cap decreases in very long sessions to keep the total to about 20,000 records. No unbounded in-memory opponent-card log. The independent sample is streamed to `independent_river_samples.jsonl`; its aggregate is saved to `independent_river_report.json`. Existing legacy `gto5_shadow_report.json` is still created and unchanged.

## Interface

The same authenticated `/api/runs/{id}/gto5-shadow` endpoint serves the independent report when selected. New UI: coverage, sample size, CALL%, playing-policy realized mean, always-CALL mean, OOS baseline difference, confidence intervals, breakdown by player and Hero made hand, and illustrative biggest single-deal swings. The last section is **explicitly not a ranking of decision errors**.

## Limitations & roadmap

1. The audit evaluates only terminal river HU CALL vs FOLD. It cannot estimate the EV of RAISE, BET, CHECK, continuation turns, or side-pot decisions; **not assessed** is not 0 regret.
2. It uses actual hands from the simulated policy and therefore estimates observed outcomes for its encountered states. There is no posterior range reconstruction and no Nash/GTO equilibrium calculation.
3. The comparison policy is learned with coarse features and disjoint tournaments. It may be weak or poorly calibrated. The main unbiased experiment is the paired realized outcome of alternative CALL/FOLD on the *same sampled deals*, aggregated over many deals.
4. A future version can add controlled resimulation of river BET/RAISE continuations using real opponent policy snapshots and paired random seeds; flop/turn require full state replay with future cards. Never label approximations as exact regret.

## Verification

`python -m unittest -v test_independent_river_auditor` tests exact win/loss/tie payouts, no private-card persistence, unsupported context exclusion, sampling cap, cross-fitting without hand-level oracle, and actual Table.play_hand callback.

GitHub CI also invokes the tournament exporter in independent-river mode, verifies the report format and that the legacy comparative Shadow is not invoked in this mode. The existing Shadow dashboard regression runs as before.