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
    by_transporter = {}
    for a in schedule.assignments:
        by_transporter.setdefault(a.transporter_id, []).append(a)
    for transporter_id, legs in by_transporter.items():
        legs = sorted(legs, key=lambda a: a.start)
        for prev, nxt in zip(legs, legs[1:]):
            assert prev.end <= nxt.start + 1e-9, f"overlap on {transporter_id}: {prev} vs {nxt}"


def _assert_capacity_never_exceeded(schedule, transporters_per_zone):
    # sweep-line check independent of the transporter labeling
    by_zone = {}
    for a in schedule.assignments:
        by_zone.setdefault(a.zone_id, []).append(a)
    for zone_id, legs in by_zone.items():
        events = []
        for a in legs:
            events.append((a.start, 1))
            events.append((a.end, -1))
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


@pytest.mark.parametrize("dispatcher", DISPATCHERS)
def test_dispatch_invariants_hold(dispatcher):
    net, orders, routes, transporters_per_zone = build_scenario(n_orders=25, transporters_per_aisle=2, transporters_hub=2)
    schedule = dispatcher(routes, orders, transporters_per_zone, HANDOVER)
    _assert_all_legs_covered(schedule, routes, orders)
    _assert_capacity_never_exceeded(schedule, transporters_per_zone)
    _assert_no_double_booking(schedule, transporters_per_zone)
    _assert_transfer_precedence(schedule, routes, orders, HANDOVER)


@pytest.mark.parametrize("dispatcher", DISPATCHERS)
def test_single_transporter_scenario_still_feasible(dispatcher):
    net, orders, routes, transporters_per_zone = build_scenario(
        n_orders=15, transporters_per_aisle=1, transporters_hub=1
    )
    schedule = dispatcher(routes, orders, transporters_per_zone, HANDOVER)
    _assert_all_legs_covered(schedule, routes, orders)
    _assert_capacity_never_exceeded(schedule, transporters_per_zone)
    _assert_transfer_precedence(schedule, routes, orders, HANDOVER)


def test_coordinated_reduces_transfer_wait_under_hub_bottleneck():
    """The core hook: with a single-transporter hub bottleneck and many
    cross-zone orders, greedy/decentralized SPT dispatch lets short
    same-aisle legs jump the queue ahead of hub transfers, while the
    coordinated (most-work-remaining) dispatcher prioritizes orders that
    still have a transfer ahead of them. Coordinated should not create
    more total transfer waiting than greedy on the same instance."""
    net, orders, routes, transporters_per_zone = build_scenario(
        n_aisles=3, hub_nodes=1, transporters_per_aisle=2, transporters_hub=1,
        n_orders=30, horizon_minutes=20.0, cross_zone_share=0.8, seed=7,
    )
    greedy_schedule = dispatch_greedy(routes, orders, transporters_per_zone, HANDOVER)
    coordinated_schedule = dispatch_coordinated(routes, orders, transporters_per_zone, HANDOVER)

    greedy_eval = evaluate_schedule(greedy_schedule, routes, orders, transporters_per_zone, HANDOVER)
    coordinated_eval = evaluate_schedule(coordinated_schedule, routes, orders, transporters_per_zone, HANDOVER)

    assert coordinated_eval.total_transfer_wait <= greedy_eval.total_transfer_wait
