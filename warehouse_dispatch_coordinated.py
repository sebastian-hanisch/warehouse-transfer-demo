"""Coordinated dispatch: SPT on the current leg (like greedy), plus a small
weighted look-ahead at how much of the order's journey is still left
afterwards - a "mostly local, slightly global" priority rule.

DESIGN GOAL (explicit, so future tuning doesn't drift from it):
Gesamtdurchlaufzeit is the primary objective - FUTURE_WORK_WEIGHT keeps SPT
(the term proven optimal for minimizing total completion time on a single
resource) dominant for exactly that reason. Umstiegs-Wartezeit reduction is
secondary: real and consistently achieved (see `_future_work`'s effect and
`test_coordinated_reduces_transfer_wait_under_hub_bottleneck`), but not
optimized directly, and never allowed to regress the primary objective in
aggregate (`test_coordinated_does_not_lose_on_lead_time_in_aggregate`).
Both are covered by their own aggregate regression test precisely because
neither is a single hard-coded number to assert against.

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

Express orders (order.is_express) get their priority score scaled down by
EXPRESS_PRIORITY_FACTOR, consistently moving them ahead of similar-priority
non-express legs while leaving the SPT + future-work ordering intact within
each group. Baseline and greedy deliberately do NOT look at is_express at
all - the point of the comparison is that a naive/local dispatcher ignores
stated priorities even when they exist, the same complaint real warehouse
operators have about purely FCFS or purely local systems.
"""

from warehouse_constants import EXPRESS_PRIORITY_FACTOR
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
        score = current_leg + FUTURE_WORK_WEIGHT * future
        return score * EXPRESS_PRIORITY_FACTOR if order.is_express else score

    return simulate_dispatch(routes, orders, transporters_per_zone, handover_minutes, priority, "coordinated")
