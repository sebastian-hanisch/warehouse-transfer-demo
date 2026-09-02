"""Shared KPI computation, used identically for all four dispatch methods
so the comparison is fair - none of the methods is scored by its own
notion of "good"."""

from dataclasses import dataclass

from warehouse_constants import DUE_DATE_BUFFER_MINUTES, DUE_DATE_FACTOR


@dataclass
class OrderResult:
    order_id: int
    release_time: float
    completion_time: float
    lead_time: float
    transfer_wait: float
    n_transfers: int
    due_time: float
    on_time: bool


@dataclass
class EvaluationResult:
    method: str
    orders: list  # list[OrderResult]
    zone_utilization: dict  # zone_id -> share in [0, 1]
    makespan: float

    @property
    def total_lead_time(self):
        return sum(o.lead_time for o in self.orders)

    @property
    def avg_lead_time(self):
        return self.total_lead_time / len(self.orders) if self.orders else 0.0

    @property
    def total_transfer_wait(self):
        return sum(o.transfer_wait for o in self.orders)

    @property
    def avg_transfer_wait(self):
        return self.total_transfer_wait / len(self.orders) if self.orders else 0.0

    @property
    def on_time_rate(self):
        if not self.orders:
            return 1.0
        return sum(1 for o in self.orders if o.on_time) / len(self.orders)


def minimal_route_time(route, handover_minutes):
    travel = sum(leg.travel_time for leg in route.legs)
    return travel + route.n_transfers * handover_minutes


def evaluate_schedule(schedule, routes, orders, transporters_per_zone, handover_minutes):
    by_order = {}
    for a in schedule.assignments:
        by_order.setdefault(a.order_id, []).append(a)

    orders_by_id = {o.order_id: o for o in orders}
    order_results = []
    makespan = 0.0

    for order_id, legs in by_order.items():
        legs.sort(key=lambda a: a.leg_index)
        order = orders_by_id[order_id]
        route = routes[order_id]
        completion_time = legs[-1].end
        lead_time = completion_time - order.release_time
        transfer_wait = sum(max(a.start - a.ready_time, 0.0) for a in legs if a.leg_index > 0)
        due_time = order.release_time + DUE_DATE_FACTOR * minimal_route_time(route, handover_minutes) + DUE_DATE_BUFFER_MINUTES
        order_results.append(
            OrderResult(
                order_id=order_id,
                release_time=order.release_time,
                completion_time=completion_time,
                lead_time=lead_time,
                transfer_wait=transfer_wait,
                n_transfers=route.n_transfers,
                due_time=due_time,
                on_time=completion_time <= due_time,
            )
        )
        makespan = max(makespan, completion_time)

    order_results.sort(key=lambda r: r.order_id)

    busy_time = {zone_id: 0.0 for zone_id in transporters_per_zone}
    for a in schedule.assignments:
        busy_time[a.zone_id] += a.end - a.start

    zone_utilization = {}
    for zone_id, capacity in transporters_per_zone.items():
        denom = capacity * makespan
        zone_utilization[zone_id] = busy_time[zone_id] / denom if denom > 0 else 0.0

    return EvaluationResult(
        method=schedule.method,
        orders=order_results,
        zone_utilization=zone_utilization,
        makespan=makespan,
    )
