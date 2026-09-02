import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from conftest import build_scenario
from warehouse_dispatch_baseline import dispatch_baseline
from warehouse_dispatch_coordinated import dispatch_coordinated
from warehouse_dispatch_greedy import dispatch_greedy
from warehouse_evaluation import evaluate_schedule

DISPATCHERS = [dispatch_baseline, dispatch_greedy, dispatch_coordinated]
HANDOVER = 1.0


def _assert_no_double_booking(schedule, transporters_per_zone):
    # The transporter is unavailable to anyone else from the moment it is
    # dispatched (start of repositioning), not just from when it starts
    # carrying the leg - so compare against start - repositioning_time.
    by_transporter = {}
    for a in schedule.assignments:
        by_transporter.setdefault(a.transporter_id, []).append(a)
    for transporter_id, legs in by_transporter.items():
        legs = sorted(legs, key=lambda a: a.start)
        for prev, nxt in zip(legs, legs[1:]):
            nxt_dispatch_time = nxt.start - nxt.repositioning_time
            assert prev.end <= nxt_dispatch_time + 1e-9, f"overlap on {transporter_id}: {prev} vs {nxt}"


def _assert_capacity_never_exceeded(schedule, transporters_per_zone):
    # sweep-line check independent of the transporter labeling. A
    # transporter occupies the zone's capacity from dispatch (start of
    # repositioning) through the end of the loaded leg.
    # Times are rounded before comparison: `start - repositioning_time` is a
    # float reconstruction of a dispatch time that was itself computed as
    # `now + repositioning_time` during simulation - algebraically the same
    # value, but not bit-for-bit after the round trip, which without
    # rounding can make the same transporter's own end/next-dispatch look
    # like a femtosecond overlap with itself.
    by_zone = {}
    for a in schedule.assignments:
        by_zone.setdefault(a.zone_id, []).append(a)
    for zone_id, legs in by_zone.items():
        events = []
        for a in legs:
            events.append((round(a.start - a.repositioning_time, 6), 1))
            events.append((round(a.end, 6), -1))
        events.sort(key=lambda e: (e[0], e[1]))  # ends before starts at same time
        concurrent = 0
        for _, delta in events:
            concurrent += delta
            assert concurrent <= transporters_per_zone[zone_id], f"zone {zone_id} over capacity"


def _assert_transfer_precedence(schedule, routes, orders, handover_minutes):
    by_order = {}
    for a in schedule.assignments:
        by_order.setdefault(a.order_id, []).append(a)
    orders_by_id = {o.order_id: o for o in orders}
    for order_id, legs in by_order.items():
        legs = sorted(legs, key=lambda a: a.leg_index)
        order = orders_by_id[order_id]
        assert legs[0].start >= order.release_time - 1e-9
        for prev, nxt in zip(legs, legs[1:]):
            assert nxt.start >= prev.end + handover_minutes - 1e-9


def _assert_all_legs_covered(schedule, routes, orders):
    by_order = {}
    for a in schedule.assignments:
        by_order.setdefault(a.order_id, []).append(a)
    for order in orders:
        route = routes[order.order_id]
        assert order.order_id in by_order
        assert len(by_order[order.order_id]) == len(route.legs)
        indices = sorted(a.leg_index for a in by_order[order.order_id])
        assert indices == list(range(len(route.legs)))


def _assert_repositioning_matches_network_distance(schedule, network, check_first_leg=True):
    """The whole point of repositioning: a transporter's next assignment
    must reflect the REAL travel time from wherever its previous leg left
    it. check_first_leg also checks a transporter's very first assignment
    against its zone's home node - true for the heuristics (every
    transporter starts there), but OR-Tools deliberately does not charge
    that one-off cost (see warehouse_ortools_solver.py's documented
    simplification), so its own test passes check_first_leg=False."""
    by_transporter = {}
    for a in schedule.assignments:
        by_transporter.setdefault(a.transporter_id, []).append(a)
    for transporter_id, legs in by_transporter.items():
        legs = sorted(legs, key=lambda a: a.start)
        if check_first_leg:
            zone_id = legs[0].zone_id
            home = network.zones[zone_id].nodes[0]
            expected_first = network.travel_time(zone_id, home, legs[0].entry_node)
            assert legs[0].repositioning_time == pytest.approx(expected_first, abs=1e-6)
        for prev, nxt in zip(legs, legs[1:]):
            expected = network.travel_time(nxt.zone_id, prev.exit_node, nxt.entry_node)
            assert nxt.repositioning_time == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("dispatcher", DISPATCHERS)
def test_dispatch_invariants_hold(dispatcher):
    net, orders, routes, transporters_per_zone = build_scenario(n_orders=25, transporters_per_aisle=2, transporters_hub=2)
    schedule = dispatcher(net, routes, orders, transporters_per_zone, HANDOVER)
    _assert_all_legs_covered(schedule, routes, orders)
    _assert_capacity_never_exceeded(schedule, transporters_per_zone)
    _assert_no_double_booking(schedule, transporters_per_zone)
    _assert_transfer_precedence(schedule, routes, orders, HANDOVER)
    _assert_repositioning_matches_network_distance(schedule, net)


@pytest.mark.parametrize("dispatcher", DISPATCHERS)
def test_single_transporter_scenario_still_feasible(dispatcher):
    net, orders, routes, transporters_per_zone = build_scenario(
        n_orders=15, transporters_per_aisle=1, transporters_hub=1
    )
    schedule = dispatcher(net, routes, orders, transporters_per_zone, HANDOVER)
    _assert_all_legs_covered(schedule, routes, orders)
    _assert_capacity_never_exceeded(schedule, transporters_per_zone)
    _assert_transfer_precedence(schedule, routes, orders, HANDOVER)
    _assert_repositioning_matches_network_distance(schedule, net)


def test_coordinated_reduces_transfer_wait_under_hub_bottleneck():
    """The core hook: with a single-transporter hub bottleneck and many
    cross-zone orders, greedy/decentralized SPT dispatch judges legs only by
    their own travel time and lets short same-aisle legs jump the queue
    ahead of hub transfers, while the coordinated dispatcher (an ATCS index
    factoring in due-date slack and setup/repositioning distance alongside
    SPT) prioritizes orders under real pressure. Coordinated should not
    create more total transfer waiting than greedy on the same instance."""
    net, orders, routes, transporters_per_zone = build_scenario(
        n_aisles=3, hub_nodes=1, transporters_per_aisle=2, transporters_hub=1,
        n_orders=30, horizon_minutes=20.0, cross_zone_share=0.8, seed=7,
    )
    greedy_schedule = dispatch_greedy(net, routes, orders, transporters_per_zone, HANDOVER)
    coordinated_schedule = dispatch_coordinated(net, routes, orders, transporters_per_zone, HANDOVER)

    greedy_eval = evaluate_schedule(greedy_schedule, routes, orders, HANDOVER)
    coordinated_eval = evaluate_schedule(coordinated_schedule, routes, orders, HANDOVER)

    assert coordinated_eval.total_transfer_wait <= greedy_eval.total_transfer_wait


def test_coordinated_does_not_lose_on_lead_time_in_aggregate():
    """Regression guard for a real design mistake: an earlier version of
    coordinated (pure "shortest total remaining route first", no weight on
    the current leg) reliably cut transfer wait but, swept over hundreds of
    random scenarios, LOST to greedy on Gesamtdurchlaufzeit more often than
    it won - throwing away SPT's per-resource optimality cost more locally
    than the global view gained. The current priority is an ATCS
    (Apparent-Tardiness-Cost-with-Setups) index, swept the same way (4/40
    losses, total_diff -907 at the default scenario family when last
    checked) - not a single-instance check, too noisy for one seed to be a
    reliable signal, learned the hard way in the sibling VRP demo."""
    total_diff = 0.0
    losses = 0
    n_seeds = 40
    for seed in range(n_seeds):
        net, orders, routes, transporters_per_zone = build_scenario(seed=seed)
        greedy_eval = evaluate_schedule(
            dispatch_greedy(net, routes, orders, transporters_per_zone, HANDOVER), routes, orders, HANDOVER
        )
        coordinated_eval = evaluate_schedule(
            dispatch_coordinated(net, routes, orders, transporters_per_zone, HANDOVER), routes, orders, HANDOVER
        )
        diff = coordinated_eval.total_lead_time - greedy_eval.total_lead_time
        total_diff += diff
        if diff > 1e-6:
            losses += 1

    assert total_diff <= 0.0
    assert losses <= n_seeds * 0.3


def test_coordinated_improves_express_on_time_rate_vs_greedy():
    """Express orders are the one dispatch signal greedy deliberately never
    looks at (by design - it stays pure local SPT). Coordinated weighs an
    express order's ATCS index up (EXPRESS_WEIGHT in the w/p term, the same
    constant OR-Tools uses), so it should reliably get better on-time
    performance for express orders than greedy under contention. Checked
    across many seeds, not a single instance - an occasional single-seed
    loss is expected noise (14 wins / 2 losses / 4 ties over 20 seeds when
    this was last swept), not a regression to chase to zero; the aggregate
    direction is what matters."""
    wins = losses = 0
    n_seeds = 20
    for seed in range(n_seeds):
        net, orders, routes, transporters_per_zone = build_scenario(
            n_aisles=3, hub_nodes=1, transporters_per_aisle=1, transporters_hub=1,
            n_orders=30, horizon_minutes=20.0, cross_zone_share=0.8, express_share=0.3, seed=seed,
        )
        greedy_eval = evaluate_schedule(
            dispatch_greedy(net, routes, orders, transporters_per_zone, HANDOVER), routes, orders, HANDOVER
        )
        coordinated_eval = evaluate_schedule(
            dispatch_coordinated(net, routes, orders, transporters_per_zone, HANDOVER), routes, orders, HANDOVER
        )
        diff = coordinated_eval.on_time_rate_express - greedy_eval.on_time_rate_express
        if diff > 1e-9:
            wins += 1
        elif diff < -1e-9:
            losses += 1

    assert wins > losses
    assert losses <= n_seeds * 0.2
