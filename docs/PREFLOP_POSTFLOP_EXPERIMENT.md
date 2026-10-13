# A17: clean preflop/postflop experiment boundary

## Independent bases

Use the existing tournament runner and bot factory. New bot names:

- `split:gto:tag_punisher`: GTO preflop, TAG postflop
- `split:tag_punisher:gto`: TAG preflop, GTO postflop
- `split:gto:gto`: same GTO instance for both streets; control
- `split:tag_punisher:tag_punisher`: same TAG instance for both streets; control

The `split:<preflop>:<postflop>` specification accepts these nine original
bases: gto, smart, tag_punisher, wide_defender, baseline_sane, nit,
loose_passive, maniac, pressure_filler. The original bot names remain intact.

## What is held constant

Each decision receives the full unchanged `PlayerView`. This includes legal
actions, cards, table size/position, chip stacks, and previous action history.
The preflop module is invoked only on `preflop`. The postflop module is
invoked on `flop`, `turn`, and `river`.

The engine (including dealing and position labels) is unmodified. The
postflop module cannot alter how the preflop module chooses actions.
The two policy objects have separate memory unless both bases are identical.

IMPORTANT: This isolates *implementation* but does not guarantee identical
postflop situations across preflop variations. Changing preflop strategy
changes hand selection, pot sizes, stack distributions, and opponents seen
postflop. This is an intended total strategy effect, not a standalone
postflop-EV effect. To isolate postflop EV, run matched starting board,
hand, pot, stack, position, and opponent ranges in a separate test harness.

Stateful multi-street strategies such as `final` are excluded from the
initial split registry pending memory-state analysis.

## Four-factorial-control design

| Arm | Preflop | Postflop |
| --- | --- | --- |
| AA | gto | gto |
| AB | gto | tag_punisher |
| BA | tag_punisher | gto |
| BB | tag_punisher | tag_punisher |

For a first smoke test, run from the repository root:

```bash
THAI_ENGINE_IMPL=legacy python -m unittest \
  test_street_split_bot test_position_labels test_numeric_position_model \
  test_seating_rotation -v
```

Then a 9-player tournament run with four experimental and five field policies:

```bash
THAI_ENGINE_IMPL=legacy python run_tournament_stats.py \
  --players "split:gto:gto,split:gto:tag_punisher,split:tag_punisher:gto,split:tag_punisher:tag_punisher,wide_defender,smart,baseline_sane,nit,loose_passive" \
  --tournaments 90 --parallel 2 --seed 42 --seat-mode rotate \
  --output-csv split_stage_90.csv
```

Repeat with other seeds and a larger tournament count before drawing
conclusions. The tournament runner measures whole-tournament outcomes,
not the EV of each street. Keep the experimental stage assignment and
seed in experiment metadata.

## Next integration: A17 editor

Add an adapter that loads preflop rules exported from Strategy Studio,
register it as another preflop base (e.g. `a17_custom`), and pair it with
fixed `gto` postflop. Changes to the preflop rules must not require changes
to the postflop policy. That adapter is not included in this PR.
