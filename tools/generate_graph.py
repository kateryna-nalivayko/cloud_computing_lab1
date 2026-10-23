# -*- coding: utf-8 -*-
"""
Генератор вхідних даних: випадковий орієнтований зважений граф
у вигляді матриці суміжності N x N.

  python tools/generate_graph.py N [--density 0.3] [--max-weight 100] [--seed 42] [-o file]

Відсутнє ребро записується як INF, діагональ = 0, ваги додатні
(від'ємних циклів немає).
"""
import argparse
import random


def generate(n, density, max_weight, seed):
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        row = []
        for j in range(n):
            if i == j:
                row.append('0')
            elif rnd.random() < density:
                row.append(str(rnd.randint(1, max_weight)))
            else:
                row.append('INF')
        rows.append(' '.join(row))
    return '%d\n%s\n' % (n, '\n'.join(rows))


def main():
    ap = argparse.ArgumentParser(description='Random graph generator for Floyd-Warshall')
    ap.add_argument('n', type=int, help='кількість вершин')
    ap.add_argument('--density', type=float, default=0.3, help='ймовірність ребра (0..1)')
    ap.add_argument('--max-weight', type=int, default=100)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('-o', '--output', help='файл (за замовчуванням graph_N.txt)')
    args = ap.parse_args()

    out = args.output or 'graph_%d.txt' % args.n
    with open(out, 'w') as f:
        f.write(generate(args.n, args.density, args.max_weight, args.seed))
    print('Written %s (N=%d, density=%.2f, seed=%d)' % (out, args.n, args.density, args.seed))


if __name__ == '__main__':
    main()
