import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from warehouse_demand import generate_orders
from warehouse_network import build_network
from warehouse_routing import route_orders


def build_scenario(n_aisles=3, nodes_per_aisle=5, hub_nodes=2, aisle_speed=1.0, hub_speed=2.0,
                    n_orders=20, horizon_minutes=60.0, cross_zone_share=0.7, seed=42,
                    transporters_per_aisle=1, transporters_hub=1):
    net = build_network(n_aisles, nodes_per_aisle, hub_nodes, aisle_speed, hub_speed)
    orders = generate_orders(net, n_orders, horizon_minutes, cross_zone_share, seed)
    routes = route_orders(net, orders)
    transporters_per_zone = {a: transporters_per_aisle for a in net.aisle_ids}
    transporters_per_zone[net.hub_id] = transporters_hub
    return net, orders, routes, transporters_per_zone


@pytest.fixture
def scenario():
    return build_scenario()
