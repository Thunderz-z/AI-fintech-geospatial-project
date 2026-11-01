"""Transaction graph construction and AML typology detectors (M1 step 6 + M1.5/F3).

**A detected motif is a suspicious pattern, never a finding of money
laundering** (AGENTS.md rule 7). Every alert produced here is a candidate
for human review, with the transaction evidence attached.

Scale note: full networkx graphs over 5M edges are impractical, so the
detectors run *vectorized on the edge frame* (pandas groupbys over
pre-filtered candidate sets; cycle detection via a scipy sparse SCC
pre-filter) and :func:`build_transaction_graph` materializes a real
``networkx.MultiDiGraph`` only for bounded windows (investigation
neighbourhoods, small fixtures, evidence bundles).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components

__all__ = [
    "MotifAlert",
    "build_transaction_graph",
    "detect_cycle",
    "detect_fan_in",
    "detect_fan_out",
    "detect_rapid_movement",
    "detect_scatter_gather",
    "detect_structuring",
]


@dataclass(frozen=True)
class MotifAlert:
    """One detected suspicious pattern with its transaction evidence."""

    typology: str  # "fan_in" | "fan_out" | "structuring" | "cycle"
    account: str  # focal account (collector / distributor / ring start)
    counter_account: str | None  # for structuring: the repeated counterparty
    tx_ids: tuple[int, ...]
    score: dict[str, Any] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.tx_ids)


def build_transaction_graph(tx: pd.DataFrame) -> nx.MultiDiGraph:
    """Build a directed multi-edge account graph from canonical transactions.

    Nodes are account IDs; each transaction becomes one edge
    ``from_account -> to_account`` carrying ``tx_id``, ``timestamp``,
    ``amount_received``, ``receiving_currency``, ``amount_paid``,
    ``payment_currency``, ``payment_format``, ``from_bank``, ``to_bank``,
    ``is_laundering``. Intended for bounded windows and fixtures, not the
    full 5M-edge dataset (see module docstring).
    """
    graph = nx.MultiDiGraph()
    for row in tx.itertuples(index=False):
        graph.add_edge(
            row.from_account,
            row.to_account,
            key=row.tx_id,
            tx_id=row.tx_id,
            timestamp=row.timestamp,
            amount_received=row.amount_received,
            receiving_currency=row.receiving_currency,
            amount_paid=row.amount_paid,
            payment_currency=row.payment_currency,
            payment_format=row.payment_format,
            from_bank=row.from_bank,
            to_bank=row.to_bank,
            is_laundering=row.is_laundering,
        )
    return graph


def _best_window_burst(
    times: np.ndarray, members: np.ndarray, tx_ids: np.ndarray,
    min_members: int, window: pd.Timedelta,
) -> dict[str, Any] | None:
    """Best (max distinct-member) time window with >= min_members distinct members.

    Shared two-pointer scan behind :func:`detect_fan_in` and
    :func:`detect_fan_out`. Inputs must be sorted by time.
    """
    best: dict[str, Any] | None = None
    left = 0
    seen: dict[str, int] = {}
    for right in range(len(times)):
        seen[members[right]] = seen.get(members[right], 0) + 1
        while (times[right] - times[left]) > window:
            seen[members[left]] -= 1
            if seen[members[left]] == 0:
                del seen[members[left]]
            left += 1
        distinct = len(seen)
        if distinct >= min_members and (best is None or distinct > best["distinct"]):
            best = {
                "distinct": distinct,
                "tx_ids": tuple(int(t) for t in tx_ids[left : right + 1]),
                "start": times[left],
                "end": times[right],
            }
    return best


def _fan_bursts(
    tx: pd.DataFrame, group_col: str, member_col: str,
    min_members: int, window: pd.Timedelta, typology: str,
) -> list[MotifAlert]:
    """Shared fan-in/fan-out machinery: distinct members converge on a group."""
    edges = tx[["tx_id", "timestamp", "from_account", "to_account"]]
    distinct = edges.groupby(group_col, observed=True)[member_col].transform("nunique")
    candidates = edges.loc[distinct >= min_members]

    alerts: list[MotifAlert] = []
    member_key = "distinct_senders" if typology == "fan_in" else "distinct_receivers"
    for group, group_edges in candidates.groupby(group_col, observed=True, sort=False):
        group_edges = group_edges.sort_values("timestamp", kind="mergesort")
        best = _best_window_burst(
            group_edges["timestamp"].to_numpy(),
            group_edges[member_col].to_numpy(),
            group_edges["tx_id"].to_numpy(),
            min_members,
            window,
        )
        if best is not None:
            alerts.append(
                MotifAlert(
                    typology=typology,
                    account=str(group),
                    counter_account=None,
                    tx_ids=best["tx_ids"],
                    score={
                        member_key: best["distinct"],
                        "window_start": str(best["start"]),
                        "window_end": str(best["end"]),
                        f"min_{member_key}": min_members,
                        "window": str(window),
                    },
                )
            )
    alerts.sort(key=lambda a: -a.score[member_key])
    return alerts


def detect_fan_in(
    tx: pd.DataFrame,
    *,
    min_senders: int = 6,
    window: pd.Timedelta | None = None,
) -> list[MotifAlert]:
    """Detect fan-in attempts: many distinct senders converge on one account.

    Candidate receivers are pre-filtered by distinct incoming senders
    (``>= min_senders``), then scanned with a sliding time window: an alert
    fires when ``min_senders`` distinct senders reach the receiver within
    ``window``.

    Note: planted IBM fan-ins show *highly varied* amounts (verified against
    HI-Small_Patterns.txt), so no amount-similarity condition is applied.

    Args:
        tx: Canonical transactions.
        min_senders: Distinct senders required inside the window.
        window: Convergence window (default 24 h).

    Returns:
        Alerts sorted by distinct-sender count (strongest first).
    """
    window = window if window is not None else pd.Timedelta(hours=24)
    return _fan_bursts(tx, "to_account", "from_account", min_senders, window, "fan_in")


def detect_fan_out(
    tx: pd.DataFrame,
    *,
    min_receivers: int = 6,
    window: pd.Timedelta | None = None,
) -> list[MotifAlert]:
    """Detect fan-out attempts: one account disperses to many distinct
    receivers within a time window (mirror of :func:`detect_fan_in`).

    Planted IBM fan-outs (verified against HI-Small_Patterns.txt) use one
    distributor with varied amounts over hours-to-days, so like fan-in no
    amount condition is applied.

    Args:
        tx: Canonical transactions.
        min_receivers: Distinct receivers required inside the window.
        window: Dispersal window (default 24 h).

    Returns:
        Alerts sorted by distinct-receiver count (strongest first).
    """
    window = window if window is not None else pd.Timedelta(hours=24)
    return _fan_bursts(
        tx, "from_account", "to_account", min_receivers, window, "fan_out"
    )


def detect_cycle(
    tx: pd.DataFrame,
    *,
    min_length: int = 3,
    max_length: int = 8,
    window: pd.Timedelta | None = None,
    degree_cap: int = 30,
    max_scc_nodes: int = 50_000,
    max_dfs_expansions: int = 1_000_000,
) -> list[MotifAlert]:
    """Detect cycle attempts: funds flowing around a directed ring back to
    the origin account within a time span.

    Scale strategy (5M edges):

    1. Restrict to low-degree nodes (total degree <= ``degree_cap``) —
       planted ring accounts are purpose-built and low-degree, high-degree
       hubs are excluded (documented heuristic).
    2. Compute strongly connected components of that sparse subgraph with
       ``scipy.sparse.csgraph`` — a cycle can only live inside one SCC.
    3. Inside each SCC of feasible size, run a depth-limited DFS with
       time-increasing edges and a per-SCC expansion budget.

    Planted IBM cycles convert currencies with unequal amounts (verified
    against HI-Small_Patterns.txt), so no amount condition is applied.

    Args:
        tx: Canonical transactions.
        min_length: Minimum ring length (transactions in the loop).
        max_length: Maximum ring length searched.
        window: Max time span from first to last ring edge (default 3 days).
        degree_cap: Node degree (in + out) ceiling for ring participants.
        max_scc_nodes: Skip SCCs larger than this (documented bound).
        max_dfs_expansions: Per-SCC DFS expansion budget (documented bound;
            a budget exhaustion can miss rings in that SCC).

    Returns:
        Alerts sorted by ring length (longest first); rings sharing the
        same transaction set are deduplicated.
    """
    window = window if window is not None else pd.Timedelta(days=3)
    edges = tx[["tx_id", "timestamp", "from_account", "to_account"]].loc[
        tx["from_account"] != tx["to_account"]
    ]
    if len(edges) < min_length:
        return []

    codes, _ = pd.factorize(
        pd.concat([edges["from_account"], edges["to_account"]], ignore_index=True),
        use_na_sentinel=False,
    )
    n_edges = len(edges)
    n_nodes = int(codes.max()) + 1
    from_int = codes[:n_edges]
    to_int = codes[n_edges:]

    # Step 1: low-degree eligible subgraph (purpose-built ring accounts are
    # low-degree; hubs are excluded as a documented heuristic).
    total_degree = np.bincount(to_int, minlength=n_nodes) + np.bincount(
        from_int, minlength=n_nodes
    )
    eligible = total_degree <= degree_cap
    keep = eligible[from_int] & eligible[to_int]
    sub_from, sub_to = from_int[keep], to_int[keep]
    sub_tx = edges["tx_id"].to_numpy()[keep]
    sub_ts_ns = edges["timestamp"].to_numpy(dtype="datetime64[ns]").astype("int64")[keep]

    # Step 2: SCCs of the eligible subgraph — cycles live inside one SCC.
    adjacency = csr_matrix(
        (np.ones(len(sub_from), dtype=np.int8), (sub_from, sub_to)),
        shape=(n_nodes, n_nodes),
    )
    n_components, labels = connected_components(
        csgraph=adjacency, directed=True, connection="strong"
    )
    component_sizes = np.bincount(labels, minlength=n_components)
    feasible = np.nonzero(
        (component_sizes >= min_length) & (component_sizes <= max_scc_nodes)
    )[0]

    alerts: list[MotifAlert] = []
    seen_rings: set[frozenset[int]] = set()
    exhausted_sccs = 0
    window_ns = window.value  # pd.Timedelta -> nanoseconds

    for component in feasible:
        mask = (labels[sub_from] == component) & (labels[sub_to] == component)
        c_from, c_to = sub_from[mask], sub_to[mask]
        c_tx, c_ts_ns = sub_tx[mask], sub_ts_ns[mask]
        if len(c_from) < min_length:
            continue
        order = np.argsort(c_ts_ns, kind="mergesort")
        c_from, c_to, c_tx, c_ts_ns = (
            c_from[order], c_to[order], c_tx[order], c_ts_ns[order],
        )

        successors: dict[int, list[tuple[int, int, int]]] = {}
        for i in range(len(c_from)):
            successors.setdefault(int(c_from[i]), []).append(
                (int(c_to[i]), int(c_tx[i]), int(c_ts_ns[i]))
            )

        expansions = 0
        budget_exhausted = False
        for start in successors:
            if budget_exhausted:
                break
            # Stack entries: (node, nodes_path, edges_path, first_ns, last_ns)
            stack: list[tuple[int, tuple[int, ...], tuple[int, ...], int | None, int | None]] = [
                (start, (start,), (), None, None)
            ]
            while stack:
                if expansions >= max_dfs_expansions:
                    budget_exhausted = True
                    break
                expansions += 1
                node, nodes_path, edges_path, first_ns, last_ns = stack.pop()
                if len(edges_path) >= max_length:
                    continue
                for nxt, tx_id, ts_ns in successors.get(node, ()):
                    if last_ns is not None and ts_ns <= last_ns:
                        continue  # time-increasing edges only
                    if first_ns is not None and ts_ns - first_ns > window_ns:
                        continue  # ring span bound
                    new_edges = edges_path + (tx_id,)
                    if nxt == start:
                        if len(new_edges) >= min_length:
                            key = frozenset(new_edges)
                            if key not in seen_rings:
                                seen_rings.add(key)
                                ring_ns = c_ts_ns[np.isin(c_tx, np.array(new_edges))]
                                alerts.append(
                                    MotifAlert(
                                        typology="cycle",
                                        account=str(start),
                                        counter_account=None,
                                        tx_ids=new_edges,
                                        score={
                                            "ring_length": len(new_edges),
                                            "window_start": str(
                                                pd.Timestamp(int(ring_ns.min()), unit="ns")
                                            ),
                                            "window_end": str(
                                                pd.Timestamp(int(ring_ns.max()), unit="ns")
                                            ),
                                            "min_length": min_length,
                                            "max_length": max_length,
                                            "window": str(window),
                                            "degree_cap": degree_cap,
                                        },
                                    )
                                )
                        continue
                    if nxt in nodes_path:
                        continue  # simple cycles only
                    stack.append(
                        (
                            nxt,
                            nodes_path + (nxt,),
                            new_edges,
                            ts_ns if first_ns is None else first_ns,
                            ts_ns,
                        )
                    )
        if budget_exhausted:
            exhausted_sccs += 1

    if exhausted_sccs:
        warnings.warn(
            f"detect_cycle: {exhausted_sccs} SCC(s) hit the DFS expansion budget "
            f"({max_dfs_expansions}); some rings may be missed in those components",
            stacklevel=2,
        )

    if alerts:
        # Deduplicate rings that share their transaction set (rotations).
        unique: dict[frozenset[int], MotifAlert] = {
            frozenset(a.tx_ids): a for a in alerts
        }
        alerts = list(unique.values())
    alerts.sort(key=lambda a: -a.score["ring_length"])
    return alerts


def detect_structuring(
    tx: pd.DataFrame,
    *,
    threshold: float = 10_000.0,
    min_transactions: int = 5,
    window: pd.Timedelta | None = None,
) -> list[MotifAlert]:
    """Detect structuring: repeated just-below-threshold transfers between a
    fixed sender/receiver pair inside a short window.

    Args:
        tx: Canonical transactions.
        threshold: Reporting threshold amounts stay below.
        min_transactions: Sub-threshold transfers between the same pair
            required inside ``window``.
        window: Pairing window (default 24 h).

    Returns:
        One alert per (sender, receiver) pair meeting the criteria, strongest
        (most transfers) first.
    """
    window = window if window is not None else pd.Timedelta(hours=24)
    below = tx.loc[
        (tx["amount_paid"] < threshold)
        & (tx["amount_received"] < threshold),
        ["tx_id", "timestamp", "from_account", "to_account", "amount_paid"],
    ]

    pair_size = below.groupby(["from_account", "to_account"], observed=True)[
        "tx_id"
    ].transform("size")
    pairs = below.loc[pair_size >= min_transactions]

    alerts: list[MotifAlert] = []
    for (sender, receiver), edges in pairs.groupby(
        ["from_account", "to_account"], observed=True, sort=False
    ):
        edges = edges.sort_values("timestamp", kind="mergesort")
        times = edges["timestamp"].to_numpy()
        tx_ids = edges["tx_id"].to_numpy()
        k = min_transactions
        # Sliding stretch of k consecutive pair-transfers within the window.
        gaps = times[k - 1 :] - times[: len(times) - k + 1]
        fits = gaps <= window
        if not fits.any():
            continue
        idx = int(np.argmax(fits))
        window_ids = tuple(int(t) for t in tx_ids[idx : idx + k])
        window_amounts = edges["amount_paid"].to_numpy()[idx : idx + k]
        alerts.append(
            MotifAlert(
                typology="structuring",
                account=str(sender),
                counter_account=str(receiver),
                tx_ids=window_ids,
                score={
                    "transfers": k,
                    "total_amount": float(window_amounts.sum()),
                    "threshold": threshold,
                    "window_start": str(times[idx]),
                    "window_end": str(times[idx + k - 1]),
                    "window": str(window),
                },
            )
        )

    alerts.sort(key=lambda a: -a.score["transfers"])
    return alerts


def detect_scatter_gather(
    tx: pd.DataFrame,
    *,
    min_sources: int = 4,
    min_sinks: int = 4,
    window: pd.Timedelta | None = None,
    redistribution_window: pd.Timedelta | None = None,
) -> list[MotifAlert]:
    """Detect scatter-gather: many sources converge on a hub within a window
    and the hub redistributes to many sinks inside an extended window.

    Args:
        tx: Canonical transactions.
        min_sources: Distinct senders into the hub required.
        min_sinks: Distinct receivers from the hub required.
        window: Convergence burst window (default 7 days).
        redistribution_window: Extra time after the incoming burst end in
            which the outgoing burst must fit (default 3 days).

    Returns:
        One alert per qualifying hub, strongest (most distinct sources) first.
        A suspicious pattern — never a laundering finding (module docstring).
    """
    window = window if window is not None else pd.Timedelta(days=7)
    redistribution_window = (
        redistribution_window if redistribution_window is not None else pd.Timedelta(days=3)
    )
    edges = tx[
        ["tx_id", "timestamp", "from_account", "to_account", "amount_received", "amount_paid"]
    ]
    in_distinct = edges.groupby("to_account", observed=True)["from_account"].transform("nunique")
    candidates = edges.loc[in_distinct >= min_sources]

    alerts: list[MotifAlert] = []
    for hub, hub_edges in candidates.groupby("to_account", observed=True, sort=False):
        hub_edges = hub_edges.sort_values("timestamp", kind="mergesort")
        incoming = _best_window_burst(
            hub_edges["timestamp"].to_numpy(),
            hub_edges["from_account"].to_numpy(),
            hub_edges["tx_id"].to_numpy(),
            min_sources,
            window,
        )
        if incoming is None:
            continue
        outgoing = edges.loc[
            (edges["from_account"] == hub)
            & (edges["timestamp"] >= incoming["start"])
            & (edges["timestamp"] <= incoming["end"] + redistribution_window)
        ].sort_values("timestamp", kind="mergesort")
        if outgoing["to_account"].nunique() < min_sinks:
            continue
        out_burst = _best_window_burst(
            outgoing["timestamp"].to_numpy(),
            outgoing["to_account"].to_numpy(),
            outgoing["tx_id"].to_numpy(),
            min_sinks,
            redistribution_window,
        )
        if out_burst is None:
            continue
        total_in = float(
            edges.loc[edges["tx_id"].isin(incoming["tx_ids"]), "amount_received"].sum()
        )
        total_out = float(
            edges.loc[edges["tx_id"].isin(out_burst["tx_ids"]), "amount_paid"].sum()
        )
        alerts.append(
            MotifAlert(
                typology="scatter_gather",
                account=str(hub),
                counter_account=None,
                tx_ids=tuple(dict.fromkeys([*incoming["tx_ids"], *out_burst["tx_ids"]])),
                score={
                    "distinct_sources": incoming["distinct"],
                    "distinct_sinks": out_burst["distinct"],
                    "total_in": total_in,
                    "total_out": total_out,
                    "in_window_start": str(incoming["start"]),
                    "in_window_end": str(incoming["end"]),
                    "out_window_start": str(out_burst["start"]),
                    "out_window_end": str(out_burst["end"]),
                    "window": str(window),
                    "redistribution_window": str(redistribution_window),
                },
            )
        )
    alerts.sort(key=lambda a: -a.score["distinct_sources"])
    return alerts


def detect_rapid_movement(
    tx: pd.DataFrame,
    *,
    min_hops: int = 3,
    max_hops: int = 8,
    max_gap: pd.Timedelta | None = None,
    min_pass_through: float = 0.5,
    max_alerts: int = 500,
) -> list[MotifAlert]:
    """Detect rapid movement of funds: time-ordered chains of at least
    ``min_hops`` transfers where each hop follows within ``max_gap`` and
    retains at least ``min_pass_through`` of the previous hop's amount
    (a pass-through/layering heuristic).

    Pure-Python bounded DFS over per-account time-sorted edge lists —
    intended for bounded datasets and fixtures, not the full 5M-edge frame
    (see :func:`detect_cycle` for the vectorized alternative at scale).
    ``max_alerts`` caps the returned chains; exceeding it is recorded in the
    first alert's score as ``"capped": true``.

    Args:
        tx: Canonical transactions.
        min_hops: Minimum chain length (transfers) to alert.
        max_hops: Maximum chain length explored.
        max_gap: Maximum time between consecutive hops (default 6 h).
        min_pass_through: Minimum amount ratio hop-to-hop.
        max_alerts: Hard cap on returned alerts (runtime guard).

    Returns:
        Chains strongest (largest start amount) first.
    """
    max_gap = max_gap if max_gap is not None else pd.Timedelta(hours=6)
    edges = tx[["tx_id", "timestamp", "from_account", "to_account", "amount_paid"]].sort_values(
        "timestamp", kind="mergesort"
    )
    times = edges["timestamp"].to_numpy()
    amounts = edges["amount_paid"].to_numpy(dtype=float)
    tx_ids = edges["tx_id"].to_numpy()
    senders = edges["from_account"].to_numpy()
    receivers = edges["to_account"].to_numpy()

    by_sender: dict[str, list[int]] = {}
    for index, account in enumerate(senders):
        by_sender.setdefault(account, []).append(index)

    alerts: list[MotifAlert] = []
    seen: set[frozenset[int]] = set()
    capped = False
    for start in range(len(edges)):
        if capped:
            break
        # Iterative DFS: (last_edge_index, amount_available, path).
        stack: list[tuple[int, float, list[int]]] = [(start, amounts[start], [start])]
        while stack:
            last, available, path = stack.pop()
            if len(path) >= min_hops:
                key = frozenset(int(tx_ids[i]) for i in path)
                if key not in seen:
                    seen.add(key)
                    alerts.append(
                        MotifAlert(
                            typology="rapid_movement",
                            account=str(senders[path[0]]),
                            counter_account=str(receivers[path[-1]]),
                            tx_ids=tuple(int(tx_ids[i]) for i in path),
                            score={
                                "hops": len(path),
                                "start_amount": float(amounts[path[0]]),
                                "end_amount": float(amounts[path[-1]]),
                                "chain_start": str(times[path[0]]),
                                "chain_end": str(times[path[-1]]),
                                "max_gap": str(max_gap),
                                "min_pass_through": min_pass_through,
                                **({"capped": True} if capped else {}),
                            },
                        )
                    )
                    if len(alerts) >= max_alerts:
                        capped = True
                        break
            if len(path) >= max_hops or capped:
                continue
            following = by_sender.get(receivers[last], [])
            for nxt in following:
                nxt_time = times[nxt]
                if nxt_time <= times[last] or (nxt_time - times[last]) > max_gap:
                    continue
                if amounts[nxt] < min_pass_through * available:
                    continue
                stack.append((nxt, amounts[nxt], [*path, nxt]))

    alerts.sort(key=lambda a: -a.score["start_amount"])
    if capped:
        # The cap engaged: mark every emitted alert so consumers know the
        # list is a bounded sample, not the full population.
        for alert in alerts:
            alert.score["capped"] = True
    return alerts
