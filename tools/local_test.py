# -*- coding: utf-8 -*-
"""
Локальна перевірка без хмари: емулює PARCS на одному комп'ютері.

Кожен "воркер" -- окремий процес з Pyro4-демоном, у якому зареєстровано
екземпляр Solver (так само, як це робить PARCS). Майстер отримує
асинхронні проксі і викликає Solver(workers, input, output).solve().

  pip install Pyro4
  python tools/local_test.py inputs/graph_200.txt --workers 1 2 4

Скрипт перевіряє, що результат паралельної версії збігається з
послідовною та з еталонною реалізацією, і друкує час.
"""
import argparse
import importlib.util
import multiprocessing as mp
import os
import sys
import tempfile
import time

import Pyro4

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def worker_process(solution_path, conn):
    mod = load_module('solver_worker', solution_path)
    daemon = Pyro4.Daemon(host='127.0.0.1')
    uri = daemon.register(mod.Solver())
    conn.send(str(uri))
    daemon.requestLoop()


def read_result(path):
    header = {}
    rows = []
    with open(path) as f:
        for line in f:
            if line.startswith('#'):
                for part in line[1:].split():
                    if '=' in part:
                        key, val = part.split('=', 1)
                        header[key] = val
            elif line.strip():
                rows.append(line.split())
    return header, rows[1:]


def reference(input_path):
    """Еталон: найпростіша реалізація, незалежна від коду рішень."""
    inf = float('inf')
    with open(input_path) as f:
        lines = [l.split() for l in f if l.strip() and not l.startswith('#')]
    n = int(lines[0][0])
    d = [[inf if v.upper() in ('INF', '-1', '-') else int(v) for v in row] for row in lines[1:n + 1]]
    for k in range(n):
        for i in range(n):
            for j in range(n):
                if d[i][k] + d[k][j] < d[i][j]:
                    d[i][j] = d[i][k] + d[k][j]
    return [['INF' if v == inf else str(v) for v in row] for row in d]


def run_parallel(input_path, output_path, p, solution):
    procs, proxies = [], []
    for _ in range(p):
        parent, child = mp.Pipe()
        pr = mp.Process(target=worker_process, args=(solution, child), daemon=True)
        pr.start()
        procs.append(pr)
        proxy = Pyro4.Proxy(parent.recv())
        Pyro4.asyncproxy(proxy)  # PARCS робить те саме
        proxies.append(proxy)
    try:
        mod = load_module('solver_master', solution)
        t = time.time()
        mod.Solver(proxies, input_path, output_path).solve()
        return time.time() - t
    finally:
        for pr in procs:
            pr.terminate()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input')
    ap.add_argument('--workers', type=int, nargs='+', default=[1, 2, 4])
    ap.add_argument('--solution', default=os.path.join(ROOT, 'solutions', 'floyd_solver.py'))
    ap.add_argument('--no-reference', action='store_true', help='пропустити повільний еталон')
    args = ap.parse_args()

    tmp = tempfile.mkdtemp()
    seq = load_module('seq', os.path.join(ROOT, 'solutions', 'floyd_sequential.py'))
    seq_out = os.path.join(tmp, 'seq.txt')
    seq.Solver([], args.input, seq_out).solve()
    seq_header, seq_rows = read_result(seq_out)

    ok = True
    if not args.no_reference:
        ref = reference(args.input)
        same = ref == seq_rows
        ok &= same
        print('sequential == reference: %s' % same)

    t_seq = float(seq_header['time_total_sec'])
    print('\n%-10s %-10s %-10s %-10s %s' % ('workers', 'time, s', 'speedup', 'effic.', 'correct'))
    print('%-10s %-10.3f %-10s %-10s %s' % ('seq', t_seq, '1.00', '-', 'yes'))
    for p in args.workers:
        out = os.path.join(tmp, 'par_%d.txt' % p)
        run_parallel(args.input, out, p, args.solution)
        header, rows = read_result(out)
        same = rows == seq_rows
        ok &= same
        t = float(header['time_total_sec'])
        print('%-10d %-10.3f %-10.2f %-10.2f %s' % (p, t, t_seq / t, t_seq / t / p, 'yes' if same else 'NO'))

    print('\nALL CORRECT' if ok else '\nMISMATCH FOUND')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
