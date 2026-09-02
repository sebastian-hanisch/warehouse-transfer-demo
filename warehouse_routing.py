"""Turns an order's origin/destination into a zone-path of legs.

Routing itself is not an optimization problem here: the hub-and-spoke
topology gives each order exactly one valid zone sequence (stay in its
aisle, or aisle -> hub -> aisle). The actual optimization problem is WHEN
and with WHICH transporter each leg gets served - that's the dispatch
layer (warehouse_dispatch_*.py).
"""

from dataclasses import dataclass


@dataclass
class Leg:
    zone_id: str
    entry_node: str
    exit_node: str
    travel_time: float


@dataclass
class Route:
    order_id: int
    legs: list  # list[Leg], in travel order

    @property
    def n_transfers(self):
        return max(len(self.legs) - 1, 0)


def route_order(network, order):
    if order.origin_aisle == order.destination_aisle:
        zone_id = order.origin_aisle
        travel_time = network.travel_time(zone_id, order.origin_node, order.destination_node)
        legs = [Leg(zone_id, order.origin_node, order.destination_node, travel_time)]
        return Route(order_id=order.order_id, legs=legs)

    origin_transfer = network.transfer_node_of_aisle[order.origin_aisle]
    dest_transfer = network.transfer_node_of_aisle[order.destination_aisle]

    leg1 = Leg(
        order.origin_aisle,
        order.origin_node,
        origin_transfer,
        network.travel_time(order.origin_aisle, order.origin_node, origin_transfer),
    )
    leg2 = Leg(
        network.hub_id,
        origin_transfer,
        dest_transfer,
        network.travel_time(network.hub_id, origin_transfer, dest_transfer),
    )
    leg3 = Leg(
        order.destination_aisle,
        dest_transfer,
        order.destination_node,
        network.travel_time(order.destination_aisle, dest_transfer, order.destination_node),
    )
    return Route(order_id=order.order_id, legs=[leg1, leg2, leg3])


def route_orders(network, orders):
    return {order.order_id: route_order(network, order) for order in orders}
