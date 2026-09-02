"""Decentralized greedy dispatch: each zone runs Shortest-Processing-Time
(SPT) locally - whenever one of its transporters frees up, it picks the
ready leg with the shortest travel time in ITS OWN zone. SPT is a
textbook-optimal rule for minimizing a single resource's own queue, but it
has no notion of which order a leg belongs to or how many transfers still
follow - exactly the "locally efficient, globally blind" behavior each
independently managed warehouse zone would show in practice.
"""

from warehouse_dispatch_core import simulate_dispatch


def _priority(order, route, leg_index, ready_time):
    return route.legs[leg_index].travel_time


def dispatch_greedy(routes, orders, transporters_per_zone, handover_minutes):
    return simulate_dispatch(routes, orders, transporters_per_zone, handover_minutes, _priority, "greedy")
