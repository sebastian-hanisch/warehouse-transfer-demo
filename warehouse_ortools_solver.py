"""OR-Tools CP-SAT model for the same dispatch problem.

Each leg is a fixed-duration interval (travel time is determined by the
route, not a decision). Per zone, a `AddCumulative` constraint with
capacity = number of transporters enforces that at most that many legs run
concurrently in a zone - transporters within a zone are interchangeable, so
no per-transporter assignment variable is needed, only the shared-resource
capacity. Consecutive legs of the same order are chained with a precedence
constraint (next leg cannot start before the previous one ends plus the
handover time) - this is the transfer-synchronization constraint. Objective:
minimize total completion time (sum of each order's final-leg end time).
"""

import math

from ortools.sat.python import cp_model

from warehouse_dispatch_core import LegAssignment, Schedule, label_transporters

SCALE = 100


def solve_ortools(routes, orders, transporters_per_zone, handover_minutes, time_limit_seconds, horizon_minutes):
    model = cp_model.CpModel()
    horizon = max(int(horizon_minutes * 10 * SCALE), 1000)
    # Round release/handover UP when discretizing to integer time units, so
    # the reconstructed float schedule never starts before the true
    # (continuous) release time or handover requirement - only rounding
    # duration itself may harmlessly shrink by <1/SCALE minutes.
    handover_scaled = math.ceil(handover_minutes * SCALE)

    starts = {}  # (order_id, leg_index) -> (IntVar start, int duration)
    intervals_by_zone = {}

    for order in orders:
        route = routes[order.order_id]
        release_scaled = math.ceil(order.release_time * SCALE)
        for i, leg in enumerate(route.legs):
            duration = max(round(leg.travel_time * SCALE), 0)
            start = model.NewIntVar(0, horizon, f"start_{order.order_id}_{i}")
            interval = model.NewIntervalVar(start, duration, start + duration, f"iv_{order.order_id}_{i}")
            starts[(order.order_id, i)] = (start, duration)
            intervals_by_zone.setdefault(leg.zone_id, []).append(interval)

            if i == 0:
                model.Add(start >= release_scaled)
            else:
                prev_start, prev_duration = starts[(order.order_id, i - 1)]
                model.Add(start >= prev_start + prev_duration + handover_scaled)

    for zone_id, intervals in intervals_by_zone.items():
        capacity = transporters_per_zone[zone_id]
        model.AddCumulative(intervals, [1] * len(intervals), capacity)

    completions = []
    for order in orders:
        route = routes[order.order_id]
        last_index = len(route.legs) - 1
        start, duration = starts[(order.order_id, last_index)]
        completions.append(start + duration)
    model.Minimize(sum(completions))

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
                )
            )
            prev_end = end

    label_transporters(assignments, transporters_per_zone)
    schedule = Schedule(method="ortools", assignments=assignments)
    return schedule, status


def status_label(status):
    return {
        cp_model.OPTIMAL: "optimal",
        cp_model.FEASIBLE: "feasible (Zeitlimit erreicht)",
        cp_model.INFEASIBLE: "unlösbar",
        cp_model.UNKNOWN: "kein Ergebnis im Zeitlimit",
        cp_model.MODEL_INVALID: "ungültiges Modell",
    }.get(status, "unbekannt")
