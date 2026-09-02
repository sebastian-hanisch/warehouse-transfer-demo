"""Shared KPI computation, used identically for all four dispatch methods
so the comparison is fair - none of the methods is scored by its own
notion of "good"."""

from dataclasses import dataclass

from warehouse_constants import DUE_DATE_BUFFER_MINUTES, DUE_DATE_BUFFER_MINUTES_EXPRESS


@dataclass
class OrderResult:
    order_id: int
    release_time: float
    completion_time: float
    lead_time: float
    pure_travel_time: float  # sum of leg travel times, from the route - the non-negotiable minimum
    transfer_wait: float  # part of lead_time spent waiting AT a handover (leg_index > 0 only)
    n_transfers: int
    due_time: float
    on_time: bool
    is_express: bool = False


@dataclass
class EvaluationResult:
    method: str
    orders: list  # list[OrderResult]
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

    @property
    def on_time_rate_express(self):
        express_orders = [o for o in self.orders if o.is_express]
        if not express_orders:
            return 1.0
        return sum(1 for o in express_orders if o.on_time) / len(express_orders)

    def avg_lead_time_composition(self, handover_minutes):
        """Breaks the average Gesamtdurchlaufzeit down into three parts that
        sum EXACTLY to avg_lead_time: pure travel time (the non-negotiable
        minimum), fixed handover overhead (n_transfers * handover_minutes),
        and everything else (queueing for a transporter, repositioning,
        including before the very first leg) - Gesamtdurchlaufzeit is the
        only thing any method here actually optimizes for; this is purely
        an explanatory breakdown of what it's made of, not a second
        objective."""
        if not self.orders:
            return {"travel": 0.0, "handover": 0.0, "wait": 0.0}
        avg_travel = sum(o.pure_travel_time for o in self.orders) / len(self.orders)
        avg_handover = sum(o.n_transfers * handover_minutes for o in self.orders) / len(self.orders)
        avg_wait = self.avg_lead_time - avg_travel - avg_handover
        return {"travel": avg_travel, "handover": avg_handover, "wait": max(avg_wait, 0.0)}


def minimal_route_time(route, handover_minutes):
    travel = sum(leg.travel_time for leg in route.legs)
    return travel + route.n_transfers * handover_minutes


def evaluate_schedule(schedule, routes, orders, handover_minutes):
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
        pure_travel_time = sum(leg.travel_time for leg in route.legs)
        transfer_wait = sum(max(a.start - a.ready_time, 0.0) for a in legs if a.leg_index > 0)
        buffer_minutes = DUE_DATE_BUFFER_MINUTES_EXPRESS if order.is_express else DUE_DATE_BUFFER_MINUTES
        due_time = order.release_time + minimal_route_time(route, handover_minutes) + buffer_minutes
        order_results.append(
            OrderResult(
                order_id=order_id,
                release_time=order.release_time,
                completion_time=completion_time,
                lead_time=lead_time,
                pure_travel_time=pure_travel_time,
                transfer_wait=transfer_wait,
                n_transfers=route.n_transfers,
                due_time=due_time,
                on_time=completion_time <= due_time,
                is_express=order.is_express,
            )
        )
        makespan = max(makespan, completion_time)

    order_results.sort(key=lambda r: r.order_id)

    return EvaluationResult(
        method=schedule.method,
        orders=order_results,
        makespan=makespan,
    )
