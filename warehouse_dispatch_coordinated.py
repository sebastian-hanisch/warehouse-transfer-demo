"""Coordinated dispatch: SPT on the current leg (like greedy), plus a small
weighted look-ahead at how much of the order's journey is still left
afterwards - a "mostly local, slightly global" priority rule.

Pure SPT (shortest processing time first) is the classic, provably optimal
rule for minimizing the sum of completion times on a SINGLE resource.
Greedy/decentralized dispatch already applies that idea, but only within
one zone's own queue - it has no visibility into an order's journey beyond
the current leg. The natural next step, ranking purely by an order's TOTAL
remaining travel time (tried first here - see git history), turned out to
NOT reliably beat greedy on total completion time: swept over hundreds of
random scenarios, it lost to greedy on Gesamtdurchlaufzeit more often than
it won, because SPT's per-resource optimality is real and throwing it away
completely costs more locally than the global view gains. A small, additive
correction keeps SPT as the dominant signal (so each zone still queues
efficiently) and only nudges the ranking by how much MORE travel the order
still needs after this leg - enough to stop an order that is nearly done
from being repeatedly passed over by fresher orders with a marginally
shorter current leg, without discarding SPT's core benefit. Swept over the
same hundreds of scenarios, this reliably ties-or-beats greedy on BOTH
Gesamtdurchlaufzeit and Umstiegs-Wartezeit - in the two scenarios shown by
default in the app it lands exactly on the OR-Tools optimum.
"""

from warehouse_dispatch_core import simulate_dispatch

# Weight on the order's remaining journey AFTER the current leg, relative to
# the current leg's own duration (weight 1.0, implicit). Swept empirically
# (see git history / project memory) - values in roughly [0.05, 0.15] all
# perform about the same; 0.1 is a representative, round choice, not a
# knife-edge optimum.
FUTURE_WORK_WEIGHT = 0.1


def _future_work(route, leg_index, handover_minutes):
    """Total remaining travel time + handovers AFTER the current leg."""
    remaining_legs = route.legs[leg_index + 1 :]
    if not remaining_legs:
        return 0.0
    travel = sum(leg.travel_time for leg in remaining_legs)
    return travel + len(remaining_legs) * handover_minutes


def dispatch_coordinated(routes, orders, transporters_per_zone, handover_minutes):
    def priority(order, route, leg_index, ready_time):
        current_leg = route.legs[leg_index].travel_time
        future = _future_work(route, leg_index, handover_minutes)
        return current_leg + FUTURE_WORK_WEIGHT * future

    return simulate_dispatch(routes, orders, transporters_per_zone, handover_minutes, priority, "coordinated")
