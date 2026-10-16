"""Representative postflop Plan MC benchmark, audit-only; no storage writes."""
import time
import planner_postflop_ev as mc

base={
    "model":"selected",
    "trials":50,
    "cycles":1,
    "hero_postflop":"gto2",
    "hero_position":"3",
    "hero_stack_bb":20,
    "opponents":[
        dict(profile="builtin:any_two",position="9",scenario="rfi",players=9,
             selector="active",entry_mode="manual",entry_pct=40,postflop="gto2"),
        dict(profile="builtin:any_two",position="8",scenario="rfi",players=9,
             selector="active",entry_mode="manual",entry_pct=35,postflop="lag"),
        dict(profile="builtin:any_two",position="7",scenario="rfi",players=9,
             selector="active",entry_mode="manual",entry_pct=30,postflop="tag"),
    ],
}
def main():
    for n,worker in [(50,1),(50,8),(250,8)]:
        setting={**base,"trials":n}
        started=time.perf_counter()
        result=mc.calculate_parallel(setting,workers=worker)
        elapsed=time.perf_counter()-started
        print("BENCH_REALISTIC", "trials",n,"workers",worker,"sec",round(elapsed,3),
              "sim",sum(result["entry_n_samples"]),
              "per_second",round(sum(result["entry_n_samples"])/elapsed),
              "active_pct",result["entry_counts_pct"],flush=True)

if __name__ == '__main__':
    main()
