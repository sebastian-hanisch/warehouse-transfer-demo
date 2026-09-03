"""Coordinated dispatch: an Apparent-Tardiness-Cost-with-Setups (ATCS)
priority index (Vepsalainen & Morton 1987; setup extension e.g. Lee,
Bhaskaran & Pinedo 1997) - the standard dispatching rule from the
scheduling literature for exactly this problem's structure: parallel
machines (transporters per zone), sequence-dependent setup times
(repositioning), weighted jobs, due dates. Replaced an earlier, hand-swept
linear formula (three independently-tuned additive weights, see git
history) with this literature-backed one on 2026-09-02, after being asked
directly whether the linear formula was really how this would be built
from scratch - it wasn't; ATCS is.

    I(o,l) = (w_o / p) * exp(-slack / (K1 * p_bar)) * exp(-s / (K2 * p_bar))

- p = current leg's own travel time (the "processing time"; SPT-optimal
  rule falls out of the w/p term alone, same as greedy's core idea).
- w_o = EXPRESS_WEIGHT if express else 1 - the SAME constant OR-Tools uses
  in its objective (`warehouse_ortools_solver.py`), not a second,
  independently-tuned number for the same idea (EXPRESS_PRIORITY_FACTOR
  used to be that second number - a known, now-fixed inconsistency).
- slack = due_time_for_order() minus an optimistic projected completion
  ("now" + this leg's travel + remaining route) - due date pressure,
  looking past just this leg (classic ATC uses only the current
  operation's due date; this problem needs the whole remaining route
  accounted for, since a "leg" is one operation of a multi-leg job, not
  the whole job).
- s = distance to the nearest currently-idle transporter - the
  sequence-dependent setup time (repositioning) ATCS was extended to
  handle.
- p_bar = average leg travel time across the whole instance, computed
  once - the scale normalizer for BOTH exponentials, since a
  repositioning distance and a leg's own travel time are literally the
  same kind of quantity here (both are node-to-node travel times within
  one zone), not two different units needing separate normalizers.
- K1, K2 = look-ahead scaling constants, swept empirically (see below) -
  small K means the exponential decays fast, i.e. only genuinely urgent
  slack/setup values matter; large K flattens the term toward
  indifference. I(o,l) is "higher = more urgent" in the literature's own
  convention; negated below since this codebase's convention is "lower
  score = served first".

Baseline and greedy remain blind to due dates and express status
entirely, by design - see their own module docstrings.
"""

import math

from warehouse_constants import EXPRESS_WEIGHT
from warehouse_dispatch_core import simulate_dispatch
from warehouse_evaluation import due_time_for_order

# Swept a grid (0.05-2.0) against the scenario families used throughout
# this project (see project memory), not just the default seed - K2 in
# particular needs to be small: a weakly-decaying setup term (large K2)
# performed BADLY (lost to greedy in 20-33/40 seeds), the repositioning-
# awareness needs to bite hard to matter, echoing the earlier
# REPOSITIONING_WEIGHT lesson from the linear formula this replaced.
ATCS_K1 = 1.0  # due-date look-ahead scale
ATCS_K2 = 0.15  # setup-time (repositioning) look-ahead scale

# Not underscore-private: warehouse_dispatch_grasp.py imports these three to
# build its construction-phase priority on the exact same ATCS formula
# (single source of truth - the alternative, re-deriving the formula in the
# GRASP module, risks silent drift between the two).
MIN_LEG_TIME = 1e-6  # guards the w/p division; real legs are never this short


def future_work(route, leg_index, handover_minutes):
    """Total remaining travel time + handovers AFTER the current leg."""
    remaining_legs = route.legs[leg_index + 1 :]
    if not remaining_legs:
        return 0.0
    travel = sum(leg.travel_time for leg in remaining_legs)
    return travel + len(remaining_legs) * handover_minutes


def average_leg_travel_time(routes):
    travels = [leg.travel_time for route in routes.values() for leg in route.legs]
    return max(sum(travels) / len(travels), MIN_LEG_TIME) if travels else 1.0


def dispatch_coordinated(network, routes, orders, transporters_per_zone, handover_minutes):
    p_bar = average_leg_travel_time(routes)

    def priority(order, route, leg_index, ready_time, idle_positions, now):
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

    return simulate_dispatch(network, routes, orders, transporters_per_zone, handover_minutes, priority, "coordinated")
