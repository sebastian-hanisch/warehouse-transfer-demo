"""Decentralized greedy dispatch: each zone runs Shortest-Processing-Time
(SPT) locally - whenever a transporter is available, it picks the ready leg
with the shortest NOMINAL travel time in ITS OWN zone. SPT is a
textbook-optimal rule for minimizing a single resource's own queue, but it
has no notion of which order a leg belongs to, how many transfers still
follow, or where its own idle transporters currently sit (`idle_positions`
is accepted but deliberately unused) - it can send a transporter clear
across the zone for a nominally "short" leg while a much closer one waits,
exactly the "locally efficient, globally blind" behavior each independently
managed warehouse zone would show in practice.
"""

from warehouse_dispatch_core import simulate_dispatch


def _priority(order, route, leg_index, ready_time, idle_positions):
    return route.legs[leg_index].travel_time


def dispatch_greedy(network, routes, orders, transporters_per_zone, handover_minutes):
    return simulate_dispatch(network, routes, orders, transporters_per_zone, handover_minutes, _priority, "greedy")
