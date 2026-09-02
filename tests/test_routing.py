import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from warehouse_demand import Order
from warehouse_network import build_network
from warehouse_routing import route_order, route_orders


def make_net():
    return build_network(n_aisles=3, nodes_per_aisle=5, hub_nodes=4, aisle_speed=1.0, hub_speed=2.0)


def test_same_aisle_order_has_single_leg_no_transfer():
    net = make_net()
    aisle_id = net.aisle_ids[0]
    nodes = net.storage_nodes[aisle_id]
    order = Order(0, nodes[0], aisle_id, nodes[-1], aisle_id, release_time=0.0)
    route = route_order(net, order)
    assert len(route.legs) == 1
    assert route.n_transfers == 0
    assert route.legs[0].zone_id == aisle_id


def test_cross_aisle_order_has_three_legs_via_hub():
    net = make_net()
    a0, a1 = net.aisle_ids[0], net.aisle_ids[1]
    origin = net.storage_nodes[a0][0]
    dest = net.storage_nodes[a1][0]
    order = Order(0, origin, a0, dest, a1, release_time=0.0)
    route = route_order(net, order)
    assert [leg.zone_id for leg in route.legs] == [a0, net.hub_id, a1]
    assert route.n_transfers == 2


def test_leg_chain_connects_at_shared_nodes():
    net = make_net()
    a0, a2 = net.aisle_ids[0], net.aisle_ids[2]
    origin = net.storage_nodes[a0][1]
    dest = net.storage_nodes[a2][2]
    order = Order(0, origin, a0, dest, a2, release_time=0.0)
    route = route_order(net, order)
    for prev_leg, next_leg in zip(route.legs, route.legs[1:]):
        assert prev_leg.exit_node == next_leg.entry_node
    assert route.legs[0].entry_node == origin
    assert route.legs[-1].exit_node == dest


def test_route_orders_covers_all_orders():
    net = make_net()
    orders = [
        Order(0, net.storage_nodes[net.aisle_ids[0]][0], net.aisle_ids[0],
              net.storage_nodes[net.aisle_ids[1]][0], net.aisle_ids[1], 0.0),
        Order(1, net.storage_nodes[net.aisle_ids[1]][0], net.aisle_ids[1],
              net.storage_nodes[net.aisle_ids[1]][2], net.aisle_ids[1], 1.0),
    ]
    routes = route_orders(net, orders)
    assert set(routes.keys()) == {0, 1}
