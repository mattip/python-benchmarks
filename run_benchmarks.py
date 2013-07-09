# Authors: Olivier Grisel
# License: MIT
from __future__ import print_function

from collections import OrderedDict
import json
import os
import traceback
from time import time
import logging

from jinja2 import Template

log = logging.getLogger(__name__)

REPORT_FILENAME = 'report/index.html'
DATA_FILENAME = 'report/benchmark_results.json'

GROUP_URL_PATTERN = ("https://github.com/numfocus/python-benchmarks/"
                     "tree/master/%s")

ABOUT_URL = ("https://github.com/numfocus/python-benchmarks/blob/master/"
             "README.md#motivation")

GITHUB_REPO_URL = "https://github.com/numfocus/python-benchmarks"


MAIN_REPORT_TEMPLATE_FILENAME = "templates/index.html"


def find_benchmarks(folders=None, platforms=None):
    """Collect benchmarks collable and shared environment initializers."""

    benchmark_groups = []

    if folders is None:
        here = os.path.dirname(os.path.abspath(__file__))
        dir_content = os.listdir(here)
        folders = [f for f in dir_content
                   if (os.path.isdir(f) and
                       os.path.exists(os.path.join(f, '__init__.py')))]
        folders.sort()

    for folder in folders:
        group_name = os.path.basename(folder)
        collected_benchmarks = []
        modules_in_error = []

        pkg = __import__(group_name, fromlist="dummy")

        benchmark_groups.append((
            group_name,
            getattr(pkg, 'make_env', None),
            collected_benchmarks,
            modules_in_error,
        ))

        for module_filename in sorted(os.listdir(folder)):
            module_name, ext = os.path.splitext(module_filename)
            if ext not in ('.py', '.so', '.dll', '.pyx'):
                continue
            module_name = "%s.%s" % (group_name, module_name)

            try:
                module = __import__(module_name, fromlist="dummy")
            except Exception as e:
                log.error("Failed to load %s: %s", module_name, e)
                tb = traceback.format_exc()
                loading_error = OrderedDict([
                    ('name', module_name),
                    ('error_type', type(e).__name__),
                    ('error', str(e)),
                    ('traceback', tb),
                ])
                modules_in_error.append(loading_error)

            for benchmark in getattr(module, 'benchmarks', ()):
                if callable(benchmark):
                    collected_benchmarks.append(
                        (benchmark.__name__, benchmark))
                elif isinstance(benchmark, tuple) and len(benchmark) == 2:
                    collected_benchmarks.append(benchmark)
                else:
                    raise ValueError("Found invalid benchmark %r in %s" %
                                     benchmark, module_name)
    return benchmark_groups


def run_benchmark(name, func, args, kwargs, memory=False, n_runs=3,
                  slow_threshold=1):
    """Call a function with the provided arguments"""
    # TODO: find a way to use memory_profiler on non-python, builtin functions
    def time_once():
        tic = time()
        func(*args, **kwargs)
        toc = time()
        return toc - tic

    first_timing = time_once()
    if first_timing > slow_threshold or n_runs <= 1:
        # Slow executions are not repeated as we assume that they are less
        # prone to variation (probably a slow naive Python variant)
        # XXX: how to deal with slow JIT compiler if any?
        cold = None
        warm = first_timing
        all_ = [first_timing]
    else:
        # Take the best time of several runs for fast executions
        other_timings = []
        for i in range(n_runs - 1):
            other_timings.append(time_once())

        all_timings = [first_timing] + other_timings
        best_timing = min(all_timings)
        if first_timing > 10 * best_timing:
            # The cold time is much slower, let's report it as cold time
            cold = first_timing
            warm = best_timing
            all_ = [all_timings]
        else:
            # The first run is not significantly slower, their is no warm-up
            # for this execution
            cold = None
            warm = best_timing
            all_ = [all_timings]
    return OrderedDict([
        ('name', name),
        ('cold_time', cold),
        ('warm_time', warm),
        ('all_times', all_),
    ])


def run_benchmarks(folders=None, platforms=None, catch_errors=True,
                   memory=True):
    collected = find_benchmarks(folders=folders, platforms=platforms)

    bench_results = []

    for group_name, make_env, benchmarks, import_errors in collected:
        log.info("Running benchmark group %s", group_name)
        args, kwargs = make_env() if make_env is not None else {}

        records = []
        runtime_errors = []
        for name, func in benchmarks:
            log.info("Benchmarking %s", name)
            try:
                record = run_benchmark(name, func, args, kwargs, memory=memory)
                records.append(record)
                log.info("%s: cold: %s, warm: %s",
                         name, record['cold_time'], record['warm_time'])
            except Exception as e:
                if catch_errors:
                    tb = traceback.format_exc()
                    runtime_error = OrderedDict([
                        ('name', name),
                        ('error_type', type(e).__name__),
                        ('error', str(e)),
                        ('traceback', tb),
                    ])
                    runtime_errors.append(runtime_error)
                    log.warn("Could not run %s: %s", name, e)
                    log.debug(tb)
                else:
                    raise

            # TODO: add special support for PyPy with a sub-process

        bench_results.append(OrderedDict([
            ('group_name', group_name),
            ('source_url', GROUP_URL_PATTERN % group_name),
            ('records', records),
            ('runtime_errors', runtime_errors),
            ('import_errors', import_errors),
        ]))
    return bench_results


def build_report(report_filename=REPORT_FILENAME, data_filename=DATA_FILENAME):
    with open(MAIN_REPORT_TEMPLATE_FILENAME, 'rb') as f:
        rendered = Template(f.read()).render(
            bench_results=bench_results,
            runtime_environment=None,
            about_url=ABOUT_URL,
            github_repo_url=GITHUB_REPO_URL,
            json_data_url=os.path.basename(bench_data_filename),
        )
    report_filename = 'report/index.html'
    log.info("Writing report to: %s", report_filename)
    with open(report_filename, 'wb') as f:
        f.write(rendered)


if __name__ == "__main__":
    # TODO: use argparse
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)-8s %(message)s')
    bench_data_filename = DATA_FILENAME
    if os.path.exists(bench_data_filename):
        log.info("Loading bench data from: %s", bench_data_filename)
        with open(bench_data_filename, 'rb') as f:
            bench_results = json.load(f)
    else:
        bench_results = run_benchmarks(catch_errors=True, memory=True)
        log.info("Writing bench data to: %s", bench_data_filename)
        with open(bench_data_filename, 'wb') as f:
            json.dump(bench_results, f, indent=2)
    build_report(data_filename=bench_data_filename)