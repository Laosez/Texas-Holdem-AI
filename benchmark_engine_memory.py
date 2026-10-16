"""Isolated process-level timing and peak RSS of fast versus legacy engine.

This launches child Python interpreters to avoid contaminating the fast-mode
memory result with the legacy dictionary allocation in the parent process.
On Linux ru_maxrss uses KiB. No private data is collected.
"""
import json
import os
import subprocess
import sys

CHILD = r"""
import json
import os
import resource
import time
start = time.perf_counter()
from core import engine
imported = time.perf_counter()
hole = [('A','s'), ('K','s')]
board = [('Q','s'), ('J','s'), ('T','s'), ('2','c'), ('3','d')]
value = engine.eval_hand(hole, board)
evaluated = time.perf_counter()
print('MEMORY_RESULT ' + json.dumps({
  'mode': os.environ['THAI_HAND_EVALUATOR'],
  'import_seconds': round(imported - start, 5),
  'first_eval_seconds': round(evaluated - imported, 5),
  'total_seconds': round(evaluated - start, 5),
  'rss_peak_mib': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
  'table_loaded': engine._FIVE_CARD_TABLE is not None,
  'score': value
}), flush=True)
"""


def run(mode):
    env = dict(os.environ, THAI_HAND_EVALUATOR=mode)
    # Limit run duration in case the old table has to be generated from scratch.
    p = subprocess.run([sys.executable, "-c", CHILD], env=env, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=120, check=False)
    print("MEMORY_CHILD_EXIT mode=%s code=%d" % (mode, p.returncode), flush=True)
    print(p.stdout, flush=True)
    if p.returncode != 0:
        raise RuntimeError("Memory child failed for evaluator %s" % mode)


if __name__ == "__main__":
    print("MEMORY_BENCHMARK_BEGIN", flush=True)
    run("fast")
    run("legacy")
    print("MEMORY_BENCHMARK_END", flush=True)
