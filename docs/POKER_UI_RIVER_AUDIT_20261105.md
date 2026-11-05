# Poker System · Page 1 / Page 3 simplification + River BET/RAISE audit

## New active postflop list (12)

`gto_postflop_v1`, `gto_postflop_20`, `gto_postflop_21`, `gto_postflop_21c`, `gto_postflop_33_5`, `gto_postflop_41_5`, `gto_postflop_531_5`, `gto_postflop_54_step15`, `gto_postflop_541_step15`, `tag_postflop_v1`, `lag_postflop_v1`, `random`.

20 older selectable variants moved to `postflop_archived` and removed from the default UI choices on pages 1 and 2. All full implementation entries stay in `bases`; archived profile IDs remain valid for historical scenarios and restored sessions. No old tournaments, snapshots or saved plans deleted. GTO 4.2 does not exist in the current catalog; GTO 4.0 archived and GTO 4.1 kept active.

Page 1: removed seven large methodology/old-version tables and the always-expanded 100-hand GTO decision trace. The execution log remains under a collapsed 'Technical log' section for troubleshooting; 9-seat preset now focuses on GTO 5.4.1/15, 5.4/15, 5.3.1, 4.1, 3.3, 2.1c, TAG, LAG and Random, with identical A17 preflop. Text around controls and reports was shortened. Existing full analysis and Independent Auditor are retained.

Page 3: removed four redundant columns P/S/F/SF whose exact content was already encoded in the class code / title, reducing 11 columns to 7. Kept all 36 mathematically unique river classes and filters. A 36→18 reduction would discard valid physical board categories, so was not performed.

## New river action analysis

Version 1.1 collects River heads-up BET and RAISE by *actual action*, without requiring a GTO reference bot or opponent private cards. In the optional engine hook, **after** the actual Hero action we record the chip stack and public action index. At hand completion, after actual fold or showdown settlement, a callback provides final chip stacks and public action history. The reported realized result is:

`realized_bb = (hero_final_stack - hero_stack_immediately_before_the_action) / current_bb`.

This includes all subsequent opponent responses and Hero responses and excludes money already committed before the decision. The report separately counts opponent first actions (FOLD/CALL/RAISE). Sampling is deterministic and bounded, matching the existing 10/25/100% audit. No opponent hole cards or hidden policy-state are included in BET/RAISE records.

**This is empirical outcome analysis, not a counterfactual BET/RAISE EV.** An alternative unplayed BET or RAISE could produce a different response from the opponent. No counterfactual regret, 'best action', solver equilibrium, or cross-policy causal ranking is claimed. Only CALL/FOLD retains existing same-deal hypothetical-call payout; its individual hand outcomes are likewise not per-hand regret or oracle EV. Flop, turn, multiway and all-in remain unsupported.

Files: `independent_river_samples.jsonl` for FOLD/CALL, `independent_river_aggression.jsonl` for BET/RAISE, a joint `independent_river_report.json` with separate `aggression` section. The UI displays observed action rewards, tournament-cluster 95% CIs when supported, reaction frequencies and illustrative individual hands. No 'overall regret' combined across incompatible estimates.

## Verification

Run `python -m unittest -v test_independent_river_auditor test_gto_postflop_20 test_gto_postflop_30 test_gto54_step_range test_replit_simulator` plus `node test_gto5_shadow_ui.js`. CI smoke runs the exporter in independent mode and verifies both samples, reports and privacy limits.