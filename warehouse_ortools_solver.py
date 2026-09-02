"""OR-Tools CP-SAT model for the same dispatch problem, including
transporter repositioning (deadheading) between consecutive legs on the
same transporter - the exact analogue of what the heuristics compute in
`warehouse_dispatch_core.simulate_dispatch`.

Each leg is a fixed-duration interval (travel time is determined by the
route, not a decision). Because repositioning time depends on which
SPECIFIC transporter carries a leg (it depends on where that transporter's
previous leg left it), transporters are no longer interchangeable the way
they were before repositioning existed - `AddCumulative` alone can no
longer express the problem. Per zone with capacity c_z, each leg gets an
integer `machine` variable (0..c_z-1, which of the zone's transporters
carries it). For every PAIR of legs in the same zone, a reified constraint
says: if they end up on the same machine, one must precede the other with
a repositioning gap in between; if on different machines, no constraint
between them at all (that's what lets them run concurrently). This is a
standard formulation for "parallel machines with sequence-dependent setup
times" - O(legs_per_zone^2) constraints, more expensive than the old
`AddCumulative` model but exact.

KNOWN SIMPLIFICATION (documented, not hidden): the model does not charge
repositioning from a machine's implicit home position for whichever leg
ends up first in its sequence - which leg is first is itself a decision,
and modeling "cost of coming from home" would need the same kind of
reification again for comparatively little payoff (it is a one-off cost
per machine, not per transition). The heuristics DO pay this (every
transporter starts at `zone.nodes[0]`), so OR-Tools has a small, one-time
head start per zone - never enough to change which method "wins" in this
demo's scenarios, but real should the numbers ever look suspiciously close.

Objective: minimize total completion time, weighted so express orders
(order.is_express) count EXPRESS_WEIGHT times as much - a classic
weighted-completion-time formulation. EXPRESS_WEIGHT is the SAME constant
`warehouse_dispatch_coordinated.py`'s ATCS index uses in its own w/p term
- genuinely shared, not two independently-tuned numbers for the same idea
(that used to be true of EXPRESS_PRIORITY_FACTOR/EXPRESS_WEIGHT before the
ATCS rewrite). Blended in on top: a tardiness penalty,
TARDINESS_PENALTY_WEIGHT times each order's `max(0, completion -
due_time)`. This one is NOT shared with coordinated - coordinated's
gated-tardiness attempt under this same mechanism was proven empirically
inert (by the time an order is projected late, it's almost always alone
in its ready queue - see `warehouse_dispatch_coordinated.py`'s docstring),
so coordinated now expresses due-date pressure as continuous slack inside
the same ATCS exponential instead, a genuinely different mechanism, not
just an independently-tuned copy. CP-SAT's objective must be integer, so
TARDINESS_PENALTY_WEIGHT (a small float) is applied by scaling the WHOLE
objective by OBJECTIVE_SCALE rather than the weight itself -
doesn't change the argmin, just keeps every coefficient integral.
"""

import math

from ortools.sat.python import cp_model

from warehouse_constants import EXPRESS_WEIGHT, TARDINESS_PENALTY_WEIGHT
from warehouse_dispatch_core import LegAssignment, Schedule
from warehouse_evaluation import due_time_for_order

SCALE = 100
OBJECTIVE_SCALE = 100


def solve_ortools(network, routes, orders, transporters_per_zone, handover_minutes, time_limit_seconds, horizon_minutes):
    model = cp_model.CpModel()
    horizon = max(int(horizon_minutes * 10 * SCALE), 1000)
    # Round release/handover/repositioning UP when discretizing to integer
    # time units, so the reconstructed float schedule never starts before
    # the true (continuous) requirement - only rounding leg duration itself
    # may harmlessly shrink by <1/SCALE minutes.
    handover_scaled = math.ceil(handover_minutes * SCALE)

    starts = {}  # (order_id, leg_index) -> (IntVar start, int duration)
    legs_by_zone = {}  # zone_id -> list[(order_id, leg_index, Leg)]

    for order in orders:
        route = routes[order.order_id]
        release_scaled = math.ceil(order.release_time * SCALE)
        for i, leg in enumerate(route.legs):
            duration = max(round(leg.travel_time * SCALE), 0)
            start = model.NewIntVar(0, horizon, f"start_{order.order_id}_{i}")
            starts[(order.order_id, i)] = (start, duration)
            legs_by_zone.setdefault(leg.zone_id, []).append((order.order_id, i, leg))

            if i == 0:
                model.Add(start >= release_scaled)
            else:
                prev_start, prev_duration = starts[(order.order_id, i - 1)]
                model.Add(start >= prev_start + prev_duration + handover_scaled)

    machine = {}  # (order_id, leg_index) -> IntVar
    for zone_id, legs in legs_by_zone.items():
        capacity = transporters_per_zone[zone_id]
        for order_id, leg_index, _leg in legs:
            machine[(order_id, leg_index)] = model.NewIntVar(0, capacity - 1, f"machine_{zone_id}_{order_id}_{leg_index}")

        for a in range(len(legs)):
            order_a, idx_a, leg_a = legs[a]
            start_a, duration_a = starts[(order_a, idx_a)]
            for b in range(a + 1, len(legs)):
                order_b, idx_b, leg_b = legs[b]
                start_b, duration_b = starts[(order_b, idx_b)]

                same_machine = model.NewBoolVar(f"same_{zone_id}_{order_a}_{idx_a}_{order_b}_{idx_b}")
                model.Add(machine[(order_a, idx_a)] == machine[(order_b, idx_b)]).OnlyEnforceIf(same_machine)
                model.Add(machine[(order_a, idx_a)] != machine[(order_b, idx_b)]).OnlyEnforceIf(same_machine.Not())

                a_before_b = model.NewBoolVar(f"before_{zone_id}_{order_a}_{idx_a}_{order_b}_{idx_b}")
                reposition_ab = math.ceil(network.travel_time(zone_id, leg_a.exit_node, leg_b.entry_node) * SCALE)
                reposition_ba = math.ceil(network.travel_time(zone_id, leg_b.exit_node, leg_a.entry_node) * SCALE)
                model.Add(start_b >= start_a + duration_a + reposition_ab).OnlyEnforceIf([same_machine, a_before_b])
                model.Add(start_a >= start_b + duration_b + reposition_ba).OnlyEnforceIf([same_machine, a_before_b.Not()])

    weighted_completions = []
    tardiness_terms = []
    for order in orders:
        route = routes[order.order_id]
        last_index = len(route.legs) - 1
        start, duration = starts[(order.order_id, last_index)]
        weight = EXPRESS_WEIGHT if order.is_express else 1
        weighted_completions.append(weight * (start + duration))

        due_scaled = round(due_time_for_order(order, route, handover_minutes) * SCALE)
        tardiness = model.NewIntVar(0, horizon, f"tardiness_{order.order_id}")
        model.AddMaxEquality(tardiness, [0, start + duration - due_scaled])
        tardiness_terms.append(tardiness)

    tardiness_weight_scaled = round(TARDINESS_PENALTY_WEIGHT * OBJECTIVE_SCALE)
    model.Minimize(OBJECTIVE_SCALE * sum(weighted_completions) + tardiness_weight_scaled * sum(tardiness_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, status

    assignments = []
    for order in orders:
        route = routes[order.order_id]
        prev_end = order.release_time
        for i, leg in enumerate(route.legs):
            start_var, duration = starts[(order.order_id, i)]
            start = solver.Value(start_var) / SCALE
            end = start + duration / SCALE
            ready_time = order.release_time if i == 0 else prev_end + handover_minutes
            transporter_id = f"{leg.zone_id}#{solver.Value(machine[(order.order_id, i)])}"
            assignments.append(
                LegAssignment(
                    order_id=order.order_id,
                    leg_index=i,
                    zone_id=leg.zone_id,
                    entry_node=leg.entry_node,
                    exit_node=leg.exit_node,
                    start=start,
                    end=end,
                    ready_time=ready_time,
                    transporter_id=transporter_id,
                )
            )
            prev_end = end

    _fill_repositioning_times(assignments, network)
    schedule = Schedule(method="ortools", assignments=assignments)
    return schedule, status


def _fill_repositioning_times(assignments, network):
    """repositioning_time isn't a model variable (only the gap CONSTRAINT
    between same-machine legs is) - reconstruct it post-hoc for display, the
    same real distance the constraint enforced: for each transporter, find
    its immediately preceding assignment (by start time) and compute the
    travel time from that leg's exit node to this leg's entry node."""
    by_transporter = {}
    for a in assignments:
        by_transporter.setdefault(a.transporter_id, []).append(a)

    for legs in by_transporter.values():
        legs.sort(key=lambda a: a.start)
        for prev, nxt in zip(legs, legs[1:]):
            nxt.repositioning_time = network.travel_time(nxt.zone_id, prev.exit_node, nxt.entry_node)


def status_label(status):
    return {
        cp_model.OPTIMAL: "optimal",
        cp_model.FEASIBLE: "feasible (Zeitlimit erreicht)",
        cp_model.INFEASIBLE: "unlösbar",
        cp_model.UNKNOWN: "kein Ergebnis im Zeitlimit",
        cp_model.MODEL_INVALID: "ungültiges Modell",
    }.get(status, "unbekannt")
