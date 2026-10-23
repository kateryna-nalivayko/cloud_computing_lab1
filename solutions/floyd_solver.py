# -*- coding: utf-8 -*-
"""
Паралельний алгоритм Флойда-Воршелла для PARCS-Python (Map/Reduce).

Основа -- та сама схема, що й у cloud_lab (розбиття матриці на блоки рядків,
mymap на воркерах, myreduce на майстрі), з трьома виправленнями:

1. Матриця НЕ пересилається на кожній ітерації.
   Кожен воркер отримує свій блок рядків лише один раз (myinit) і зберігає
   його в пам'яті. На ітерації k йому надсилається тільки k-й рядок (pivot_row).
   Воркер, якому належить рядок k+1, повертає його -- це pivot для наступної
   ітерації. Обмін даними за ітерацію: O(P*N) замість O(N^2).

2. "Немає ребра" -- окремий маркер INF (у файлі пишеться як INF),
   а не звичайне число 999. Недосяжні пари у відповіді теж позначаються INF.

3. Є окрема послідовна версія (floyd_sequential.py) для порівняння.

Сумісно з Python 2.7 (образ hummer12007/parcs-node) і Python 3.
"""
import time

try:
    from Pyro4 import expose
except ImportError:  # щоб модуль можна було імпортувати без Pyro4
    def expose(obj):
        return obj

try:
    xrange
except NameError:
    xrange = range

INF = float('inf')  # "немає ребра" -- окремий маркер, не звичайне число


class Solver(object):
    def __init__(self, workers=None, input_file_name=None, output_file_name=None):
        self.input_file_name = input_file_name
        self.output_file_name = output_file_name
        self.workers = workers
        # стан воркера: його блок рядків (живе між викликами в межах задачі)
        self.start = 0
        self.rows = []

    # ================================================== майстер
    def solve(self):
        start_time = time.time()
        print("Job Started")

        n, matrix = self.read_input()
        p = min(len(self.workers), n)
        workers = self.workers[:p]
        print("Matrix %dx%d, workers: %d" % (n, n, p))

        # блоки рядків: перші (n % p) воркерів отримують на 1 рядок більше
        bounds = []
        base, extra = divmod(n, p)
        start = 0
        for i in xrange(p):
            end = start + base + (1 if i < extra else 0)
            bounds.append((start, end))
            start = end

        # 1. розсилаємо кожному воркеру його блок ОДИН раз
        t = time.time()
        sent = [workers[i].myinit(bounds[i][0], matrix[bounds[i][0]:bounds[i][1]])
                for i in xrange(p)]
        for s in sent:
            s.value  # чекаємо, поки всі отримають дані
        distribute_time = time.time() - t

        # 2. основний цикл: на кожній ітерації пересилається лише k-й рядок
        t = time.time()
        pivot_row = matrix[0]  # рядок 0 до першої ітерації не змінюється
        for k in xrange(n):
            # map
            mapped = []
            for w in workers:
                mapped.append(w.mymap(k, pivot_row))
            # reduce: отримуємо рядок k+1 для наступної ітерації
            pivot_row = self.myreduce(mapped)
        compute_time = time.time() - t

        # 3. збираємо результат з воркерів
        t = time.time()
        parts = [w.mycollect() for w in workers]
        result = []
        for part in parts:
            result.extend(part.value)
        collect_time = time.time() - t

        total_time = time.time() - start_time
        self.write_output(result, n, p, total_time, compute_time, distribute_time, collect_time)
        print("Job Finished: %.3f s" % total_time)

    @staticmethod
    @expose
    def myreduce(mapped):
        # виконується на майстрі: лише один воркер повертає рядок, решта -- None
        next_pivot = None
        for result in mapped:
            row = result.value
            if row is not None:
                next_pivot = row
        return next_pivot

    # ================================================== воркер
    @expose
    def myinit(self, start, chunk):
        # зберігаємо свій блок рядків у пам'яті воркера
        self.start = start
        self.rows = [list(row) for row in chunk]
        return len(self.rows)

    @expose
    def mymap(self, k, pivot_row):
        # D[i][j] = min(D[i][j], D[i][k] + D[k][j]) для своїх рядків
        for idx in xrange(len(self.rows)):
            row = self.rows[idx]
            d_ik = row[k]
            if d_ik == INF:
                continue  # з i у k шляху немає -- рядок не зміниться
            new_row = []
            for j in xrange(len(row)):
                via_k = d_ik + pivot_row[j]
                new_row.append(via_k if via_k < row[j] else row[j])
            self.rows[idx] = new_row

        # якщо рядок k+1 наш -- повертаємо його як pivot для наступної ітерації
        nk = k + 1
        if self.start <= nk < self.start + len(self.rows):
            return self.rows[nk - self.start]
        return None

    @expose
    def mycollect(self):
        return self.rows

    # ================================================== файли
    def read_input(self):
        f = open(self.input_file_name, 'r')
        lines = [l.strip() for l in f if l.strip() and not l.startswith('#')]
        f.close()
        n = int(lines[0])
        matrix = []
        for line in lines[1:n + 1]:
            row = []
            for value in line.split():
                row.append(INF if value.upper() in ('INF', '-1', '-') else int(value))
            if len(row) != n:
                raise ValueError("Row %d has %d values, expected %d" % (len(matrix), len(row), n))
            matrix.append(row)
        return n, matrix

    def write_output(self, matrix, n, p, total_time, compute_time, distribute_time, collect_time):
        checksum = 0
        unreachable = 0
        for row in matrix:
            for v in row:
                if v == INF:
                    unreachable += 1
                else:
                    checksum += v

        f = open(self.output_file_name, 'w')
        f.write('# algorithm=floyd-warshall mode=parallel\n')
        f.write('# n=%d workers=%d\n' % (n, p))
        f.write('# time_total_sec=%.3f\n' % total_time)
        f.write('# time_compute_sec=%.3f time_distribute_sec=%.3f time_collect_sec=%.3f\n'
                % (compute_time, distribute_time, collect_time))
        f.write('# checksum=%d unreachable_pairs=%d\n' % (checksum, unreachable))
        f.write('%d\n' % n)
        for row in matrix:
            f.write(' '.join('INF' if v == INF else str(v) for v in row))
            f.write('\n')
        f.close()
