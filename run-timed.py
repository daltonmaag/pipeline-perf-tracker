import runpy
import sys
import argparse
import time
import json

parser = argparse.ArgumentParser(description='Run a Python script several times')
parser.add_argument('--times', help='Number of times to run', type=int, default=3)
parser.add_argument('command', help='Python module to run', nargs=argparse.REMAINDER)

args = parser.parse_args()

sys.stdout = open('output.txt', 'w')
sys.stderr = sys.stdout
module = args.command[0]
sys.argv = args.command
errcode = 0

def fake_exit(err=0):
    global errcode
    errcode = err

oldsysexit = sys.exit
sys.exit = fake_exit

t_start_cpu, t_start_clock = time.process_time(), time.perf_counter()
for i in range(args.times):
    print("\n### Starting run %i ###\n" % i)
    runpy.run_module(module, run_name="__main__")
t_end_cpu, t_end_clock = time.process_time(), time.perf_counter()

json.dump({
    "cpu": t_end_cpu-t_start_cpu,
    "clock": t_end_clock-t_start_clock,
}, open("times.json", "w"))

sys.exit(errcode)
