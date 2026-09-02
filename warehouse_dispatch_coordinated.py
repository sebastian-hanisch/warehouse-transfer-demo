"""Coordinated dispatch: Shortest-Remaining-Work-First (SRPT) applied to an
order's ENTIRE remaining journey, not just the leg in front of a single
zone - the natural multi-stage generalization of SPT for minimizing total
completion time (Gesamtdurchlaufzeit).

For a single resource, SPT (shortest processing time first) is the classic,
provably optimal rule for minimizing the sum of completion times. Greedy/
decentralized dispatch already applies that idea, but only to the CURRENT
leg's own travel time - it has no visibility into whether an order is
almost done (little work left) or has barely started (lots of work left),
because that requires knowing the order's full route across zones. An order
one leg away from delivery and an order that just started can both offer a
short CURRENT leg to the same zone; picking by current-leg duration alone
is a coin flip between them, even though finishing the near-complete order
first is what actually minimizes total completion time (it turns "pending"
into "done" fastest, the same reasoning behind SRPT). Coordinated ranks by
TOTAL remaining travel time (current + all future legs + handovers) instead
- an order close to finishing its journey is served before one that still
has most of its journey ahead, regardless of which zone either happens to
be in right now.
"""

from warehouse_dispatch_core import simulate_dispatch


def _remaining_work(route, leg_index, handover_minutes):
    remaining_legs = route.legs[leg_index:]
    travel = sum(leg.travel_time for leg in remaining_legs)
    remaining_transfers = max(len(remaining_legs) - 1, 0)
    return travel + remaining_transfers * handover_minutes


def dispatch_coordinated(routes, orders, transporters_per_zone, handover_minutes):
    def priority(order, route, leg_index, ready_time):
        return _remaining_work(route, leg_index, handover_minutes)  # ascending: least remaining work first

    return simulate_dispatch(routes, orders, transporters_per_zone, handover_minutes, priority, "coordinated")
