# GTO preflop — independent position charts

## Scope

This change replaces shared Early/Middle/Late/Blinds objects **at runtime**
with an explicit 169-hand chart for every exact (table_size, position) pair.

- Supported `table_size`: 2..10.
- 9-max: `9, 8, 7, 6, 5, 4, 3, SB, BB`.
- HU: `SB, BB`; SB starts with the prior Late/button values.
- Each table-size/position combination has an independent map: 54 charts in
  total across 2..10 players.
- Every chart explicitly contains all 169 hand classes.
- Every hand contains a tuple `(fold, call, raise)` whose sum is 1.0.

The original `RANGE_EARLY`, `RANGE_MIDDLE`, `RANGE_LATE` and
`RANGE_BLINDS` remain as historical templates only. There is **no**
recalibration of ranges in this pull request. The previous `position_group`
rules and HU button behavior initialize each independent chart, including
all previous default (0.85, 0.10, 0.05) frequencies.

Each `GTOBot` copies its chart set when constructed. Editing one bot
does not modify baseline templates, other instances, other positions or
other table sizes.

## Programmatic edits

```python
from bots.gto_bot import GTOBot
bot = GTOBot()
bot.set_hand_frequencies(9, "9", "AKs", (0.0, 0.2, 0.8))
bot.set_hand_frequencies(9, "8", "AKs", (0.3, 0.2, 0.5))
bot.set_hand_frequencies(2, "SB", "AKs", (0.0, 0.0, 1.0))
```

The setter validates the hand and probabilities. These values are used
before the original facing-bet adjustment in the current GTO preflop logic.
They are **not** yet situation-specific opening/3bet/4bet charts; adding
those dimensions is a separate experiment.

For future A17 JSON support, the canonical coordinates are
`(table_size, position, hand_class)`. For all-in and pricing-dependent
ranges the schema must gain an explicit `preflop_situation` dimension.

## Check in Codespaces

```bash
THAI_ENGINE_IMPL=legacy python -m unittest \
  test_gto_position_ranges test_numeric_position_model \
  test_position_labels test_seating_rotation test_street_split_bot -v
```

The test list assumes the separate street-split branch has already been
merged locally. If testing this branch alone, omit `test_street_split_bot`.

The default game result distributions should remain consistent with the
historical behavior. The unit tests assert exact baseline frequencies,
not the equality of stochastic tournament results.

## Non-goals

- Do not change postflop GTO or Monte Carlo equity estimators.
- Do not touch `Table`, `PlayerView`, the dealer rotation, or telemetry.
- Do not merge different table sizes into a single flat position chart.
- Do not turn these baseline grouped charts into new solver-derived GTO ranges.
