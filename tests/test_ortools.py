import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ortools.sat.python import cp_model

from conftest import build_scenario
from warehouse_demand import Order
from warehouse_dispatch_coordinated import dispatch_coordinated
from warehouse_evaluation import evaluate_schedule
from warehouse_ortools_solver import solve_ortools
from warehouse_routing import Leg, Route
from test_dispatch import (
    _assert_all_legs_covered,
    _assert_capacity_never_exceeded,
    _assert_transfer_precedence,
)

HANDOVER = 1.0


def test_ortools_finds_feasible_solution_and_respects_constraints():
    net, orders, routes, transporters_per_zone = build_scenario(
        n_orders=10, transporters_per_aisle=1, transporters_hub=1, horizon_minutes=30.0
    )
    schedule, status = solve_ortools(routes, orders, transporters_per_zone, HANDOVER, time_limit_seconds=5, horizon_minutes=30.0)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert schedule is not None
    _assert_all_legs_covered(schedule, routes, orders)
    _assert_capacity_never_exceeded(schedule, transporters_per_zone)
    _assert_transfer_precedence(schedule, routes, orders, HANDOVER)


def test_ortools_at_least_as_good_as_coordinated_heuristic_on_small_instance():
    net, orders, routes, transporters_per_zone = build_scenario(
        n_aisles=2, hub_nodes=1, transporters_per_aisle=1, transporters_hub=1,
        n_orders=8, horizon_minutes=15.0, cross_zone_share=0.8, seed=3,
    )
    coordinated_schedule = dispatch_coordinated(routes, orders, transporters_per_zone, HANDOVER)
    coordinated_eval = evaluate_schedule(coordinated_schedule, routes, orders, transporters_per_zone, HANDOVER)

    ortools_schedule, status = solve_ortools(
        routes, orders, transporters_per_zone, HANDOVER, time_limit_seconds=5, horizon_minutes=15.0
    )
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    ortools_eval = evaluate_schedule(ortools_schedule, routes, orders, transporters_per_zone, HANDOVER)

    # OR-Tools optimizes on a discretized time grid (SCALE units), so it can
    # be a hair worse than the continuous-time heuristic purely from
    # rounding release times up to the grid - allow a small, grid-sized
    # tolerance rather than requiring an exact win.
    assert ortools_eval.total_lead_time <= coordinated_eval.total_lead_time + 0.5


def test_ortools_weighted_objective_prefers_finishing_express_order_first():
    """Two orders, identical routes and release time, compete for the same
    single-transporter zone - only one can go first. With EXPRESS_WEIGHT > 1
    in the objective, OR-Tools should choose to finish the express order
    first (whichever order goes second necessarily finishes later)."""
    routes = {
        0: Route(order_id=0, legs=[Leg("aisle_0", "n1", "n2", 4.0)]),
        1: Route(order_id=1, legs=[Leg("aisle_0", "n1", "n2", 4.0)]),
    }
    orders = [
        Order(0, "n1", "aisle_0", "n2", "aisle_0", release_time=0.0, is_express=False),
        Order(1, "n1", "aisle_0", "n2", "aisle_0", release_time=0.0, is_express=True),
    ]
    transporters_per_zone = {"aisle_0": 1}

    schedule, status = solve_ortools(routes, orders, transporters_per_zone, HANDOVER, time_limit_seconds=5, horizon_minutes=20.0)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    completion = {a.order_id: a.end for a in schedule.assignments}
    assert completion[1] < completion[0]
