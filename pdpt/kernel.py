# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The pdpt-core authors
"""Compiled kernel for the insertion scan (Proposition 4.5 of the paper; conditions (b) and (c) only: windows on the recomputed segment and the junction with the first unchanged event -- (d) and W_t are checked at acceptance), Numba-accelerated.

`scan_chain` tests every position pair (i, j) of one route for the insertion of
a two-visit chain (first at i, second at j) and returns the feasible pairs with
their cost delta and the earliest start of `second`.  It is the compiled twin of
`incremental.State.try_insert_chain` + `lns._chain_positions`; the test suite
checks both give identical results.  Falls back to pure Python without Numba.
"""
from __future__ import annotations

import numpy as np

try:
    from numba import njit
except Exception:                                   # pragma: no cover
    def njit(*a, **k):
        def deco(f):
            return f
        return deco if not (a and callable(a[0])) else a[0]

EPS = 1e-9
INF = np.inf


@njit(cache=True)
def scan_chain(nodes, x, l, load, dur, n,
               start_node, end_node, start_tw, l_end,
               first_node, second_node, dur_first, dur_second, q, is_pick_first,
               extra_release, cap, cost_km, fixed_cost, handling_cost,
               D, T, a, b, max_out):
    """Return (count, I, J, DELTA, XLAST) for feasible insertions of the chain.

    nodes[0:n], x, l, load, dur describe the current route (n visits).
    q is the quantity added to the load between first and second (q>0 for pickup/pick).
    extra_release: additional release date of `first` (the drop end a pick waits for), or -inf.
    """
    I = np.empty(max_out, np.int64)
    J = np.empty(max_out, np.int64)
    DELTA = np.empty(max_out, np.float64)
    XLAST = np.empty(max_out, np.float64)
    cnt = 0
    b1 = b[first_node]
    b2 = b[second_node]
    for i in range(n + 1):
        if i > 0:
            prev_node = nodes[i - 1]
            t_prev = x[i - 1] + dur[i - 1]
        else:
            prev_node = start_node
            t_prev = start_tw
        if t_prev > b1 + EPS:
            break                      # t_prev is monotone in i; arrival is not (T varies)
        arr1 = t_prev + T[prev_node, first_node]
        if arr1 > b1 + EPS:
            continue
        # capacity on [i, j): base load + q
        base_load = load[i - 1] if i > 0 else 0.0
        if base_load + q > cap + EPS or base_load + q < -EPS:
            continue
        s1 = arr1
        if a[first_node] > s1:
            s1 = a[first_node]
        if extra_release > s1:
            s1 = extra_release
        t1 = s1 + dur_first
        for j in range(i, n + 1):
            if j > i:
                if load[j - 1] + q > cap + EPS:
                    break
            # earliest start at second after the segment i..j-1
            if j == i:
                tt = t1
                pn = first_node
            else:
                # propagate through the segment once per j (incremental): recompute from scratch for clarity
                tt = t1
                pn = first_node
                feasible_seg = True
                for pos in range(i, j):
                    nd = nodes[pos]
                    arr = tt + T[pn, nd]
                    st = arr if arr > a[nd] else a[nd]
                    if st > b[nd] + EPS:
                        feasible_seg = False
                        break
                    tt = st + dur[pos]
                    pn = nd
                if not feasible_seg:
                    break
            if tt > b2 + EPS:
                break                  # tt is monotone in j
            arr2 = tt + T[pn, second_node]
            if arr2 > b2 + EPS:
                continue
            s2 = arr2 if arr2 > a[second_node] else a[second_node]
            t2 = s2 + dur_second
            # junction with the first unchanged successor
            if j < n:
                nxt = nodes[j]
                if t2 + T[second_node, nxt] > l[j] + EPS:
                    continue
                old_next = nxt
            else:
                if t2 + T[second_node, end_node] > l_end + EPS:
                    continue
                old_next = end_node
            old_prev = nodes[i - 1] if i > 0 else start_node
            if i == j:
                delta = D[old_prev, first_node] + D[first_node, second_node] + D[second_node, old_next] - D[old_prev, old_next]
            else:
                a_n = nodes[i]
                b_n = nodes[j - 1]
                delta = D[old_prev, first_node] + D[first_node, a_n] - D[old_prev, a_n] \
                    + D[b_n, second_node] + D[second_node, old_next] - D[b_n, old_next]
            delta = delta * cost_km
            if n == 0:
                delta += fixed_cost
            delta += handling_cost
            if cnt < max_out:
                I[cnt] = i
                J[cnt] = j
                DELTA[cnt] = delta
                XLAST[cnt] = s2
                cnt += 1
    return cnt, I, J, DELTA, XLAST


@njit(cache=True)
def scan_routes(route_ids, NODES, X, L, LOAD, DUR, N, START, END, START_TW, L_END, CAP, COSTKM, FIXED, ALLOWED,
                first_node, second_node, dur_first, dur_second, q, is_pick_first, extra_release, handling_cost,
                D, T, a, b):
    """Batched scan over the routes in `route_ids` (rows of the padded arrays).
    Returns (count, K, I, J, DELTA, XLAST) with K the route row index."""
    total = 0
    for rr in range(route_ids.shape[0]):
        n = N[route_ids[rr]]
        total += (n + 1) * (n + 2) // 2
    K = np.empty(total, np.int64)
    I = np.empty(total, np.int64)
    J = np.empty(total, np.int64)
    DELTA = np.empty(total, np.float64)
    XLAST = np.empty(total, np.float64)
    cnt = 0
    for rr in range(route_ids.shape[0]):
        r = route_ids[rr]
        if ALLOWED[r] == 0:
            continue
        n = N[r]
        if q > CAP[r] + EPS:
            continue
        c, i_, j_, d_, x_ = scan_chain(NODES[r], X[r], L[r], LOAD[r], DUR[r], n,
                                       START[r], END[r], START_TW[r], L_END[r],
                                       first_node, second_node, dur_first, dur_second, q, is_pick_first,
                                       extra_release, CAP[r], COSTKM[r], FIXED[r], handling_cost,
                                       D, T, a, b, (n + 1) * (n + 2) // 2)
        for c_ in range(c):
            K[cnt] = r
            I[cnt] = i_[c_]
            J[cnt] = j_[c_]
            DELTA[cnt] = d_[c_]
            XLAST[cnt] = x_[c_]
            cnt += 1
    return cnt, K, I, J, DELTA, XLAST
