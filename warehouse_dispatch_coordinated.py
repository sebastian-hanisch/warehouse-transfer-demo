"""Coordinated dispatch: prioritizes orders by their position in the whole
warehouse-wide journey, not just the leg in front of a single zone.

Two combined rules, both needing visibility beyond one zone's own queue:

1. Continuation-first: a leg that is already the 2nd/3rd leg of an order -
   i.e. the order has already been handed off at least once - is served
   before any brand-new leg competing for the same transporter. This is
   what greedy/decentralized SPT lacks: SPT judges a leg purely by its own
   travel time, so a short fresh single-aisle order can jump the queue
   ahead of an order that is already waiting mid-transfer, deepening
   exactly the wait it just incurred.
2. Most-Work-Remaining (MWKR) as the tie-break within each tier: a classic
   multi-stage scheduling rule - among equally "continuation" or equally
   "fresh" legs, prefer the order with the most total travel time (across
   all its still-open legs and transfers) still ahead of it.
"""

from warehouse_dispatch_core import simulate_dispatch


def _remaining_work(route, leg_index, handover_minutes):
    remaining_legs = route.legs[leg_index:]
    travel = sum(leg.travel_time for leg in remaining_legs)
    remaining_transfers = max(len(remaining_legs) - 1, 0)
    return travel + remaining_transfers * handover_minutes


def dispatch_coordinated(routes, orders, transporters_per_zone, handover_minutes):
    def priority(order, route, leg_index, ready_time):
        continuation_tier = 0 if leg_index > 0 else 1  # continuations first
        remaining = _remaining_work(route, leg_index, handover_minutes)
        return (continuation_tier, -remaining)

    return simulate_dispatch(routes, orders, transporters_per_zone, handover_minutes, priority, "coordinated")
