import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from warehouse_constants import DUE_DATE_BUFFER_MINUTES, DUE_DATE_FACTOR
from warehouse_dispatch_core import LegAssignment, Schedule
from warehouse_demand import Order
from warehouse_evaluation import evaluate_schedule
from warehouse_routing import Leg, Route

HANDOVER = 1.0


def test_evaluation_on_hand_built_example():
    # Order 0: single leg in aisle_0, travel_time 3, release 0 -> starts at 0 (no wait), ends at 3.
    # Order 1: two legs (aisle_1 -> hub), release 0.
    #   leg0: travel 2, scheduled start 0 -> end 2. ready_time for leg1 = 2 + handover(1) = 3.
    #   leg1: travel 4, but transporter only free at 5 -> actual start 5 (2 minutes of transfer wait).
    routes = {
        0: Route(order_id=0, legs=[Leg("aisle_0", "n1", "n2", 3.0)]),
        1: Route(order_id=1, legs=[Leg("aisle_1", "n3", "T", 2.0), Leg("hub", "T", "n4", 4.0)]),
    }
    orders = [
        Order(0, "n1", "aisle_0", "n2", "aisle_0", release_time=0.0),
        Order(1, "n3", "aisle_1", "n4", "hub", release_time=0.0),
    ]
    assignments = [
        LegAssignment(order_id=0, leg_index=0, zone_id="aisle_0", entry_node="n1", exit_node="n2",
                      start=0.0, end=3.0, ready_time=0.0, transporter_id="aisle_0#0"),
        LegAssignment(order_id=1, leg_index=0, zone_id="aisle_1", entry_node="n3", exit_node="T",
                      start=0.0, end=2.0, ready_time=0.0, transporter_id="aisle_1#0"),
        LegAssignment(order_id=1, leg_index=1, zone_id="hub", entry_node="T", exit_node="n4",
                      start=5.0, end=9.0, ready_time=3.0, transporter_id="hub#0"),
    ]
    schedule = Schedule(method="test", assignments=assignments)
    transporters_per_zone = {"aisle_0": 1, "aisle_1": 1, "hub": 1}

    result = evaluate_schedule(schedule, routes, orders, transporters_per_zone, HANDOVER)

    by_id = {r.order_id: r for r in result.orders}
    assert by_id[0].completion_time == 3.0
    assert by_id[0].lead_time == 3.0
    assert by_id[0].transfer_wait == 0.0
    assert by_id[0].n_transfers == 0

    assert by_id[1].completion_time == 9.0
    assert by_id[1].lead_time == 9.0
    assert by_id[1].transfer_wait == 2.0  # 5 - 3
    assert by_id[1].n_transfers == 1

    assert result.makespan == 9.0
    assert result.total_lead_time == 12.0
    assert result.avg_lead_time == 6.0
    assert result.total_transfer_wait == 2.0

    # due dates: order 0 minimal route time = 3 (no transfers)
    expected_due_0 = 0.0 + DUE_DATE_FACTOR * 3.0 + DUE_DATE_BUFFER_MINUTES
    assert by_id[0].due_time == expected_due_0
    assert by_id[0].on_time is True

    # order 1 minimal route time = 2 + 4 + 1*handover = 7
    expected_due_1 = 0.0 + DUE_DATE_FACTOR * 7.0 + DUE_DATE_BUFFER_MINUTES
    assert by_id[1].due_time == expected_due_1
    assert by_id[1].on_time is (9.0 <= expected_due_1)


def test_zone_utilization_matches_busy_fraction():
    routes = {0: Route(order_id=0, legs=[Leg("aisle_0", "n1", "n2", 4.0)])}
    orders = [Order(0, "n1", "aisle_0", "n2", "aisle_0", release_time=0.0)]
    assignments = [
        LegAssignment(order_id=0, leg_index=0, zone_id="aisle_0", entry_node="n1", exit_node="n2",
                      start=0.0, end=4.0, ready_time=0.0, transporter_id="aisle_0#0"),
    ]
    schedule = Schedule(method="test", assignments=assignments)
    transporters_per_zone = {"aisle_0": 2}
    result = evaluate_schedule(schedule, routes, orders, transporters_per_zone, HANDOVER)
    # makespan = 4, busy_time = 4, capacity = 2 -> utilization = 4 / (2*4) = 0.5
    assert result.zone_utilization["aisle_0"] == 0.5


def test_no_orders_returns_neutral_defaults():
    schedule = Schedule(method="test", assignments=[])
    result = evaluate_schedule(schedule, {}, [], {"aisle_0": 1}, HANDOVER)
    assert result.avg_lead_time == 0.0
    assert result.on_time_rate == 1.0
    assert result.makespan == 0.0
