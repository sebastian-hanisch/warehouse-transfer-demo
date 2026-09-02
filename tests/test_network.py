import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from warehouse_network import build_network


def make_net(n_aisles=3, nodes_per_aisle=5, hub_nodes=4, aisle_speed=1.0, hub_speed=2.0):
    return build_network(n_aisles, nodes_per_aisle, hub_nodes, aisle_speed, hub_speed)


def test_aisle_count_and_ids():
    net = make_net(n_aisles=3)
    assert net.aisle_ids == ["aisle_0", "aisle_1", "aisle_2"]
    assert net.hub_id == "hub"


def test_storage_nodes_exclude_transfer_node():
    net = make_net(n_aisles=2, nodes_per_aisle=5)
    for aisle_id in net.aisle_ids:
        transfer_node = net.transfer_node_of_aisle[aisle_id]
        assert transfer_node not in net.storage_nodes[aisle_id]
        assert len(net.storage_nodes[aisle_id]) == 4  # nodes_per_aisle - 1


def test_transfer_node_belongs_to_both_zones():
    net = make_net(n_aisles=2, nodes_per_aisle=4, hub_nodes=3)
    for aisle_id in net.aisle_ids:
        transfer_node = net.transfer_node_of_aisle[aisle_id]
        assert transfer_node in net.zones[aisle_id].nodes
        assert transfer_node in net.zones[net.hub_id].nodes


def test_travel_time_within_aisle_uses_aisle_speed():
    net = make_net(n_aisles=1, nodes_per_aisle=5, aisle_speed=2.0)
    aisle_id = net.aisle_ids[0]
    nodes = net.zones[aisle_id].nodes  # [transfer, A0_1, A0_2, A0_3, A0_4]
    t = net.travel_time(aisle_id, nodes[0], nodes[-1])
    assert t == 4 / 2.0  # 4 hops / speed


def test_travel_time_zero_for_same_node():
    net = make_net()
    aisle_id = net.aisle_ids[0]
    node = net.storage_nodes[aisle_id][0]
    assert net.travel_time(aisle_id, node, node) == 0.0


def test_more_aisles_than_hub_nodes_reuses_attachment_points():
    net = make_net(n_aisles=5, hub_nodes=2)
    attach_points = {net.transfer_node_of_aisle[a] for a in net.aisle_ids}
    assert attach_points <= set(net.zones[net.hub_id].nodes)


def test_positions_cover_all_nodes():
    net = make_net(n_aisles=3, nodes_per_aisle=4, hub_nodes=3)
    all_nodes = set(net.zones[net.hub_id].nodes)
    for aisle_id in net.aisle_ids:
        all_nodes |= set(net.zones[aisle_id].nodes)
    assert set(net.positions.keys()) == all_nodes
