"""Orakel für Simulator und CP-SAT-Modell.

* Die Dispositionsregeln (FCFS, SPT, ATCS) werden von einem zweiten Simulator nachgerechnet, der keine Ereignisliste benutzt, sondern je Zone den frühestmöglichen
  Dispositionszeitpunkt sucht; Geometrie (Gassen als Pfade) und ATCS-Formel sind unabhängig von Hand codiert. Gleichzeitige Ereignisse müssen vor der Entscheidung alle
  wirksam sein (früher entschied die Einfügereihenfolge der Ereignisliste, welcher Transporter bzw. welcher Auftrag gesehen wurde).
* Das CP-SAT-Optimum wird gegen Vollaufzählung (alle präzedenzzulässigen Reihenfolgen x Transporterwahl, serielle Planerzeugung) geprüft.
* Der Zeithorizont des CP-SAT-Modells muss auch bei vielen Aufträgen in kurzem Horizont jede Lösung enthalten (früher: Status „unlösbar“ trotz zulässiger Pläne)."""

import math
import random

import pytest

from conftest import build_scenario
from warehouse_constants import DUE_DATE_BUFFER_MINUTES, DUE_DATE_BUFFER_MINUTES_EXPRESS, EXPRESS_WEIGHT, TARDINESS_PENALTY_WEIGHT
from warehouse_demand import Order
from warehouse_dispatch_baseline import dispatch_baseline
from warehouse_dispatch_coordinated import ATCS_K1, ATCS_K2, dispatch_coordinated
from warehouse_dispatch_greedy import dispatch_greedy
from warehouse_network import build_network
from warehouse_ortools_solver import solve_ortools
from warehouse_routing import route_orders

cp_model = pytest.importorskip("ortools.sat.python.cp_model")


def _index(net, zone, node):
    return net.zones[zone].nodes.index(node)


def _legs_by_hand(net, orders):
    """(Zone, Eintrittsindex, Austrittsindex) je Leg; Gassen und Hub sind Pfade, der Umschlagpunkt ist der Index 0 der Gasse."""
    out = {}
    for o in orders:
        if o.origin_aisle == o.destination_aisle:
            z = o.origin_aisle
            out[o.order_id] = [(z, _index(net, z, o.origin_node), _index(net, z, o.destination_node))]
        else:
            n_hub = len(net.zones[net.hub_id].nodes)
            ai, bi = net.aisle_ids.index(o.origin_aisle), net.aisle_ids.index(o.destination_aisle)
            out[o.order_id] = [
                (o.origin_aisle, _index(net, o.origin_aisle, o.origin_node), 0),
                (net.hub_id, ai % n_hub, bi % n_hub),
                (o.destination_aisle, 0, _index(net, o.destination_aisle, o.destination_node)),
            ]
    return out


def _due(order, durations, h):
    buffer = DUE_DATE_BUFFER_MINUTES_EXPRESS if order.is_express else DUE_DATE_BUFFER_MINUTES
    return order.release_time + sum(durations) + (len(durations) - 1) * h + buffer


def _other_simulator(net, orders, tpz, h, rule):
    mr = _legs_by_hand(net, orders)
    speed = {z: net.zones[z].speed for z in net.zones}
    dur = {(oid, i): abs(e - x) / speed[z] for oid, legs in mr.items() for i, (z, e, x) in enumerate(legs)}
    p_bar = max(sum(dur.values()) / len(dur), 1e-6)
    by_id = {o.order_id: o for o in orders}
    ready = {(o.order_id, 0): o.release_time for o in orders}
    machines = {z: [[0.0, 0] for _ in range(tpz[z])] for z in tpz}  # frei ab, Position (Index)
    done = {}

    def priority(oid, i, now, idle_pos):
        if rule == "fcfs":
            return 0.0
        if rule == "spt":
            return dur[(oid, i)]
        z, e, _x = mr[oid][i]
        p = max(dur[(oid, i)], 1e-6)
        rest = [dur[(oid, j)] for j in range(i + 1, len(mr[oid]))]
        near = min((abs(pos - e) / speed[z] for pos in idle_pos), default=0.0)
        slack = max(_due(by_id[oid], [dur[(oid, j)] for j in range(len(mr[oid]))], h) - (now + p + sum(rest) + len(rest) * h), 0.0)
        w = EXPRESS_WEIGHT if by_id[oid].is_express else 1
        return -((w / p) * math.exp(-slack / (ATCS_K1 * p_bar)) * math.exp(-near / (ATCS_K2 * p_bar)))

    while len(done) < len(dur):
        best = None
        for z in tpz:
            cand = [(k, r) for k, r in ready.items() if k not in done and mr[k[0]][k[1]][0] == z]
            if cand:
                t = max(min(m[0] for m in machines[z]), min(r for _k, r in cand))
                if best is None or t < best[0] - 1e-9:
                    best = (t, z)
        t, z = best
        cand = [(k, r) for k, r in ready.items() if k not in done and mr[k[0]][k[1]][0] == z and r <= t + 1e-9]
        idle = [m for m in machines[z] if m[0] <= t + 1e-9]
        (oid, i), r = min(cand, key=lambda kr: (priority(kr[0][0], kr[0][1], t, [m[1] for m in idle]), kr[1]))
        entry = mr[oid][i][1]
        m = min(idle, key=lambda m: (abs(m[1] - entry) / speed[z], m[0]))
        start = t + abs(m[1] - entry) / speed[z]
        end = start + dur[(oid, i)]
        m[0], m[1] = end, mr[oid][i][2]
        done[(oid, i)] = (start, end)
        if i + 1 < len(mr[oid]):
            ready[(oid, i + 1)] = end + h
    return done


@pytest.mark.parametrize("rule, dispatcher", [("fcfs", dispatch_baseline), ("spt", dispatch_greedy), ("atcs", dispatch_coordinated)])
def test_dispatch_rules_agree_with_a_second_simulator(rule, dispatcher):
    rng = random.Random(21)
    for _ in range(60):
        n_aisles, nodes, hub_nodes = rng.randint(2, 4), rng.randint(3, 6), rng.randint(1, 4)
        net, orders, routes, tpz = build_scenario(
            n_aisles=n_aisles, nodes_per_aisle=nodes, hub_nodes=hub_nodes, aisle_speed=rng.choice([0.5, 1.0, 2.0]), hub_speed=rng.choice([1.0, 2.0, 4.0]),
            n_orders=rng.randint(8, 30), horizon_minutes=rng.choice([10.0, 30.0]), cross_zone_share=rng.choice([0.3, 0.7, 1.0]), seed=rng.randrange(10000),
            transporters_per_aisle=rng.randint(1, 3), transporters_hub=rng.randint(1, 3), express_share=rng.choice([0.0, 0.5]),
        )
        h = rng.choice([0.5, 1.0, 2.0])
        mine = _other_simulator(net, orders, tpz, h, rule)
        theirs = {(a.order_id, a.leg_index): a for a in dispatcher(net, routes, orders, tpz, h).assignments}
        for key, (start, end) in mine.items():
            assert theirs[key].start == pytest.approx(start, abs=1e-7) and theirs[key].end == pytest.approx(end, abs=1e-7), (rule, key)


def test_events_at_the_same_instant_are_all_seen_before_a_decision():
    """Von Hand: zwei Transporter in Gasse 0 (Index 0 = Umschlagpunkt). Auftrag 0 (A0_3 -> A0_4, Freigabe 0): Anfahrt 3, Fahrt 1, Transporter frei bei Minute 4 an A0_4.
    Auftrag 1 wird genau dann frei (Freigabe 4) und startet an A0_4: der gerade frei gewordene Transporter braucht 0 Anfahrt, der wartende am Umschlagpunkt 4.
    Richtig: Start 4 (nicht 8)."""
    net = build_network(2, 5, 1, 1.0, 2.0)
    orders = [
        Order(0, "A0_3", "aisle_0", "A0_4", "aisle_0", 0.0),
        Order(1, "A0_4", "aisle_0", "A0_3", "aisle_0", 4.0),
    ]
    routes = route_orders(net, orders)
    tpz = {"aisle_0": 2, "aisle_1": 1, "hub": 1}
    for dispatcher in (dispatch_baseline, dispatch_greedy, dispatch_coordinated):
        starts = {a.order_id: a.start for a in dispatcher(net, routes, orders, tpz, 1.0).assignments}
        assert starts == {0: pytest.approx(3.0), 1: pytest.approx(4.0)}, dispatcher.__name__


def _brute_force_optimum(net, orders, tpz, h):
    """Vollaufzählung (kein Heimatpunkt, wie das CP-SAT-Modell): serielle Planerzeugung über alle präzedenzzulässigen Legfolgen und alle Transporterwahlen."""
    mr = _legs_by_hand(net, orders)
    speed = {z: net.zones[z].speed for z in net.zones}
    by_id = {o.order_id: o for o in orders}
    dur = {oid: [abs(e - x) / speed[z] for z, e, x in legs] for oid, legs in mr.items()}
    due = {oid: _due(by_id[oid], dur[oid], h) for oid in mr}
    best = [math.inf]

    def rec(next_leg, last_end, machines, cost):
        if cost >= best[0]:
            return
        pending = [oid for oid in mr if next_leg[oid] < len(mr[oid])]
        if not pending:
            best[0] = cost
            return
        for oid in pending:
            i = next_leg[oid]
            z, e, x = mr[oid][i]
            ready = by_id[oid].release_time if i == 0 else last_end[oid] + h
            for mi, (free, pos) in enumerate(machines[z]):
                start = max(ready, free + (0.0 if pos is None else abs(pos - e) / speed[z]))
                end = start + dur[oid][i]
                machines[z][mi] = (end, x)
                next_leg[oid], old_end = i + 1, last_end.get(oid)
                last_end[oid] = end
                extra = 0.0
                if i + 1 == len(mr[oid]):
                    w = EXPRESS_WEIGHT if by_id[oid].is_express else 1
                    extra = w * end + TARDINESS_PENALTY_WEIGHT * max(0.0, end - due[oid])
                rec(next_leg, last_end, machines, cost + extra)
                next_leg[oid] = i
                if old_end is None:
                    del last_end[oid]
                else:
                    last_end[oid] = old_end
                machines[z][mi] = (free, pos)

    rec({oid: 0 for oid in mr}, {}, {z: [(0.0, None)] * tpz[z] for z in tpz}, 0.0)
    return best[0]


def test_cpsat_optimum_equals_exhaustive_enumeration():
    rng = random.Random(4)
    checked = 0
    while checked < 10:
        net, orders, routes, tpz = build_scenario(
            n_aisles=rng.choice([2, 3]), nodes_per_aisle=rng.choice([3, 4, 5]), hub_nodes=rng.choice([1, 2]), aisle_speed=rng.choice([0.5, 1.0, 2.0]), hub_speed=rng.choice([1.0, 2.0, 4.0]),
            n_orders=rng.choice([2, 3]), horizon_minutes=rng.choice([3.0, 10.0]), cross_zone_share=rng.choice([0.0, 0.5, 1.0]), seed=rng.randrange(10000),
            transporters_per_aisle=rng.choice([1, 2]), transporters_hub=rng.choice([1, 2]), express_share=rng.choice([0.0, 0.5]),
        )
        if sum(len(r.legs) for r in routes.values()) > 7:
            continue
        h = rng.choice([0.0, 1.0, 2.0])
        schedule, status = solve_ortools(net, routes, orders, tpz, h, 20, 30.0)
        assert status == cp_model.OPTIMAL
        by_id = {o.order_id: o for o in orders}
        value = 0.0
        for o in orders:
            durations = [leg.travel_time for leg in routes[o.order_id].legs]
            end = max(a.end for a in schedule.assignments if a.order_id == o.order_id)
            value += (EXPRESS_WEIGHT if by_id[o.order_id].is_express else 1) * end + TARDINESS_PENALTY_WEIGHT * max(0.0, end - _due(o, durations, h))
        assert value == pytest.approx(_brute_force_optimum(net, orders, tpz, h), abs=0.05)   # Aufrunden der Freigaben auf 1/100 min im Modell
        checked += 1


def test_cpsat_horizon_contains_every_schedule_even_for_many_orders_in_a_short_horizon():
    """8 Aufträge, alle innerhalb der ersten Minute freigegeben, je ein Transporter: der Plan dauert weit über 10 Minuten (früher die obere Grenze aller Startzeiten)."""
    net, orders, routes, tpz = build_scenario(n_orders=8, horizon_minutes=1.0, transporters_per_aisle=1, transporters_hub=1)
    schedule, status = solve_ortools(net, routes, orders, tpz, 1.0, 3, 1.0)
    assert schedule is not None and status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert max(a.end for a in schedule.assignments) > 10.0
