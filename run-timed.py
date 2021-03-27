import runpy
import sys
import argparse
import time
import json
import traceback
import subprocess

parser = argparse.ArgumentParser(description='Run a Python script several times')
parser.add_argument('--times', help='Number of times to run', type=int, default=3)
parser.add_argument('--profile', help='Write profile to file', type=str)
parser.add_argument('command', help='Python module to run', nargs=argparse.REMAINDER)

args = parser.parse_args()

# sys.stdout = open('output.txt', 'w')
sys.stderr = sys.stdout
module = args.command[0]
sys.argv = args.command
exitcode = 0

times = []


for i in range(args.times):
    t_start_cpu, t_start_clock = time.process_time(), time.perf_counter()
    print("\n### Starting run %i ###\n" % i)
    try:
        runpy.run_module(module, run_name="__main__")
    except SystemExit as exception:
        exitcode = exception.code
        if exitcode != 0 and exitcode is not None:
            print("Got exit code %i, exiting" % i)
            break
    except Exception as e:
        print("Caught exception %s" % e)
        traceback.print_exc(file=sys.stdout)
        exitcode = 1
        break
    t_end_cpu, t_end_clock = time.process_time(), time.perf_counter()
    times.append({
        "cpu": t_end_cpu-t_start_cpu,
        "clock": t_end_clock-t_start_clock,
    })

json.dump(times, open("times.json", "w"))

if args.profile and (exitcode == 0 or exitcode is None):
    print("\n### Starting profiling run ###\n")
    cmd = ["py-spy", "record", "-o", args.profile, "--", "python", "-m"] + sys.argv
    print(" ".join(cmd))
    subprocess.run(cmd)
sys.exit(exitcode)
