"""One-off auditable precomputation: 1019 physical representative metrics."""
import json
import unittest
from pathlib import Path
from postflop_catalog_metrics import calculate_example_metrics,hand_class


class GenerateCatalogMetrics(unittest.TestCase):
    def test_generate_1019_metrics_exactly(self):
        catalog=json.loads(
            (Path(__file__).resolve().parent/"data/postflop_composite_catalog.json")
            .read_text(encoding="utf-8")
        )
        assert len(catalog["rows"])==1019
        for row in catalog["rows"]:
            metrics=calculate_example_metrics(row["hero"],row["board"])
            payload={
                "id":row["id"],
                "hole_name":hand_class(
                    [tuple((int(x[:-1]),x[-1])) for x in row["hero"].split("-")]
                ),
                "hero_improve":round(metrics["hero_improve"],8),
                "opp_contact":{
                    pos:round(value,8) if value is not None else None
                    for pos,value in metrics["opponent_contact"].items()
                },
                "flop_category":metrics["flop_category"]
            }
            print("COMPOSITE_METRIC_ROW="+json.dumps(payload,separators=(",",":")),
                  flush=True)


if __name__=="__main__":
    unittest.main()
