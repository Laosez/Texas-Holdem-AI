"""Repeatable speed audit of a realistic postflop hand on Railway."""
import time
import planner_postflop_ev as mc

def main():
    req = {"model":"selected","trials":4000,"cycles":1,
           "hand":"K4s","hero_postflop":"gto2",
           "hero_position":"3","hero_stack_bb":20,
           "opponents":[
              {"profile":"builtin:any_two","position":"9","scenario":"rfi",
               "players":9,"selector":"active","entry_mode":"manual",
               "entry_pct":40,"postflop":"gto2"},
              {"profile":"builtin:any_two","position":"8","scenario":"rfi",
               "players":9,"selector":"active","entry_mode":"manual",
               "entry_pct":35,"postflop":"lag"},
              {"profile":"builtin:any_two","position":"7","scenario":"rfi",
               "players":9,"selector":"active","entry_mode":"manual",
               "entry_pct":30,"postflop":"tag"},
           ]}
    results=[]
    for workers in (1,3):
        start=time.perf_counter()
        result=mc.calculate_parallel(req,workers=workers)
        seconds=time.perf_counter()-start
        print("BENCH_SELECTED",workers,"sec",round(seconds,4),
              "samples",result["simulations_per_hand"],
              "EV",result["ev_bb"]["K4s"],
              "CI",result["ev_ci95_bb"]["K4s"],flush=True)
        results.append((result,seconds))
    assert results[0][0]==results[1][0], "single-hand precision regression"
    print("BENCH_SELECTED_SPEEDUP",round(results[0][1]/results[1][1],2),flush=True)

if __name__=="__main__":
    main()
