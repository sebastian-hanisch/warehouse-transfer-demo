import time

import pandas as pd
import streamlit as st

from warehouse_constants import (
    DEFAULT_AISLE_SPEED,
    DEFAULT_HUB_SPEED,
    DEFAULT_ORTOOLS_TIME_LIMIT,
    MAX_ORTOOLS_TIME_LIMIT,
    METHOD_COORDINATED,
    METHOD_LABELS,
    ORTOOLS_COOLDOWN_BUFFER_SECONDS,
)
from warehouse_demand import generate_orders
from warehouse_dispatch_baseline import dispatch_baseline
from warehouse_dispatch_coordinated import dispatch_coordinated
from warehouse_dispatch_greedy import dispatch_greedy
from warehouse_evaluation import evaluate_schedule
from warehouse_network import build_network
from warehouse_ortools_solver import solve_ortools, status_label
from warehouse_presets import (
    PRESETS,
    apply_preset,
    bounds,
    init_session_state_defaults,
    load_permalink_settings,
    randomize_seed,
    sync_query_params,
)
from warehouse_routing import route_orders
from warehouse_ui_panel import render_method_panel
from warehouse_visualization import (
    build_animation_figure,
    build_kpi_comparison_figure,
    build_transfer_wait_figure,
    build_warehouse_figure,
)

st.set_page_config(page_title="Lagerlogistik: Umstiegspunkte", layout="wide")

init_session_state_defaults()
load_permalink_settings()

st.title("Automatisiertes Hochregallager: Transport ueber mehrere Zonen")
st.markdown(
    "Ware bewegt sich durch mehrere **Zonen** (Regalgassen-Shuttles + zentraler "
    "Verteiler/Lift). Jeder Transporter bleibt in seiner eigenen Zone - grenz-"
    "ueberschreitende Auftraege muessen an einem **Umschlagpunkt** auf den "
    "naechsten Transporter umsteigen. Diese Demo zeigt, warum eine Zone, die "
    "nur fuer sich selbst optimal disponiert, an solchen Umschlagpunkten "
    "Wartezeit erzeugt - und wie viel eine zonenuebergreifend koordinierte "
    "Disposition davon vermeidet."
)

with st.sidebar:
    st.header("Lagerlayout")
    n_aisles = st.slider("Anzahl Gassen-Zonen", *bounds("n_aisles_slider"), key="n_aisles_slider")
    nodes_per_aisle = st.slider("Knoten je Gasse", *bounds("nodes_per_aisle_slider"), key="nodes_per_aisle_slider")
    hub_nodes = st.slider("Knoten im Verteiler/Hub", *bounds("hub_nodes_slider"), key="hub_nodes_slider")

    st.header("Transporter")
    trans_aisle = st.slider("Shuttle je Gasse", *bounds("trans_aisle_slider"), key="trans_aisle_slider")
    trans_hub = st.slider("Transporter im Hub", *bounds("trans_hub_slider"), key="trans_hub_slider")
    handover = st.slider("Umstiegszeit (min)", *bounds("handover_slider"), key="handover_slider")

    st.header("Auftraege")
    n_orders = st.slider("Anzahl Auftraege", *bounds("n_orders_slider"), key="n_orders_slider")
    horizon = st.slider("Zeithorizont (min)", *bounds("horizon_slider"), key="horizon_slider")
    cross_zone = st.slider("Anteil zonenuebergreifend", *bounds("cross_zone_slider"), key="cross_zone_slider")
    seed = st.number_input("Seed", *bounds("seed_input"), key="seed_input")
    st.button("Neuer Zufalls-Seed", on_click=randomize_seed)

    st.header("Beispielszenarien")
    for name in PRESETS:
        st.button(name, on_click=apply_preset, args=(name,), width='stretch')

    sync_query_params(
        {
            "n_aisles_slider": n_aisles, "nodes_per_aisle_slider": nodes_per_aisle,
            "hub_nodes_slider": hub_nodes, "trans_aisle_slider": trans_aisle,
            "trans_hub_slider": trans_hub, "handover_slider": handover,
            "n_orders_slider": n_orders, "horizon_slider": horizon,
            "cross_zone_slider": cross_zone, "seed_input": int(seed),
        }
    )


@st.cache_data
def _build_scenario(n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, seed):
    network = build_network(n_aisles, nodes_per_aisle, hub_nodes, DEFAULT_AISLE_SPEED, DEFAULT_HUB_SPEED)
    orders = generate_orders(network, n_orders, horizon, cross_zone, int(seed))
    routes = route_orders(network, orders)
    return network, orders, routes


network, orders, routes = _build_scenario(n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, seed)
transporters_per_zone = {aisle_id: trans_aisle for aisle_id in network.aisle_ids}
transporters_per_zone[network.hub_id] = trans_hub
orders_by_id = {o.order_id: o for o in orders}


@st.cache_data
def _run_own_methods(n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, seed, trans_aisle, trans_hub, handover):
    network, orders, routes = _build_scenario(n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, seed)
    tpz = {aisle_id: trans_aisle for aisle_id in network.aisle_ids}
    tpz[network.hub_id] = trans_hub

    schedules = {
        "baseline": dispatch_baseline(routes, orders, tpz, handover),
        "greedy": dispatch_greedy(routes, orders, tpz, handover),
        "coordinated": dispatch_coordinated(routes, orders, tpz, handover),
    }
    evaluations = {
        method: evaluate_schedule(schedule, routes, orders, tpz, handover) for method, schedule in schedules.items()
    }
    return schedules, evaluations


schedules, evaluations = _run_own_methods(
    n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, seed, trans_aisle, trans_hub, handover
)

# ---- Primary view: result first ----
greedy_eval = evaluations["greedy"]
coordinated_eval = evaluations["coordinated"]

st.header("Ihr optimierter Transportplan")
wait_reduction = greedy_eval.total_transfer_wait - coordinated_eval.total_transfer_wait
wait_reduction_pct = (wait_reduction / greedy_eval.total_transfer_wait * 100) if greedy_eval.total_transfer_wait > 0 else 0.0

cols = st.columns(4)
cols[0].metric("Umstiegs-Wartezeit gesamt", f"{coordinated_eval.total_transfer_wait:.0f} min", f"{-wait_reduction:.0f} min vs. dezentral")
cols[1].metric("Gesamtdurchlaufzeit", f"{coordinated_eval.total_lead_time:.0f} min")
cols[2].metric("Puenktlichkeit", f"{coordinated_eval.on_time_rate * 100:.0f}%")
cols[3].metric("Letzte Auslieferung", f"{coordinated_eval.makespan:.0f} min")

if greedy_eval.total_transfer_wait > 0:
    st.caption(
        f"Im Vergleich zur dezentralen Disposition (jede Zone optimiert nur fuer sich) spart die "
        f"zonenuebergreifend koordinierte Disposition rund {wait_reduction:.0f} Minuten Umstiegs-"
        f"Wartezeit ({wait_reduction_pct:.0f}% weniger) - Verfahren: {METHOD_LABELS[METHOD_COORDINATED]}."
    )
else:
    st.caption("Bei diesem Szenario gibt es kaum Engpaesse an Umschlagpunkten - alle Verfahren liegen nahe beieinander.")

st.plotly_chart(build_warehouse_figure(network), width='stretch')

# ---- Detail area ----
with st.expander("Wie wir das erreichen", expanded=False):
    tab_baseline, tab_greedy, tab_coordinated, tab_ortools, tab_compare, tab_animation = st.tabs(
        ["Unoptimiert", "Dezentral (Greedy)", "Koordiniert", "OR-Tools", "Vergleich", "Animation"]
    )

    with tab_baseline:
        render_method_panel(
            "baseline", schedules["baseline"], evaluations["baseline"], orders_by_id, network, transporters_per_zone,
            extra_caption="Keine Prioritaetslogik: wer zuerst bereit ist, wird zuerst bedient.",
        )

    with tab_greedy:
        render_method_panel(
            "greedy", schedules["greedy"], evaluations["greedy"], orders_by_id, network, transporters_per_zone,
            extra_caption="Jede Zone dispatcht lokal nach kuerzester Fahrzeit (SPT) - ohne Sicht auf andere Zonen.",
        )

    with tab_coordinated:
        render_method_panel(
            "coordinated", schedules["coordinated"], evaluations["coordinated"], orders_by_id, network, transporters_per_zone,
            extra_caption="Auftraege, die schon einmal umgestiegen sind, haben Vorrang; sonst gewinnt die Order mit dem meisten verbleibenden Arbeitsaufwand (Most Work Remaining).",
        )

    with tab_ortools:
        st.markdown("Exakter/naeherungsweise optimaler Solver (Google OR-Tools, CP-SAT). Button-gesteuert, da rechenintensiver als die eigenen Heuristiken.")
        time_limit = st.slider("Zeitlimit (s)", 1, MAX_ORTOOLS_TIME_LIMIT, DEFAULT_ORTOOLS_TIME_LIMIT, key="ortools_time_limit")

        cooldown_active = False
        last_run = st.session_state.get("ortools_last_run_at")
        last_limit = st.session_state.get("ortools_last_time_limit", DEFAULT_ORTOOLS_TIME_LIMIT)
        if last_run is not None:
            elapsed = time.time() - last_run
            cooldown_needed = last_limit + ORTOOLS_COOLDOWN_BUFFER_SECONDS
            cooldown_active = elapsed < cooldown_needed

        solve_clicked = st.button("Mit OR-Tools loesen", disabled=cooldown_active)
        if cooldown_active:
            st.caption(f"Kurze Abkuehlpause aktiv - noch {cooldown_needed - elapsed:.0f}s.")

        if solve_clicked:
            with st.spinner("OR-Tools loest..."):
                schedule, status = solve_ortools(routes, orders, transporters_per_zone, handover, time_limit, horizon)
            st.session_state["ortools_last_run_at"] = time.time()
            st.session_state["ortools_last_time_limit"] = time_limit
            st.session_state["ortools_schedule"] = schedule
            st.session_state["ortools_status"] = status
            st.session_state["ortools_scenario_key"] = (n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, seed, trans_aisle, trans_hub, handover)

        current_key = (n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, seed, trans_aisle, trans_hub, handover)
        stale = st.session_state.get("ortools_scenario_key") != current_key
        ortools_schedule = st.session_state.get("ortools_schedule")

        if ortools_schedule is not None and not stale:
            st.caption(f"Status: {status_label(st.session_state['ortools_status'])}")
            ortools_eval = evaluate_schedule(ortools_schedule, routes, orders, transporters_per_zone, handover)
            render_method_panel("ortools", ortools_schedule, ortools_eval, orders_by_id, network, transporters_per_zone)
        elif ortools_schedule is not None and stale:
            st.info("Eingaben haben sich geaendert - bitte erneut loesen.")
        else:
            st.info("Noch nicht geloest.")

    with tab_compare:
        compare_evals = dict(evaluations)
        ortools_schedule = st.session_state.get("ortools_schedule")
        current_key = (n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, seed, trans_aisle, trans_hub, handover)
        if ortools_schedule is not None and st.session_state.get("ortools_scenario_key") == current_key:
            compare_evals["ortools"] = evaluate_schedule(ortools_schedule, routes, orders, transporters_per_zone, handover)

        st.plotly_chart(build_kpi_comparison_figure(compare_evals), width='stretch')
        st.plotly_chart(build_transfer_wait_figure(compare_evals), width='stretch')

        rows = []
        for method, result in compare_evals.items():
            rows.append(
                {
                    "Verfahren": METHOD_LABELS.get(method, method),
                    "Gesamtdurchlaufzeit (min)": round(result.total_lead_time, 1),
                    "Umstiegs-Wartezeit (min)": round(result.total_transfer_wait, 1),
                    "Puenktlichkeit": f"{result.on_time_rate * 100:.0f}%",
                    "Letzte Auslieferung (min)": round(result.makespan, 1),
                }
            )
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

    with tab_animation:
        method_choice = st.selectbox("Verfahren fuer Animation", list(schedules.keys()), format_func=lambda m: METHOD_LABELS.get(m, m), key="anim_method")
        st.plotly_chart(build_animation_figure(schedules[method_choice], network, orders), width='stretch')

st.markdown("---")
st.caption(
    "Teil des [Operations-Research-Demo-Portfolios](https://sebastianhanisch.net/demos.html) von "
    "[Sebastian Hanisch](https://sebastianhanisch.net) - Operations Research und Machine Learning. "
    "Interesse an einer massgeschneiderten Loesung? [Kontakt aufnehmen](https://sebastianhanisch.net/kontakt.html)."
)
