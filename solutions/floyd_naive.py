# -*- coding: utf-8 -*-
"""
Наївна паралельна версія (як у cloud_lab): вся матриця пересилається на кожній ітерації.
Потрібна лише для порівняння з floyd_solver.py у звіті.

Для кожної проміжної вершини k = 0..N-1:
  1. Майстер бере k-й рядок матриці (pivot_row).
  2. Map: матриця ділиться на P блоків рядків; кожен воркер отримує свій блок,
     pivot_row і k та оновлює свої рядки за формулою
         D[i][j] = min(D[i][j], D[i][k] + D[k][j])
  3. Reduce: майстер збирає оновлені блоки і склеює їх назад у матрицю.

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

INF = 10 ** 9  # "немає ребра"


class Solver(object):
    def __init__(self, workers=None, input_file_name=None, output_file_name=None):
        self.input_file_name = input_file_name
        self.output_file_name = output_file_name
        self.workers = workers

    def solve(self):
        start_time = time.time()
        print("Job Started")

        n, matrix = self.read_input()
        p = min(len(self.workers), n)
        print("Matrix %dx%d, workers: %d" % (n, n, p))

        # розміри блоків: перші (n % p) воркерів отримують на 1 рядок більше
        bounds = []
        base, extra = divmod(n, p)
        start = 0
        for i in xrange(p):
            end = start + base + (1 if i < extra else 0)
            bounds.append((start, end))
            start = end

        compute_start = time.time()
        for k in xrange(n):
            pivot_row = matrix[k]

            # map
            mapped = []
            for i in xrange(p):
                chunk = matrix[bounds[i][0]:bounds[i][1]]
                mapped.append(self.workers[i].mymap(chunk, pivot_row, k))

            # reduce
            matrix = self.myreduce(mapped)
        compute_time = time.time() - compute_start

        total_time = time.time() - start_time
        self.write_output(matrix, n, p, total_time, compute_time)
        print("Job Finished: %.3f s" % total_time)

    @staticmethod
    @expose
    def mymap(chunk, pivot_row, k):
        # виконується на воркері: оновлює свій блок рядків
        result = []
        for row in chunk:
            d_ik = row[k]
            if d_ik >= INF:
                result.append(row)  # з i у k шляху немає -- рядок не зміниться
                continue
            new_row = []
            for j in xrange(len(row)):
                via_k = d_ik + pivot_row[j]
                new_row.append(via_k if via_k < row[j] else row[j])
            result.append(new_row)
        return result

    @staticmethod
    @expose
    def myreduce(mapped):
        # виконується на майстрі: склеює блоки в одну матрицю
        matrix = []
        for chunk in mapped:
            matrix.extend(chunk.value)
        return matrix

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
            matrix.append(row)
        return n, matrix

    def write_output(self, matrix, n, p, total_time, compute_time):
        checksum = 0
        unreachable = 0
        for row in matrix:
            for v in row:
                if v >= INF:
                    unreachable += 1
                else:
                    checksum += v

        f = open(self.output_file_name, 'w')
        f.write('# algorithm=floyd-warshall mode=parallel-naive\n')
        f.write('# n=%d workers=%d\n' % (n, p))
        f.write('# time_total_sec=%.3f\n' % total_time)
        f.write('# time_compute_sec=%.3f\n' % compute_time)
        f.write('# checksum=%d unreachable_pairs=%d\n' % (checksum, unreachable))
        f.write('%d\n' % n)
        for row in matrix:
            f.write(' '.join('INF' if v >= INF else str(v) for v in row))
            f.write('\n')
        f.close()
