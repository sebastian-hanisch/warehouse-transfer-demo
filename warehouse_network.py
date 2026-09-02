"""Warehouse graph: a hub-and-spoke layout of zones.

One central "hub" zone (a fast conveyor/lift corridor) connects several
"aisle" zones (slower rack-shuttle corridors). Each aisle attaches to the
hub at exactly one shared node - the transfer/handover point between the
aisle's transporter fleet and the hub's transporter fleet. Transporters may
only travel on edges that belong to their own zone.
"""

from dataclasses import dataclass

import networkx as nx


@dataclass
class Zone:
    zone_id: str
    kind: str  # "hub" or "aisle"
    nodes: list  # ordered path of node ids belonging to this zone
    speed: float  # distance units per minute
    graph: nx.Graph  # subgraph with only this zone's edges


@dataclass
class WarehouseNetwork:
    zones: dict  # zone_id -> Zone
    hub_id: str
    aisle_ids: list
    transfer_node_of_aisle: dict  # aisle_id -> node id (shared with hub)
    storage_nodes: dict  # aisle_id -> list of node ids usable as order origin/destination
    positions: dict  # node id -> (x, y), for visualization

    def zone_of_node(self, node_id, zone_id):
        """True if node_id belongs to zone_id's node list."""
        return node_id in self.zones[zone_id].nodes

    def travel_time(self, zone_id, from_node, to_node):
        zone = self.zones[zone_id]
        if from_node == to_node:
            return 0.0
        dist = nx.shortest_path_length(zone.graph, from_node, to_node, weight="weight")
        return dist / zone.speed


def build_network(
    n_aisles,
    nodes_per_aisle,
    hub_nodes,
    aisle_speed,
    hub_speed,
):
    """Build a hub-and-spoke warehouse graph.

    n_aisles: number of aisle zones
    nodes_per_aisle: nodes per aisle INCLUDING the shared transfer node
    hub_nodes: number of nodes along the hub corridor
    aisle_speed, hub_speed: distance units per minute for each zone kind
    """
    hub_id = "hub"
    hub_node_ids = [f"H{j}" for j in range(hub_nodes)]
    hub_graph = nx.Graph()
    hub_graph.add_nodes_from(hub_node_ids)
    for j in range(hub_nodes - 1):
        hub_graph.add_edge(hub_node_ids[j], hub_node_ids[j + 1], weight=1)

    zones = {
        hub_id: Zone(zone_id=hub_id, kind="hub", nodes=hub_node_ids, speed=hub_speed, graph=hub_graph)
    }

    aisle_ids = []
    transfer_node_of_aisle = {}
    storage_nodes = {}

    for i in range(n_aisles):
        aisle_id = f"aisle_{i}"
        aisle_ids.append(aisle_id)
        attach_node = hub_node_ids[i % hub_nodes]
        transfer_node_of_aisle[aisle_id] = attach_node

        interior = [f"A{i}_{k}" for k in range(1, nodes_per_aisle)]
        aisle_node_ids = [attach_node] + interior

        aisle_graph = nx.Graph()
        aisle_graph.add_nodes_from(aisle_node_ids)
        for k in range(len(aisle_node_ids) - 1):
            aisle_graph.add_edge(aisle_node_ids[k], aisle_node_ids[k + 1], weight=1)

        zones[aisle_id] = Zone(
            zone_id=aisle_id, kind="aisle", nodes=aisle_node_ids, speed=aisle_speed, graph=aisle_graph
        )
        storage_nodes[aisle_id] = interior

    positions = _layout(hub_node_ids, aisle_ids, zones, transfer_node_of_aisle)

    return WarehouseNetwork(
        zones=zones,
        hub_id=hub_id,
        aisle_ids=aisle_ids,
        transfer_node_of_aisle=transfer_node_of_aisle,
        storage_nodes=storage_nodes,
        positions=positions,
    )


def _layout(hub_node_ids, aisle_ids, zones, transfer_node_of_aisle):
    """Deterministic 2D layout: hub as a horizontal line, aisles as vertical
    branches alternating above/below their attachment point on the hub."""
    positions = {}
    hub_span = max(len(hub_node_ids) - 1, 1)
    for j, node in enumerate(hub_node_ids):
        positions[node] = (j / hub_span * 10.0, 0.0)

    for idx, aisle_id in enumerate(aisle_ids):
        attach = transfer_node_of_aisle[aisle_id]
        ax, _ay = positions[attach]
        direction = 1.0 if idx % 2 == 0 else -1.0
        # small horizontal jitter so aisles sharing a hub attachment node don't overlap
        jitter = 0.35 * (idx // 2)
        interior = zones[aisle_id].nodes[1:]
        for k, node in enumerate(interior, start=1):
            positions[node] = (ax + jitter, direction * k * 1.0)

    return positions
