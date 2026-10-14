# SKACHKOV Poker System — Screen 2 «План» (14 Oct 2026)

## Five-block workflow

1. **Стратегии и соперники:** Hero strategy, position, preflop scenario, effective stack, 1–5 independent opponent strategies with their own position, scenario and action-selector.
2. **Equity + A17:** Any Two / heuristic GTOBot / selected opponents; 169-hand Monte Carlo at 100/200/500/1000 trials per class; slider only highlights hands. Toggle A01–A17 with repeated clicks; drag a hand onto a box to move it.
3. **Матрицы:** one main matrix or two matrices (hero + selected opponent #1–#5), 13×13 with positions preserved; synchronized selected hand.
4. **Сравнение:** weighted combo Jaccard overlap, hero/villain range widths, changed action-combo count, actual multiway hero-range showdown equity from the computed matrix.
5. **Редактор руки:** editable action frequencies, separate box assignment, undo, apply single hand or explicitly selected boxes; equity selected hand vs Any Two heads-up, selected filter and all selected opponents.

## Strategy preservation

- A17 V5 canonical hand-to-box JSON is unchanged. User moves only affect the editable client-side copy.
- Missing actions are **not** interpreted as Fold; they are undefined. Only assigned non-fold action frequencies count toward a playable range.
- Each saved context is immutable: `/data/strategy_plans/<12hex>/vNNNNN.json`, with version refs `saved:<id>@v<n>`.
- A new revision keeps its original position/scenario/table size. Different context → Save as new.
- Changes do NOT silently rewrite baseline tournament bot code. Screen 1's bot selector does not yet load saved planner strategies. To run a custom strategy, a separate preflop strategy adapter with explicit missing-context behavior is necessary.
- Full backup ZIP now includes saved strategy revisions and restores them to new collision-free IDs.

## Sources / limitations

- **A17 V5** and **A17 Legacy** are separate box mappings.
- **GTO Bot (эвристика)** reconstructs the repository's internal position-group mixed charts, not a solved Nash GTO range. Its unopened calls are shown as limps.
- **Any Two** is 100% of 1,326 combinations.
- Unsupported scenarios for built-in A17 or heuristic GTO are deliberately left **undefined**, not populated with fictitious ranges.
- Simultaneous showdown equity uses a new 7-card evaluator and independent weighted opponent combo proposals, conditioned on all concrete cards being distinct. A shared board is dealt once; ties are paid 1 / number of winners.
- For each hand class, hero suits are sampled among its actual 4/6/12 concrete combinations. No averaged heads-up estimates are used for multiway.
- Simulation: 50–2,000 Monte Carlo runouts per class. The UI initially proposes 200; its statistical noise may be material (~7 percentage points worst-case 95% binomial upper bound). Increase trials for boundary decisions.
- No opponent fold equity, action EV, postflop realization, ICM, rake, tournament payout EV or solver equilibrium is claimed.

## API

All /api/plan/* endpoints require `X-Runner-Key`.
- GET `/plan`: Screen 2.
- GET `/api/plan/catalog`: saved strategy index, built-ins, legal actions, 169 hands and 17 boxes.
- GET `/api/plan/source?profile=&position=&scenario=&players=&stack_bb=`: resolve immutable saved or generated built-in profile.
- POST `/api/plan/strategies`: save new revision or new named context.
- DELETE `/api/plan/strategies/<id>`: move saved plan into its own trash.
- POST `/api/plan/compare`: exact combo-weighted range overlap.
- POST `/api/plan/equity`: start or serve cached Monte Carlo job; GET `/api/plan/equity/<hash>`: status/progress/result.
- Calculations are serialized, cached by input strategy versions/weights and source hashes. A tournament running blocks new equity calculations.

## Validation

`python -m unittest test_replit_simulator test_screen1 test_a17_position_ranges test_reliability test_planner test_planner_http -v`

CI also runs 2 real tournaments and a complete 169-hand equity matrix against 5 Any Two opponent distributions, checking every score is in [0,100]. The tests validate immutable revisions, source maps, 7-card scoring, card blockers, partial actions, and HTTP access controls.

## Next

- Save full per-table-size/scenario strategy assemblies for direct use in Screen 1. Avoid hidden fallbacks on uncovered positions.
- Import original benchmark equity file for 1–5 opponents and add versioned validation against it.
- Support CSV/JSON import/export for third-party and historical solver ranges (with explicit provenance).
