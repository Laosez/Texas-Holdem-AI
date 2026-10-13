# A17 Shared Equity Estimator — compatibility stage

## What is unified

These three bots now call one sampling implementation in
`core/equity_legacy.py`:

| Bot | Existing method preserved | Default samples |
|---|---|---:|
| GTO | `GTOBot._hand_strength` | 100 |
| Smart | `SmartBot._estimate_equity` | 100 |
| Monte Carlo | `MonteCarloBot._estimate_equity` | 500 |

The methods remain available as stable wrappers, and the bots keep their
distinct postflop decision rules. The shared evaluator also accepts a
private `random.Random(seed)` object to make an isolated simulation
repeatable. Without an explicit RNG it consumes Python's global
`random` state just as the old bots did.

## Why not replace core/equity.py

The repo already contains `core/equity.py` as the canonical, frozen CFR
(Path A/Path B) equity module. That implementation differs from the legacy
bots in both sampling and showdown accounting.

We MUST NOT modify or silently replace the CFR implementation in this
refactor. The new module is explicitly named `equity_legacy` to avoid
confusing potentially non-comparable numeric values.

The legacy bots credit **0.5** on any tie, including multiway ties; this
is not mathematically correct for split pots with more than two winners.
It is deliberately preserved to keep the test baseline unchanged. A
future algorithm version may return actual equity shares if separately
validated.

## Reproducibility

```python
import random
from core.equity_legacy import estimate_equity_legacy

value = estimate_equity_legacy(
    hole_cards=[("A", "s"), ("K", "s")],
    board=[("Q", "h"), ("J", "h"), ("2", "c")],
    num_opponents=2,
    sims=100,
    rng=random.Random(42),
)
```

A single fixed seed per bot is **not** sufficient for fully matched
tournament experiments if they take different actions. Replayable
per-decision RNG streams and identical game state fixtures are stronger
controls for later A17 experiments.

## Codespaces tests

This branch is stacked on `feat/gto-position-ranges-20261014`. After
merging both to the local `feature/separate-preflop-postflop`, run:

```bash
THAI_ENGINE_IMPL=legacy python -m unittest \
  test_shared_legacy_equity \
  test_gto_position_ranges \
  test_numeric_position_model \
  test_position_labels \
  test_seating_rotation \
  test_street_split_bot -v
```

Optionally perform a short 2–9-player tournament smoke check after
passing all tests. The full 90-tournament benchmark is a *separate*
validation task and should not be attributed to these unit tests.

## Next algorithm upgrade (separate branch)

Compare versions side-by-side on seeded poker states before enabling:
- exact winner split-pot shares in multiway pots;
- stronger tie handling, source range models;
- configurable Monte Carlo precision and common random numbers;
- caching or other optimized evaluator implementations.

Version these algorithm changes explicitly; do not mix them into the
compatibility baseline.
