"""One-off precompute exact selected-goal rates for 1,019 real sample deals."""
import json
from pathlib import Path
import unittest
from postflop_catalog_metrics import calculate_goal_metrics

class GenerateSelectedGoalMetrics(unittest.TestCase):
    def test_emit_selected_metrics(self):
        data=json.loads((Path(__file__).parent/"data"/"postflop_composite_catalog.json").read_text(encoding="utf-8"))
        assert len(data["rows"])==1019
        for row in data["rows"]:
            x=calculate_goal_metrics(row["hero"],row["board"])
            assert x["runouts"]==1081
            assert abs(x["hero_goals"]["improve_category"]-row["hero_improve"])<1e-7
            for name, value in row["opp_contact"].items():
                assert abs(x["villain_goals"]["pair_or_draw"][name]-value)<1e-7
            out={"id":row["id"],
                 "hero_goals":{key:round(rate,8) for key,rate in x["hero_goals"].items()},
                 "villain_goals":{
                     goal:{pos:(round(rate,8) if rate is not None else None)
                           for pos,rate in ranges.items()}
                     for goal,ranges in x["villain_goals"].items()
                 }}
            print("SELECTABLE_GOAL_METRICS="+json.dumps(out,separators=(",",":")),flush=True)

if __name__=="__main__":
    unittest.main()
