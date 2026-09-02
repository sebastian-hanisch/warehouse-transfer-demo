"""Example scenarios and permalink logic.

WICHTIG - eine Wahrheitsquelle fuer Wertebereiche: SETTING_SPECS definiert
Minimum/Maximum/Default je Widget. Sowohl die Slider in app.py (ueber
bounds()) als auch die Permalink-Begrenzung lesen daraus - dieselbe
Struktur, die in den Schwesterdemos (vrp_demo, shift_demo) eine
Absturzklasse durch Permalink-Werte ausserhalb des Wertebereichs behoben
hat. Hier von Anfang an uebernommen statt erst nach einem Fund.
"""

import math
import random
from dataclasses import dataclass
from typing import Callable, Optional

import streamlit as st

from warehouse_constants import (
    DEFAULT_CROSS_ZONE_SHARE,
    DEFAULT_HANDOVER_MINUTES,
    DEFAULT_HORIZON_MINUTES,
    DEFAULT_HUB_NODES,
    DEFAULT_N_AISLES,
    DEFAULT_N_ORDERS,
    DEFAULT_NODES_PER_AISLE,
    DEFAULT_SEED,
    DEFAULT_TRANSPORTERS_HUB,
    DEFAULT_TRANSPORTERS_PER_AISLE,
    MAX_CROSS_ZONE_SHARE,
    MAX_HANDOVER_MINUTES,
    MAX_HORIZON_MINUTES,
    MAX_HUB_NODES,
    MAX_N_AISLES,
    MAX_N_ORDERS,
    MAX_NODES_PER_AISLE,
    MAX_SEED,
    MAX_TRANSPORTERS_HUB,
    MAX_TRANSPORTERS_PER_AISLE,
    MIN_CROSS_ZONE_SHARE,
    MIN_HANDOVER_MINUTES,
    MIN_HORIZON_MINUTES,
    MIN_HUB_NODES,
    MIN_N_AISLES,
    MIN_N_ORDERS,
    MIN_NODES_PER_AISLE,
    MIN_SEED,
    MIN_TRANSPORTERS_HUB,
    MIN_TRANSPORTERS_PER_AISLE,
)


@dataclass(frozen=True)
class SettingSpec:
    url_param: str
    caster: Callable
    default: object
    lo: Optional[float] = None
    hi: Optional[float] = None


SETTING_SPECS = {
    "n_aisles_slider": SettingSpec("aisles", int, DEFAULT_N_AISLES, MIN_N_AISLES, MAX_N_AISLES),
    "nodes_per_aisle_slider": SettingSpec("nodes", int, DEFAULT_NODES_PER_AISLE, MIN_NODES_PER_AISLE, MAX_NODES_PER_AISLE),
    "hub_nodes_slider": SettingSpec("hub_nodes", int, DEFAULT_HUB_NODES, MIN_HUB_NODES, MAX_HUB_NODES),
    "trans_aisle_slider": SettingSpec("trans_aisle", int, DEFAULT_TRANSPORTERS_PER_AISLE, MIN_TRANSPORTERS_PER_AISLE, MAX_TRANSPORTERS_PER_AISLE),
    "trans_hub_slider": SettingSpec("trans_hub", int, DEFAULT_TRANSPORTERS_HUB, MIN_TRANSPORTERS_HUB, MAX_TRANSPORTERS_HUB),
    "handover_slider": SettingSpec("handover", float, DEFAULT_HANDOVER_MINUTES, MIN_HANDOVER_MINUTES, MAX_HANDOVER_MINUTES),
    "n_orders_slider": SettingSpec("orders", int, DEFAULT_N_ORDERS, MIN_N_ORDERS, MAX_N_ORDERS),
    "horizon_slider": SettingSpec("horizon", float, DEFAULT_HORIZON_MINUTES, MIN_HORIZON_MINUTES, MAX_HORIZON_MINUTES),
    "cross_zone_slider": SettingSpec("cross", float, DEFAULT_CROSS_ZONE_SHARE, MIN_CROSS_ZONE_SHARE, MAX_CROSS_ZONE_SHARE),
    "seed_input": SettingSpec("seed", int, DEFAULT_SEED, MIN_SEED, MAX_SEED),
}

PRESET_KEYS = [
    "n_aisles_slider", "nodes_per_aisle_slider", "hub_nodes_slider", "trans_aisle_slider",
    "trans_hub_slider", "handover_slider", "n_orders_slider", "horizon_slider",
    "cross_zone_slider", "seed_input",
]

# Curated, checked scenarios (not random) - "Stosszeit" is tuned so the
# greedy-vs-koordiniert gap in Umstiegs-Wartezeit is clearly visible, the
# same way shift_demo's integrality-gap preset is a checked example rather
# than a lucky random draw.
PRESETS = {
    "Kleines Lager, wenig Verkehr": dict(
        n_aisles=2, nodes_per_aisle=4, hub_nodes=2, trans_aisle=1, trans_hub=1,
        handover=1.0, n_orders=8, horizon=30.0, cross=0.5, seed=2,
    ),
    "Stosszeit mit Engpass am Umschlagpunkt": dict(
        n_aisles=3, nodes_per_aisle=5, hub_nodes=1, trans_aisle=2, trans_hub=1,
        handover=1.0, n_orders=30, horizon=20.0, cross=0.8, seed=7,
    ),
    "Grosses Lager": dict(
        n_aisles=4, nodes_per_aisle=6, hub_nodes=4, trans_aisle=2, trans_hub=3,
        handover=1.0, n_orders=40, horizon=90.0, cross=0.6, seed=99,
    ),
}


def bounds(state_key):
    spec = SETTING_SPECS[state_key]
    return spec.lo, spec.hi


def apply_preset(name):
    values = PRESETS[name]
    st.session_state["n_aisles_slider"] = values["n_aisles"]
    st.session_state["nodes_per_aisle_slider"] = values["nodes_per_aisle"]
    st.session_state["hub_nodes_slider"] = values["hub_nodes"]
    st.session_state["trans_aisle_slider"] = values["trans_aisle"]
    st.session_state["trans_hub_slider"] = values["trans_hub"]
    st.session_state["handover_slider"] = values["handover"]
    st.session_state["n_orders_slider"] = values["n_orders"]
    st.session_state["horizon_slider"] = values["horizon"]
    st.session_state["cross_zone_slider"] = values["cross"]
    st.session_state["seed_input"] = values["seed"]


def randomize_seed():
    st.session_state["seed_input"] = random.randint(MIN_SEED, MAX_SEED)


def load_permalink_settings():
    if "permalink_loaded" in st.session_state:
        return
    qp = st.query_params
    for state_key, spec in SETTING_SPECS.items():
        if spec.url_param in qp:
            try:
                value = spec.caster(qp[spec.url_param])
                if isinstance(value, float) and not math.isfinite(value):
                    continue
                if spec.lo is not None:
                    value = max(spec.lo, value)
                if spec.hi is not None:
                    value = min(spec.hi, value)
                st.session_state[state_key] = value
            except (ValueError, TypeError):
                pass
    st.session_state["permalink_loaded"] = True


def init_session_state_defaults():
    for state_key, spec in SETTING_SPECS.items():
        if state_key not in st.session_state:
            st.session_state[state_key] = spec.default


def sync_query_params(values):
    """values: dict state_key -> current widget value."""
    try:
        for state_key, spec in SETTING_SPECS.items():
            st.query_params[spec.url_param] = str(values[state_key])
    except Exception:
        pass
