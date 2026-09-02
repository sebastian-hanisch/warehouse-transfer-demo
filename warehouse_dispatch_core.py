"""Shared discrete-event dispatch simulator used by all three own methods
(baseline, greedy/decentralized, coordinated) - they differ only in the
priority function that decides which ready leg gets served next whenever a
transporter is available. This mirrors classic job-shop dispatching rules:

- baseline:     constant priority -> pure first-ready-first-served (FCFS)
- greedy:       Shortest Processing Time (SPT) on the current leg's nominal
                travel time only - each zone locally prefers the leg that
                finishes fastest for ITS OWN queue, blind to which order it
                belongs to, how many transfers still follow, AND blind to
                repositioning: it has no notion of where its idle
                transporters currently sit, so it can send one clear across
                the zone for a "short" leg while a much closer leg waits.
- coordinated:  SPT plus a small weighted look-ahead at the order's whole
                remaining route AND at how far the nearest idle transporter
                actually is (see warehouse_dispatch_coordinated.py).

Transporters are individually tracked (id + current position + free-at
time), not just counted - a transporter that just dropped off at one node
must reposition (deadhead, unloaded) to a new leg's entry node before it
can start carrying it. Repositioning time is real network travel time
(`network.travel_time`), computed from wherever the transporter's previous
leg left it - the same mechanic OR-Tools models exactly via per-machine
sequencing (see warehouse_ortools_solver.py). Every transporter starts at
its zone's first node (`zone.nodes[0]`, the aisle's hub-facing end for
aisle zones) at simulation time 0 - a "parked near the entrance" default.

Because repositioning cost depends on WHICH transporter ends up serving a
leg, and that can only be known at the moment a transporter is actually
free (not when the leg first became ready - the idle pool keeps changing
in between), priority is recomputed fresh every time a transporter frees
up and there is more than one ready leg to choose from, rather than being
fixed once and cached in a heap. `priority_fn` receives the CURRENT list of
idle-transporter positions in the leg's own zone, so it CAN factor
repositioning in (coordinated does; baseline/greedy ignore the argument by
design). Once a leg is chosen, the transporter requiring the LEAST
repositioning to reach it is picked (ties broken by whichever has been idle
longest) - a standard, realistic nearest-vehicle dispatch rule.
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
    start: float  # pickup time (after any repositioning) - order actually starts moving
    end: float
    ready_time: float  # earliest the leg *could* have started (release, or prev leg end + handover)
    transporter_id: str = ""
    repositioning_time: float = 0.0  # empty/deadhead travel immediately before `start`


@dataclass
class Schedule:
    method: str
    assignments: list  # list[LegAssignment], unsorted


@dataclass
class _TransporterState:
    id: str
    position: str
    free_at: float


def simulate_dispatch(network, routes, orders, transporters_per_zone, handover_minutes, priority_fn, method_name):
    """priority_fn(order, route, leg_index, ready_time, idle_positions, now) ->
    sortable value, lower = served first. idle_positions is the list of node
    ids where the leg's own zone's CURRENTLY idle transporters sit (may be
    empty transiently between events - only used to react to positioning,
    never required). now is the current decision instant (shared by every
    candidate compared in the same try_match call, unlike ready_time which
    differs per candidate) - needed for rules like ATCS that measure slack
    relative to "right now", not to whenever this particular leg happened
    to become ready."""
    seq = itertools.count()
    events = []  # heap of (time, seq, kind, payload)
    orders_by_id = {o.order_id: o for o in orders}

    for order in orders:
        heapq.heappush(events, (order.release_time, next(seq), "ready", (order.order_id, 0, order.release_time)))

    idle = {}
    for zone_id, count in transporters_per_zone.items():
        home = network.zones[zone_id].nodes[0]
        idle[zone_id] = [_TransporterState(id=f"{zone_id}#{i}", position=home, free_at=0.0) for i in range(count)]

    ready_queue = {zone_id: [] for zone_id in transporters_per_zone}  # list of (order_id, leg_index, ready_time)
    assignments = []

    def try_match(zone_id, now):
        while idle[zone_id] and ready_queue[zone_id]:
            idle_positions = [t.position for t in idle[zone_id]]
            best_ready = min(
                range(len(ready_queue[zone_id])),
                key=lambda i: (
                    priority_fn(
                        orders_by_id[ready_queue[zone_id][i][0]],
                        routes[ready_queue[zone_id][i][0]],
                        ready_queue[zone_id][i][1],
                        ready_queue[zone_id][i][2],
                        idle_positions,
                        now,
                    ),
                    ready_queue[zone_id][i][2],  # tie-break: ready_time
                ),
            )
            order_id, leg_index, ready_time = ready_queue[zone_id].pop(best_ready)
            route = routes[order_id]
            leg = route.legs[leg_index]

            best_transporter = min(
                range(len(idle[zone_id])),
                key=lambda i: (network.travel_time(zone_id, idle[zone_id][i].position, leg.entry_node), idle[zone_id][i].free_at),
            )
            transporter = idle[zone_id].pop(best_transporter)
            repositioning_time = network.travel_time(zone_id, transporter.position, leg.entry_node)

            start = now + repositioning_time
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
                    transporter_id=transporter.id,
                    repositioning_time=repositioning_time,
                )
            )
            heapq.heappush(events, (end, next(seq), "free", (zone_id, transporter.id, leg.exit_node)))
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
            ready_queue[zone_id].append((order_id, leg_index, ready_time))
            try_match(zone_id, time)
        elif kind == "free":
            zone_id, transporter_id, position = payload
            idle[zone_id].append(_TransporterState(id=transporter_id, position=position, free_at=time))
            try_match(zone_id, time)

    return Schedule(method=method_name, assignments=assignments)
