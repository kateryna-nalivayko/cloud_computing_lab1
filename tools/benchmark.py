# -*- coding: utf-8 -*-
"""
Автоматичне тестування в хмарі через REST API майстра PARCS.

Для кожного вхідного файлу:
  * запускає послідовну версію (solutions/floyd_sequential.py);
  * запускає паралельну версію для 1, 2, ... P воркерів, вмикаючи/вимикаючи
    воркерів через API (/api/worker/<id>/enable|disable);
  * читає час з заголовка вихідного файлу, перевіряє контрольну суму;
  * зберігає results/results.csv і друкує таблицю (час, прискорення, ефективність).

  python3 tools/benchmark.py http://MASTER_IP:8080
  python3 tools/benchmark.py http://MASTER_IP:8080 --inputs inputs/graph_600.txt --workers 1 2 4 6 --repeats 3

Лише стандартна бібліотека Python 3 (працює в Cloud Shell без встановлення пакетів).
"""
import argparse
import csv
import json
import os
import re
import statistics
import sys
import time
import uuid
from urllib import error, request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARALLEL = os.path.join(ROOT, 'solutions', 'floyd_solver.py')
SEQUENTIAL = os.path.join(ROOT, 'solutions', 'floyd_sequential.py')


class Parcs:
    def __init__(self, url):
        self.url = url.rstrip('/')

    def _req(self, path, data=None, headers=None, method=None, timeout=60):
        req = request.Request(self.url + path, data=data, headers=headers or {}, method=method)
        return request.urlopen(req, timeout=timeout)

    def workers(self):
        with self._req('/api/worker') as r:
            return sorted(json.load(r)['workers'], key=lambda w: w['id'])

    def set_worker(self, worker_id, enabled):
        self._req('/api/worker/%d/%s' % (worker_id, 'enable' if enabled else 'disable'),
                  data=b'', method='POST').close()

    def use_workers(self, count):
        ws = self.workers()
        if count > len(ws):
            raise SystemExit('Потрібно %d воркерів, а зареєстровано лише %d' % (count, len(ws)))
        for i, w in enumerate(ws):
            self.set_worker(w['id'], i < count)

    def job_ids(self):
        with self._req('/jobs') as r:
            return [int(x) for x in re.findall(r'data-job-id="(\d+)"', r.read().decode('utf-8'))]

    def submit(self, name, solution_path, input_path):
        before = set(self.job_ids())
        boundary = uuid.uuid4().hex
        parts = [('--%s\r\nContent-Disposition: form-data; name="job_name"\r\n\r\n%s\r\n'
                  % (boundary, name)).encode()]
        for field, path in (('solution_file', solution_path), ('input_file', input_path)):
            with open(path, 'rb') as f:
                content = f.read()
            parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
                          'Content-Type: application/octet-stream\r\n\r\n'
                          % (boundary, field, os.path.basename(path))).encode())
            parts.append(content + b'\r\n')
        parts.append(('--%s--\r\n' % boundary).encode())
        self._req('/api/job', data=b''.join(parts),
                  headers={'Content-Type': 'multipart/form-data; boundary=%s' % boundary},
                  timeout=300).close()
        new = sorted(set(self.job_ids()) - before)
        if not new:
            raise RuntimeError('Не вдалося визначити ID нової задачі')
        return new[-1]

    def wait_output(self, job_id, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with self._req('/api/job/%d/output' % job_id, timeout=300) as r:
                    return r.read().decode('utf-8')
            except error.HTTPError as e:
                if e.code == 404:  # задача завершилась, але вихідного файлу немає
                    raise RuntimeError('Задача %d завершилась з помилкою (див. сторінку Jobs)' % job_id)
                time.sleep(2)  # 400 -- ще виконується
            except (error.URLError, OSError):
                time.sleep(5)  # майстер тимчасово не відповідає -- пробуємо ще
        raise RuntimeError('Таймаут очікування задачі %d' % job_id)


def parse_header(text):
    h = {}
    for line in text.splitlines():
        if not line.startswith('#'):
            break
        for part in line[1:].split():
            if '=' in part:
                k, v = part.split('=', 1)
                h[k] = v
    return h


def run_once(parcs, name, solution, input_path, timeout):
    job_id = parcs.submit(name, solution, input_path)
    h = parse_header(parcs.wait_output(job_id, timeout))
    return job_id, float(h['time_total_sec']), float(h['time_compute_sec']), h['checksum']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('master_url', help='http://MASTER_IP:8080')
    ap.add_argument('--inputs', nargs='+',
                    default=[os.path.join(ROOT, 'inputs', 'graph_%d.txt' % n) for n in (300, 600, 900)])
    ap.add_argument('--workers', type=int, nargs='+', help='за замовчуванням 1..усі зареєстровані')
    ap.add_argument('--repeats', type=int, default=1, help='повторів кожного запуску (медіана)')
    ap.add_argument('--timeout', type=int, default=1800, help='макс. секунд на одну задачу')
    ap.add_argument('--solution', default=PARALLEL,
                    help='паралельне рішення (за замовчуванням solutions/floyd_solver.py)')
    ap.add_argument('--out', default=os.path.join(ROOT, 'results', 'results.csv'))
    args = ap.parse_args()

    parcs = Parcs(args.master_url)
    total_workers = len(parcs.workers())
    counts = args.workers or list(range(1, total_workers + 1))
    print('Зареєстровано воркерів: %d; тестуємо: %s' % (total_workers, counts))

    rows = []
    try:
        for input_path in args.inputs:
            n = os.path.basename(input_path)
            runs = [('sequential', 0, SEQUENTIAL)] + [('parallel', p, args.solution) for p in counts]
            t_seq = None
            seq_checksum = None
            for mode, p, solution in runs:
                parcs.use_workers(max(p, 1))  # PARCS не запускає задачу без жодного воркера
                totals, computes = [], []
                for r in range(args.repeats):
                    label = '%s %s p=%d #%d' % (n, mode, p, r + 1)
                    job_id, t_total, t_comp, checksum = run_once(parcs, label, solution,
                                                                 input_path, args.timeout)
                    totals.append(t_total)
                    computes.append(t_comp)
                    print('  job #%-3d %-40s %8.2f s' % (job_id, label, t_total))
                t = statistics.median(totals)
                if mode == 'sequential':
                    t_seq, seq_checksum = t, checksum
                correct = checksum == seq_checksum
                speedup = t_seq / t if t > 0 else 1.0
                rows.append({
                    'input': n, 'mode': mode, 'workers': p,
                    'time_total_sec': '%.3f' % t,
                    'time_compute_sec': '%.3f' % statistics.median(computes),
                    'speedup': '%.2f' % speedup,
                    'efficiency': '%.2f' % (speedup / p) if p else '',
                    'checksum': checksum, 'correct': 'yes' if correct else 'NO',
                })
    finally:
        try:
            parcs.use_workers(total_workers)  # повертаємо всіх воркерів
        except Exception:
            pass

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print('\n%-16s %-11s %-8s %-10s %-8s %-8s %s'
          % ('input', 'mode', 'workers', 'time, s', 'speedup', 'effic.', 'correct'))
    for r in rows:
        print('%-16s %-11s %-8s %-10s %-8s %-8s %s'
              % (r['input'], r['mode'], r['workers'] or '-', r['time_total_sec'],
                 r['speedup'], r['efficiency'] or '-', r['correct']))
    print('\nЗбережено: %s' % args.out)
    if any(r['correct'] != 'yes' for r in rows):
        sys.exit(1)


if __name__ == '__main__':
    main()
