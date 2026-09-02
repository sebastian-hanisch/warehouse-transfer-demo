"""Coordinated dispatch: SPT on the current leg (like greedy), plus two
small weighted look-aheads - how much of the order's journey is still left
afterwards, and how far the nearest idle transporter actually is.

DESIGN GOAL (explicit, so future tuning doesn't drift from it):
Gesamtdurchlaufzeit is the primary objective - FUTURE_WORK_WEIGHT and
REPOSITIONING_WEIGHT both keep SPT (the term proven optimal for minimizing
total completion time on a single resource) dominant, only nudging it.
Umstiegs-Wartezeit reduction is secondary: real and consistently achieved,
but not optimized directly, and never allowed to regress the primary
objective in aggregate. Both are covered by their own aggregate regression
test (`test_coordinated_does_not_lose_on_lead_time_in_aggregate`,
`test_coordinated_reduces_transfer_wait_under_hub_bottleneck`) precisely
because neither is a single hard-coded number to assert against.

Pure SPT (shortest processing time first) is the classic, provably optimal
rule for minimizing the sum of completion times on a SINGLE resource.
Greedy/decentralized dispatch already applies that idea, but only within
one zone's own queue - it has no visibility into an order's journey beyond
the current leg, NOR into where its own idle transporters currently sit.
That second blind spot only matters once transporters must physically
reposition (deadhead) between legs - before repositioning existed in this
model, ranking purely by remaining route length was enough to reliably beat
greedy. Once transporters had to travel empty between assignments, that
FUTURE_WORK_WEIGHT-only version started LOSING to greedy on
Gesamtdurchlaufzeit more often than it won, swept over hundreds of random
scenarios: greedy's plain SPT, while blind to positioning, was still often
"good enough" locally, while ignoring positioning entirely let coordinated
send a transporter clear across a zone for a nominally-short leg. Adding
REPOSITIONING_WEIGHT - a small preference for legs reachable quickly from a
currently idle transporter - fixed this decisively: swept the same way,
this now reliably beats greedy on BOTH Gesamtdurchlaufzeit and
Umstiegs-Wartezeit, by a wide margin, across every scenario family tested
(0-3 losses out of 60 seeds per family, not just one lucky example).

Express orders (order.is_express) get their priority score scaled down by
EXPRESS_PRIORITY_FACTOR, consistently moving them ahead of similar-priority
non-express legs while leaving the rest of the ordering intact. Baseline
and greedy deliberately do NOT look at is_express at all - the point of the
comparison is that a naive/local dispatcher ignores stated priorities even
when they exist, the same complaint real warehouse operators have about
purely FCFS or purely local systems.

SLACK-BASED PRIORITY (added 2026-09-02, revised twice same day): the
score is further adjusted by SLACK_WEIGHT times the order's remaining
slack (capped above at SLACK_CAP_MINUTES), where slack =
due_time_for_order() minus an optimistic projected completion
("ready_time + current_leg + future" - what it'd be if everything from
here on went smoothly, no further queueing). Less slack (or negative -
already behind) means a lower score, served sooner; comfortable slack
means a slightly higher score, nudged back a little to make room.

Two real mistakes were made and caught while building this, in order:
(1) First version was GATED (`max(0, ...)`, only active once already
projected late), mirroring OR-Tools' tardiness term under one constant
shared with `warehouse_ortools_solver.py`. Instrumented and swept it: it
was almost completely inert here - by the time an order's optimistic
projection crosses its deadline, it has usually already waited so long
that it's the ONLY ready leg left in its queue (everything else has long
since been served), so no penalty weight can reorder anything - verified
directly (byte-identical schedules from weight 0 to 9999). OR-Tools'
gated version does work (it optimizes globally, not leg-by-leg), so the
two methods now use genuinely DIFFERENT mechanisms and DIFFERENT
constants (SLACK_WEIGHT here vs. TARDINESS_PENALTY_WEIGHT there) - unlike
EXPRESS_PRIORITY_FACTOR/EXPRESS_WEIGHT, two independently-tuned numbers
for the same idea with no such empirical justification, this split is the
result of one mechanism demonstrably not working, not an unexamined
inconsistency.
(2) Fixing (1) by switching to an ungated, continuous term, a SIGN ERROR
(`score - weight*slack` instead of `score + weight*slack`) meant more
slack - i.e. LESS urgency - produced a LOWER score, prioritizing the most
comfortable orders and deprioritizing the most urgent ones; caught only
because the aggregate sweep showed tardiness getting WORSE as the weight
increased, the opposite of the intended direction, which made the sign
flip obvious.
With both fixed and swept properly (40 seeds x 4 scenario families):
total tardiness improves a little in low-congestion scenarios, but is
roughly flat-to-slightly-worse in the demo's showcase congested/express-
heavy scenarios (a real, honest limit of a myopic per-leg heuristic:
pulling one order forward necessarily pushes another back, and in a
congested system that's often a wash or worse in aggregate, similar in
spirit to the earlier pure-SRPT lesson). SLACK_CAP_MINUTES keeps the
"comfortable orders get deprioritized" side of the term from growing
unbounded, which is what kept Gesamtdurchlaufzeit regression small and
express on-time rate essentially unaffected (0-1 losses per 40 seeds) at
the chosen weight - a low-risk, small-but-real nudge, not a strong
guarantee. Applied AFTER express scaling rather than inside it, so the
two signals stay independent rather than compounding. Baseline and greedy
remain blind to due dates entirely, same as to is_express, by design.
"""

from warehouse_constants import EXPRESS_PRIORITY_FACTOR
from warehouse_dispatch_core import simulate_dispatch
from warehouse_evaluation import due_time_for_order

# All three weights are relative to the current leg's own duration (weight
# 1.0, implicit). Swept empirically across several scenario families (see
# git history / project memory) - representative, robust choices, not
# knife-edge optima; values within roughly +/-30% perform similarly.
FUTURE_WORK_WEIGHT = 0.1
REPOSITIONING_WEIGHT = 1.5
SLACK_WEIGHT = 0.15
SLACK_CAP_MINUTES = 5.0


def _future_work(route, leg_index, handover_minutes):
    """Total remaining travel time + handovers AFTER the current leg."""
    remaining_legs = route.legs[leg_index + 1 :]
    if not remaining_legs:
        return 0.0
    travel = sum(leg.travel_time for leg in remaining_legs)
    return travel + len(remaining_legs) * handover_minutes


def dispatch_coordinated(network, routes, orders, transporters_per_zone, handover_minutes):
    def priority(order, route, leg_index, ready_time, idle_positions):
        leg = route.legs[leg_index]
        current_leg = leg.travel_time
        future = _future_work(route, leg_index, handover_minutes)
        nearest_transporter = min(
            (network.travel_time(leg.zone_id, position, leg.entry_node) for position in idle_positions),
            default=0.0,
        )
        score = current_leg + FUTURE_WORK_WEIGHT * future + REPOSITIONING_WEIGHT * nearest_transporter
        score = score * EXPRESS_PRIORITY_FACTOR if order.is_express else score

        due_time = due_time_for_order(order, route, handover_minutes)
        slack = due_time - (ready_time + current_leg + future)
        return score + SLACK_WEIGHT * min(slack, SLACK_CAP_MINUTES)

    return simulate_dispatch(network, routes, orders, transporters_per_zone, handover_minutes, priority, "coordinated")
