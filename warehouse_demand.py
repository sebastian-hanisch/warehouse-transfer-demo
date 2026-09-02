"""Order generation for the warehouse-transfer demo."""

from dataclasses import dataclass

import numpy as np


@dataclass
class Order:
    order_id: int
    origin_node: str
    origin_aisle: str
    destination_node: str
    destination_aisle: str
    release_time: float  # minutes


def generate_orders(network, n_orders, horizon_minutes, cross_zone_share, seed):
    """Generate n_orders pickup/delivery orders between aisle storage nodes.

    A share of `cross_zone_share` orders has origin and destination in
    different aisles (forcing a hub transfer); the rest stays within one
    aisle (no transfer needed). Release times are drawn uniformly over the
    horizon and returned sorted.
    """
    rng = np.random.default_rng(seed)
    aisle_ids = network.aisle_ids
    orders = []

    for order_id in range(n_orders):
        origin_aisle = rng.choice(aisle_ids)
        want_cross_zone = len(aisle_ids) > 1 and rng.random() < cross_zone_share

        if want_cross_zone:
            other_aisles = [a for a in aisle_ids if a != origin_aisle]
            destination_aisle = rng.choice(other_aisles)
        else:
            destination_aisle = origin_aisle

        origin_node = rng.choice(network.storage_nodes[origin_aisle])
        dest_candidates = network.storage_nodes[destination_aisle]
        if destination_aisle == origin_aisle:
            dest_candidates = [n for n in dest_candidates if n != origin_node]
            if not dest_candidates:
                dest_candidates = network.storage_nodes[destination_aisle]
        destination_node = rng.choice(dest_candidates)

        release_time = float(rng.uniform(0.0, horizon_minutes))

        orders.append(
            Order(
                order_id=order_id,
                origin_node=str(origin_node),
                origin_aisle=origin_aisle,
                destination_node=str(destination_node),
                destination_aisle=destination_aisle,
                release_time=release_time,
            )
        )

    orders.sort(key=lambda o: o.release_time)
    return orders
