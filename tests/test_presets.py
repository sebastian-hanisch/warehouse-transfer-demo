import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from warehouse_presets import PRESETS, SETTING_SPECS


def test_setting_specs_defaults_are_within_bounds():
    for state_key, spec in SETTING_SPECS.items():
        if spec.lo is not None:
            assert spec.default >= spec.lo, state_key
        if spec.hi is not None:
            assert spec.default <= spec.hi, state_key


def test_permalink_url_params_are_unique():
    params = [spec.url_param for spec in SETTING_SPECS.values()]
    assert len(params) == len(set(params))


def test_permalink_clamps_out_of_range_values(monkeypatch):
    import streamlit as st

    fake_qp = {"aisles": "999", "orders": "-10", "cross": "abc", "seed": "5"}
    monkeypatch.setattr(st, "query_params", fake_qp)
    st.session_state.clear()

    from warehouse_presets import load_permalink_settings

    load_permalink_settings()

    assert st.session_state["n_aisles_slider"] == SETTING_SPECS["n_aisles_slider"].hi
    assert st.session_state["n_orders_slider"] == SETTING_SPECS["n_orders_slider"].lo
    assert "cross_zone_slider" not in st.session_state  # invalid caster input ignored
    assert st.session_state["seed_input"] == 5


def test_presets_have_all_required_fields():
    required = {
        "n_aisles", "nodes_per_aisle", "hub_nodes", "trans_aisle", "trans_hub",
        "handover", "n_orders", "horizon", "cross", "express", "seed",
    }
    for name, values in PRESETS.items():
        assert required <= set(values.keys()), name


def test_presets_within_setting_spec_bounds():
    field_to_state_key = {
        "n_aisles": "n_aisles_slider", "nodes_per_aisle": "nodes_per_aisle_slider",
        "hub_nodes": "hub_nodes_slider", "trans_aisle": "trans_aisle_slider",
        "trans_hub": "trans_hub_slider", "handover": "handover_slider",
        "n_orders": "n_orders_slider", "horizon": "horizon_slider",
        "cross": "cross_zone_slider", "express": "express_slider", "seed": "seed_input",
    }
    for name, values in PRESETS.items():
        for field, state_key in field_to_state_key.items():
            spec = SETTING_SPECS[state_key]
            v = values[field]
            if spec.lo is not None:
                assert v >= spec.lo, f"{name}.{field}"
            if spec.hi is not None:
                assert v <= spec.hi, f"{name}.{field}"
