# -*- coding: utf-8 -*-
"""
Послідовний алгоритм Флойда-Воршелла (базова версія для порівняння).

Запускається в PARCS як звичайна задача, але всі обчислення виконує майстер,
воркери не використовуються. Тому послідовна і паралельна версії міряються
на однакових віртуальних машинах у тій самій хмарі.

Можна запустити й локально:  python floyd_sequential.py input.txt output.txt
"""
import sys
import time

try:
    xrange
except NameError:
    xrange = range

INF = float('inf')  # "немає ребра"


class Solver(object):
    def __init__(self, workers=None, input_file_name=None, output_file_name=None):
        self.input_file_name = input_file_name
        self.output_file_name = output_file_name
        self.workers = workers

    def solve(self):
        start_time = time.time()
        print("Job Started (sequential)")

        n, matrix = self.read_input()

        t = time.time()
        for k in xrange(n):
            pivot_row = matrix[k]
            for i in xrange(n):
                row = matrix[i]
                d_ik = row[k]
                if d_ik == INF:
                    continue
                new_row = []
                for j in xrange(n):
                    via_k = d_ik + pivot_row[j]
                    new_row.append(via_k if via_k < row[j] else row[j])
                matrix[i] = new_row
        compute_time = time.time() - t

        total_time = time.time() - start_time
        self.write_output(matrix, n, total_time, compute_time)
        print("Job Finished: %.3f s" % total_time)

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

    def write_output(self, matrix, n, total_time, compute_time):
        checksum = 0
        unreachable = 0
        for row in matrix:
            for v in row:
                if v == INF:
                    unreachable += 1
                else:
                    checksum += v

        f = open(self.output_file_name, 'w')
        f.write('# algorithm=floyd-warshall mode=sequential\n')
        f.write('# n=%d workers=0\n' % n)
        f.write('# time_total_sec=%.3f\n' % total_time)
        f.write('# time_compute_sec=%.3f\n' % compute_time)
        f.write('# checksum=%d unreachable_pairs=%d\n' % (checksum, unreachable))
        f.write('%d\n' % n)
        for row in matrix:
            f.write(' '.join('INF' if v == INF else str(v) for v in row))
            f.write('\n')
        f.close()


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python floyd_sequential.py input.txt output.txt")
        sys.exit(1)
    Solver([], sys.argv[1], sys.argv[2]).solve()
