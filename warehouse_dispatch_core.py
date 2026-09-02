"""Shared discrete-event dispatch simulator used by all three own methods
(baseline, greedy/decentralized, coordinated) - they differ only in the
priority function that decides which ready leg a freed-up transporter picks
next. This mirrors classic job-shop dispatching rules:

- baseline:     constant priority -> pure first-ready-first-served (FCFS)
- greedy:       Shortest Processing Time (SPT) - each zone locally prefers
                the leg that finishes fastest for ITS OWN queue, blind to
                which order it belongs to or how many transfers still
                follow. A textbook-greedy, per-resource-optimal rule.
- coordinated:  Most Work Remaining (MWKR) - a classic multi-stage
                dispatching rule: prioritize the order with the most
                remaining travel time (across all its still-open legs and
                transfers), so cross-zone orders are pushed through instead
                of stalling at a handover point.

A transporter is only tracked as a *count* per zone during simulation
(all transporters in a zone are interchangeable); concrete transporter ids
for the Gantt chart are assigned afterwards by `label_transporters`.
"""

import heapq
import itertools
from dataclasses import dataclass


@dataclass
class LegAssignment:
    order_id: int
    leg_index: int
    zone_id: str
    entry_node: str
    exit_node: str
    start: float
    end: float
    ready_time: float  # earliest the leg *could* have started (release, or prev leg end + handover)
    transporter_id: str = ""


@dataclass
class Schedule:
    method: str
    assignments: list  # list[LegAssignment], unsorted


def simulate_dispatch(routes, orders, transporters_per_zone, handover_minutes, priority_fn, method_name):
    """priority_fn(order, route, leg_index, ready_time) -> float, lower = served first."""
    seq = itertools.count()
    events = []  # heap of (time, seq, kind, payload)
    orders_by_id = {o.order_id: o for o in orders}

    for order in orders:
        heapq.heappush(events, (order.release_time, next(seq), "ready", (order.order_id, 0, order.release_time)))

    available = dict(transporters_per_zone)
    ready_heap = {zone_id: [] for zone_id in transporters_per_zone}
    assignments = []

    def try_match(zone_id, now):
        while available[zone_id] > 0 and ready_heap[zone_id]:
            _, _, _, order_id, leg_index, ready_time = heapq.heappop(ready_heap[zone_id])
            available[zone_id] -= 1
            route = next(r for r in (routes[order_id],))
            leg = route.legs[leg_index]
            start = now
            end = start + leg.travel_time
            assignments.append(
                LegAssignment(
                    order_id=order_id,
                    leg_index=leg_index,
                    zone_id=zone_id,
                    entry_node=leg.entry_node,
                    exit_node=leg.exit_node,
                    start=start,
                    end=end,
                    ready_time=ready_time,
                )
            )
            heapq.heappush(events, (end, next(seq), "free", zone_id))
            if leg_index + 1 < len(route.legs):
                next_ready = end + handover_minutes
                heapq.heappush(
                    events, (next_ready, next(seq), "ready", (order_id, leg_index + 1, next_ready))
                )

    while events:
        time, _, kind, payload = heapq.heappop(events)
        if kind == "ready":
            order_id, leg_index, ready_time = payload
            route = routes[order_id]
            leg = route.legs[leg_index]
            zone_id = leg.zone_id
            prio = priority_fn(orders_by_id[order_id], route, leg_index, ready_time)
            heapq.heappush(ready_heap[zone_id], (prio, ready_time, next(seq), order_id, leg_index, ready_time))
            try_match(zone_id, time)
        elif kind == "free":
            zone_id = payload
            available[zone_id] += 1
            try_match(zone_id, time)

    label_transporters(assignments, transporters_per_zone)
    return Schedule(method=method_name, assignments=assignments)


def label_transporters(assignments, transporters_per_zone):
    """Post-hoc greedy interval coloring: assign each leg to a concrete
    transporter slot within its zone, purely for display (Gantt chart,
    utilization). Feasibility is guaranteed by construction - the
    simulator never let more legs run concurrently in a zone than that
    zone had transporters."""
    by_zone = {}
    for a in assignments:
        by_zone.setdefault(a.zone_id, []).append(a)

    for zone_id, legs in by_zone.items():
        n = transporters_per_zone[zone_id]
        next_free = [0.0] * n
        for a in sorted(legs, key=lambda x: x.start):
            slot = min(range(n), key=lambda s: (next_free[s] > a.start, next_free[s]))
            next_free[slot] = a.end
            a.transporter_id = f"{zone_id}#{slot}"
