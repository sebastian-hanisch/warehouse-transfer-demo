"""Baseline: unoptimized first-come-first-served dispatch. No priority
logic at all - whichever leg became ready first gets served first,
regardless of zone or downstream consequences. This is the "no
optimization" comparison point, analogous to an unoptimized starting
route in the sibling VRP demo.
"""

from warehouse_dispatch_core import simulate_dispatch


def _priority(order, route, leg_index, ready_time):
    return 0.0


def dispatch_baseline(routes, orders, transporters_per_zone, handover_minutes):
    return simulate_dispatch(routes, orders, transporters_per_zone, handover_minutes, _priority, "baseline")
