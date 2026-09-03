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

Optional `rng`/`rcl_size` turn a decision from "always the single best
ready leg" into "uniformly random among the RCL_SIZE best-ranked ready
legs" (a Restricted Candidate List) - the construction phase of GRASP
(warehouse_dispatch_grasp.py). Left at their defaults (`rng=None`), every
decision is exactly the old strict-best pick, so baseline/greedy/coordinated
are completely unaffected - this is purely additive.

Optional `lookahead_window` (default 0.0, disabled) turns every decision
from strict NON-DELAY dispatch ("a transporter is dispatched the instant
both it and a ready leg exist") into a bounded DELAY/general schedule: before
committing to the current best ready leg, `try_match` peeks at the event
heap for legs that will become ready in this SAME zone within the next
`lookahead_window` minutes, scores each with `priority_fn` evaluated AT ITS
OWN future ready time (fair comparison - that's when it would actually be
served), and if any such candidate scores strictly better than the current
best ready leg, the transporter is left idle instead of dispatched - it
gets re-considered automatically once that candidate's own "ready" event
fires (or sooner, if something else changes first), so the wait is always
bounded by `lookahead_window` and can never stall the simulation. This is
what lets a heuristic use "inserted idle time" the way OR-Tools' exact
solver does (see warehouse_dispatch_coordinated.py's module docstring for
why non-delay dispatch alone cannot minimize a WEIGHTED objective) - without
it, no priority function, however good, can ever choose to wait for a more
valuable job that is about to arrive.

Optional `forced_zone`/`forced_sequence` replay a SPECIFIC known prefix of
decisions for one zone instead of letting priority_fn (+ RCL/lookahead)
decide them: `forced_sequence` is a list, consumed from the front, of
either `(order_id, leg_index)` (dispatch exactly this leg next in
`forced_zone`) or the sentinel `"WAIT"` (defer once, unconditionally - used
when the CALLER wants a deliberate pause the simulator couldn't otherwise
infer). If the next forced `(order_id, leg_index)` hasn't become ready yet,
the transporter is held idle (not substituted with something else) until
it does - `try_match` runs again on this zone's next event, so this
naturally reproduces however much real "inserted idle time" the forced
sequence implies without needing explicit WAIT tokens for that case. Once
the list is exhausted, `forced_zone` reverts to normal priority_fn(+RCL+
lookahead) behavior for the rest of the run - "prefix forced, remainder is
a baseline rollout", letting a caller ask "what would the FINAL schedule
look like if zone Z's decisions instead followed THIS exact order" without
a much more invasive generator/resumable rewrite of this event loop.

Built for a single-zone monotonic-beam-search prototype that was tried and
did NOT pay off (lost to GRASP on every seed tested - narrower scope than
GRASP, only one zone improved, plus a noisy branch-discovery process; see
project memory). Reused and refined (the idle-instead-of-substitute
fallback above was added for it) for a second prototype - re-solving one
zone's dispatch EXACTLY via a small CP-SAT sub-model, given ready times
from an already-computed heuristic schedule, then replaying the exact
sequence here - that ALSO did not pay off (0/20 seeds improved over plain
ATCS or GRASP, see project memory for why: a zone-local exact re-solve
can't rediscover the kind of "inserted idle time" benefit that depends on
information from OTHER zones, which the decomposition necessarily hides).
Kept anyway - small, self-contained, backward-compatible - as groundwork
should a future idea need "replay a known prefix, rest is a baseline
rollout" again.
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


def simulate_dispatch(network, routes, orders, transporters_per_zone, handover_minutes, priority_fn, method_name, rng=None, rcl_size=1, lookahead_window=0.0, forced_zone=None, forced_sequence=None):
    """priority_fn(order, route, leg_index, ready_time, idle_positions, now) ->
    sortable value, lower = served first. idle_positions is the list of node
    ids where the leg's own zone's CURRENTLY idle transporters sit (may be
    empty transiently between events - only used to react to positioning,
    never required). now is the current decision instant (shared by every
    candidate compared in the same try_match call, unlike ready_time which
    differs per candidate) - needed for rules like ATCS that measure slack
    relative to "right now", not to whenever this particular leg happened
    to become ready.

    rng/rcl_size: with rng given and rcl_size > 1, each decision picks
    uniformly at random among the rcl_size best-ranked ready legs instead of
    strictly the best one - see module docstring."""
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

    def better_candidate_arriving_soon(zone_id, now, idle_positions, best_score):
        for event_time, _, kind, payload in events:
            if kind != "ready" or event_time <= now or event_time > now + lookahead_window:
                continue
            cand_order_id, cand_leg_index, cand_ready_time = payload
            cand_leg = routes[cand_order_id].legs[cand_leg_index]
            if cand_leg.zone_id != zone_id:
                continue
            cand_score = priority_fn(
                orders_by_id[cand_order_id], routes[cand_order_id], cand_leg_index,
                cand_ready_time, idle_positions, cand_ready_time,
            )
            if cand_score < best_score:
                return True
        return False

    def rank_best(zone_id, idle_positions, now):
        ranked = sorted(
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
        if rng is not None and rcl_size > 1 and len(ranked) > 1:
            return rng.choice(ranked[:rcl_size])
        return ranked[0]

    def try_match(zone_id, now):
        while idle[zone_id] and ready_queue[zone_id]:
            idle_positions = [t.position for t in idle[zone_id]]

            if zone_id == forced_zone and forced_sequence:
                step = forced_sequence[0]
                if step == "WAIT":
                    forced_sequence.pop(0)
                    break
                best_ready = next(
                    (i for i, cand in enumerate(ready_queue[zone_id]) if (cand[0], cand[1]) == step),
                    None,
                )
                if best_ready is not None:
                    forced_sequence.pop(0)
                else:
                    # the forced leg hasn't become ready yet - hold this
                    # transporter idle rather than substituting a different
                    # leg; try_match runs again on this zone's next event, so
                    # this naturally waits exactly as long as needed (no
                    # explicit "WAIT" tokens required for this case, unlike
                    # deferring for a reason the caller can't already see
                    # coming, e.g. lookahead below).
                    break
            else:
                best_ready = rank_best(zone_id, idle_positions, now)

                if lookahead_window > 0:
                    candidate = ready_queue[zone_id][best_ready]
                    best_score = priority_fn(
                        orders_by_id[candidate[0]], routes[candidate[0]], candidate[1],
                        candidate[2], idle_positions, now,
                    )
                    if better_candidate_arriving_soon(zone_id, now, idle_positions, best_score):
                        break  # defer: leave this transporter idle, a future "ready" event re-triggers try_match

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
