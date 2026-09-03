"""GRASP (Greedy Randomized Adaptive Search Procedure; Feo & Resende
1989/1995) built directly on top of Koordiniert's ATCS priority rule - tries
to close part of the gap to OR-Tools that a single dispatching-rule pass
cannot close by construction alone: ATCS commits to one decision per event
and never reconsiders it, however good the rule.

Construction: the exact same ATCS index as warehouse_dispatch_coordinated.py
(imported, not re-derived - a single source of truth, no risk of the two
formulas drifting apart), but at every dispatch decision
`simulate_dispatch` picks uniformly at random from the RCL_SIZE best-ranked
ready legs (the "Restricted Candidate List") instead of strictly the single
best. GRASP_ITERATIONS independent randomized constructions are run and the
best one (by objective, see below) is kept - already more than a single
dispatching-rule pass can do, since a later construction can "undo" an
earlier greedy choice that turned out costly, something ATCS itself never
gets a chance to do.

Look-ahead (added 2026-09-03): every `simulate_dispatch` call here (both
construction and local search) also passes `lookahead_window=LOOKAHEAD_WINDOW`.
Verified directly on real OR-Tools solutions that this targets a genuine,
provable source of the gap: 6 of 37 proven-OPTIMAL CP-SAT solutions checked
on a hub-bottleneck instance left the sole hub transporter idle for a moment
even though a leg was already ready and waiting ("inserted idle time" -  a
classical, well-known reason non-delay schedules can be suboptimal for a
WEIGHTED objective like this one's). `simulate_dispatch`'s own non-delay
loop can never do that on its own - every decision dispatches immediately
whenever both a transporter and a ready leg exist. `lookahead_window` lets
it defer: before committing to the current best ready leg, it peeks at legs
that will become ready in this zone within the window, and if one of them
scores better under the SAME priority function (evaluated at ITS OWN future
ready time), the transporter is left idle instead - it gets reconsidered
automatically once that leg's own "ready" event fires, so the wait is always
bounded and can never stall. See warehouse_dispatch_core.py's module
docstring for the mechanism itself.

Local search: starting from the best constructed schedule, a bounded number
of random single-leg perturbations are tried. Each one adds a random bias to
ONE leg's priority (nudging it earlier or later relative to whatever else it
competes against in its own zone) and re-simulates (deterministically,
rng=None) to get a complete, feasible candidate schedule - feasibility is
automatic because a bias only ever changes WHICH ready leg wins a tie, never
the simulator's own precedence/capacity mechanics. A perturbation is kept
only if it improves the objective, otherwise reverted - greedy/randomized
hill-climbing, not simulated annealing; no acceptance criterion for worse
moves, the perturbation budget here is too small to need one. (A more
sophisticated swap-based local search + Iterated Local Search shake-and-
restart was tried as a REPLACEMENT for this - see git history/project
memory - and reverted: no consistent net improvement over this simpler
design, at roughly double the runtime. The look-ahead addition above is a
different, unrelated axis - it changes WHEN a transporter is dispatched,
not which candidate wins - and stacks additively with this local search
rather than competing with it.)

Objective: NOT total lead time (the app's headline KPI), but the SAME
weighted-completion-time + tardiness objective OR-Tools actually minimizes
(see warehouse_ortools_solver.py) - "closes the gap to OR-Tools" is only a
meaningful claim when measured on the metric OR-Tools is solving for.
"""

import math
import random

from warehouse_constants import EXPRESS_WEIGHT, TARDINESS_PENALTY_WEIGHT
from warehouse_dispatch_coordinated import ATCS_K1, ATCS_K2, MIN_LEG_TIME, average_leg_travel_time, future_work
from warehouse_dispatch_core import simulate_dispatch
from warehouse_evaluation import due_time_for_order

# Swept against coordinated/OR-Tools across 4 scenario families x 15 seeds
# (default, hub bottleneck, express-heavy, large): 150/400/4 wins against
# coordinated on almost every seed (0-1 losses per family out of 15) and
# closes 14-33% of the remaining gap to OR-Tools' objective value, at up to
# ~2s runtime at the sliders' absolute maximum (60 orders, 5 aisles, 8
# nodes/aisle) - fast enough to run inline like the other three heuristics,
# no button/cooldown needed the way OR-Tools has. Doubling the budget again
# (300/800) only pushed gap-closure from ~14-26% to ~14-33% while roughly
# doubling runtime - clearly diminishing returns past this point.
GRASP_ITERATIONS = 150
RCL_SIZE = 4
LOCAL_SEARCH_MOVES = 400
BIAS_SCALE = 0.5  # fraction of p_bar a single perturbation can shift one leg's priority by

# Swept separately (0.0-2.0 minutes) on top of the above, same 4 families x
# 15 seeds: 0.75 min consistently pushed gap-closure from 14-33% to 25-39%
# in EVERY family (never a regression, unlike most windows tested alone on
# plain Koordiniert without GRASP's construction/local-search diversity
# underneath it) - runtime rises to ~3.9s at the sliders' absolute maximum
# (from ~2s), still acceptable to run inline. Windows above ~1.5 start
# giving some of the gain back (too much unjustified waiting).
LOOKAHEAD_WINDOW = 0.75


def _atcs_index(order, route, leg_index, idle_positions, now, network, handover_minutes, p_bar):
    """Same formula as warehouse_dispatch_coordinated.dispatch_coordinated's
    inner `priority` - kept as its own function here only because GRASP adds
    a bias term on top of it (see _make_priority)."""
    leg = route.legs[leg_index]
    p = max(leg.travel_time, MIN_LEG_TIME)
    future = future_work(route, leg_index, handover_minutes)
    nearest_transporter = min(
        (network.travel_time(leg.zone_id, position, leg.entry_node) for position in idle_positions),
        default=0.0,
    )
    due_time = due_time_for_order(order, route, handover_minutes)
    projected_completion = now + p + future
    slack = max(due_time - projected_completion, 0.0)
    weight = EXPRESS_WEIGHT if order.is_express else 1
    index = (
        (weight / p)
        * math.exp(-slack / (ATCS_K1 * p_bar))
        * math.exp(-nearest_transporter / (ATCS_K2 * p_bar))
    )
    return -index


def _make_priority(network, handover_minutes, p_bar, bias):
    def priority(order, route, leg_index, ready_time, idle_positions, now):
        base = _atcs_index(order, route, leg_index, idle_positions, now, network, handover_minutes, p_bar)
        return base + bias.get((order.order_id, leg_index), 0.0)

    return priority


def _objective(schedule, routes, orders, handover_minutes):
    """Weighted completion time + tardiness penalty - the objective
    OR-Tools' CP-SAT model minimizes (see warehouse_ortools_solver.py),
    unscaled and real-valued since GRASP has no need for CP-SAT's integer
    discretization."""
    orders_by_id = {o.order_id: o for o in orders}
    by_order = {}
    for a in schedule.assignments:
        by_order.setdefault(a.order_id, []).append(a)

    total = 0.0
    for order_id, legs in by_order.items():
        completion = max(a.end for a in legs)
        order = orders_by_id[order_id]
        route = routes[order_id]
        weight = EXPRESS_WEIGHT if order.is_express else 1
        due = due_time_for_order(order, route, handover_minutes)
        tardiness = max(completion - due, 0.0)
        total += weight * completion + TARDINESS_PENALTY_WEIGHT * tardiness
    return total


def _all_leg_keys(routes):
    return [(order_id, leg_index) for order_id, route in routes.items() for leg_index in range(len(route.legs))]


def dispatch_grasp(network, routes, orders, transporters_per_zone, handover_minutes, seed=0):
    rng = random.Random(seed)
    p_bar = average_leg_travel_time(routes)
    leg_keys = _all_leg_keys(routes)

    best_schedule = None
    best_score = math.inf
    for _ in range(GRASP_ITERATIONS):
        priority = _make_priority(network, handover_minutes, p_bar, {})
        schedule = simulate_dispatch(
            network, routes, orders, transporters_per_zone, handover_minutes, priority, "grasp",
            rng=rng, rcl_size=RCL_SIZE, lookahead_window=LOOKAHEAD_WINDOW,
        )
        score = _objective(schedule, routes, orders, handover_minutes)
        if score < best_score:
            best_score, best_schedule = score, schedule

    bias = {}
    for _ in range(LOCAL_SEARCH_MOVES):
        if not leg_keys:
            break
        key = leg_keys[rng.randrange(len(leg_keys))]
        previous = bias.get(key, 0.0)
        bias[key] = rng.uniform(-BIAS_SCALE * p_bar, BIAS_SCALE * p_bar)

        priority = _make_priority(network, handover_minutes, p_bar, bias)
        candidate = simulate_dispatch(
            network, routes, orders, transporters_per_zone, handover_minutes, priority, "grasp",
            lookahead_window=LOOKAHEAD_WINDOW,
        )
        score = _objective(candidate, routes, orders, handover_minutes)
        if score < best_score:
            best_score, best_schedule = score, candidate
        else:
            bias[key] = previous

    return best_schedule
