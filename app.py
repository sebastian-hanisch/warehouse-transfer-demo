"""
Lagerlogistik: Transport über mehrere Zonen mit Umschlagpunkten – interaktive Demo
Sebastian Hanisch - Operations Research und Machine Learning

Fachlich ein Pickup-and-Delivery-Problem mit Transshipment (PDPT): Ware bewegt sich
durch mehrere Zonen (Regalgassen-Shuttles + zentraler Verteiler/Lift), zonengebundene
Transporter dürfen ihre eigene Zone nicht verlassen, zonenübergreifende Aufträge
müssen an einem Umschlagpunkt auf den nächsten Transporter umsteigen.

Vier Dispositionsverfahren im Vergleich: Unoptimiert (FCFS), Dezentral je Zone
(Greedy: lokales SPT je Leg), Koordiniert (eigene Heuristik: SPT je Leg plus ein
kleines Gewicht auf die restliche Reise des Auftrags) und OR-Tools (CP-SAT).
Kernthema: lokal optimale Disposition je Zone erzeugt an Umschlagpunkten Wartezeit,
die sich kaskadenartig fortpflanzt - eine zonenübergreifend koordinierte Disposition
vermeidet das systematisch. Reines "kürzeste Restroute zuerst" (ohne SPT-Gewicht)
wurde zuerst probiert, verlor aber im Sweep über hunderte Zufallsszenarien öfter als
es gegen Greedy bei der Gesamtdurchlaufzeit gewann - SPT ist für eine einzelne
Ressource nachweislich optimal, das komplett zu verwerfen kostet lokal mehr, als die
globale Sicht gewinnt. Die aktuelle, leicht gewichtete Fassung schlägt Greedy
zuverlässig bei beiden Kennzahlen.

Selbe Struktur wie bei den anderen Demos in diesem Workspace: Ergebnis zuerst,
vollständiger Methodenvergleich sekundär im Expander, dazu "Wie funktioniert diese
Demo?" und "Mathematische Formulierung" als eigene Expander.

Code-Struktur: Modell, Dispositionsverfahren, Kennzahlen, PDF-Export und
Visualisierung liegen in den Modulen warehouse_*.py neben dieser Datei.
"""

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
from warehouse_pdf_export import generate_dispatch_pdf
from warehouse_presets import (
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

PRESET_BUTTONS = {
    "Kleines Lager, wenig Verkehr": (
        "🏬",
        "Kaum Engpässe an Umschlagpunkten – alle vier Verfahren liegen nah beieinander. "
        "Zeigt: Koordination hilft nur, wenn Kapazität tatsächlich knapp ist.",
    ),
    "Stoßzeit mit Engpass am Umschlagpunkt": (
        "⚠️",
        "Nur ein Hub-Transporter, viele zonenübergreifende Aufträge – die Lücke zwischen "
        "dezentraler und koordinierter Disposition ist hier am deutlichsten sichtbar "
        "(bewusst geprüft, nicht zufällig getroffen).",
    ),
    "Großes Lager": (
        "🏭",
        "4 Gassen-Zonen, 40 Aufträge – Stresstest für die Rechenzeit des OR-Tools-Solvers "
        "bei größerem Format.",
    ),
}


@st.cache_data
def _build_scenario(n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, seed):
    network = build_network(n_aisles, nodes_per_aisle, hub_nodes, DEFAULT_AISLE_SPEED, DEFAULT_HUB_SPEED)
    orders = generate_orders(network, n_orders, horizon, cross_zone, int(seed))
    routes = route_orders(network, orders)
    return network, orders, routes


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


st.set_page_config(page_title="Lagerlogistik – Sebastian Hanisch", layout="wide")

st.title("🏭 Lagerlogistik: Umschlagpunkte")
st.markdown(
    """
Interaktive Demo zu einem automatisierten Hochregallager: Ware bewegt sich durch mehrere
**Zonen** (Regalgassen-Shuttles + ein zentraler Verteiler/Lift). Jeder Transporter bleibt in
seiner eigenen Zone - Aufträge, die zonenübergreifend müssen, "steigen" an einem
**Umschlagpunkt** auf den nächsten Transporter um. Kernthema ist, wie stark **lokal optimale
Disposition je Zone** an Umschlagpunkten Wartezeit erzeugt, die sich kaskadenartig
fortpflanzt - und wie viel eine **zonenübergreifend koordinierte Disposition** davon
vermeidet. Hintergrund im Expander "Wie funktioniert diese Demo?" unten sowie formal
hergeleitet im Expander "📐 Mathematische Formulierung".
"""
)

st.caption("🎯 Schnellstart – ein Beispielszenario laden:")
preset_cols = st.columns(len(PRESET_BUTTONS))
for col, name in zip(preset_cols, PRESET_BUTTONS):
    emoji, help_text = PRESET_BUTTONS[name]
    with col:
        st.button(f"{emoji} {name}", width='stretch', on_click=apply_preset, args=(name,), help=help_text)

st.caption(
    "🔗 Die Adresszeile oben spiegelt Ihre aktuelle Konfiguration wider – einfach kopieren, "
    "um ein Szenario zu teilen."
)

load_permalink_settings()
init_session_state_defaults()

with st.sidebar:
    st.header("⚙️ Einstellungen")

    st.markdown("**Lagerlayout**")
    n_aisles = st.slider("Anzahl Gassen-Zonen", *bounds("n_aisles_slider"), key="n_aisles_slider")
    nodes_per_aisle = st.slider("Knoten je Gasse", *bounds("nodes_per_aisle_slider"), key="nodes_per_aisle_slider")
    hub_nodes = st.slider("Knoten im Verteiler/Hub", *bounds("hub_nodes_slider"), key="hub_nodes_slider")

    st.markdown("**Transporter**")
    trans_aisle = st.slider("Shuttle je Gasse", *bounds("trans_aisle_slider"), key="trans_aisle_slider")
    trans_hub = st.slider("Transporter im Hub", *bounds("trans_hub_slider"), key="trans_hub_slider")
    handover = st.slider("Umstiegszeit (min)", *bounds("handover_slider"), key="handover_slider")

    st.markdown("**Aufträge**")
    n_orders = st.slider("Anzahl Aufträge", *bounds("n_orders_slider"), key="n_orders_slider")
    horizon = st.slider("Zeithorizont (min)", *bounds("horizon_slider"), key="horizon_slider")
    cross_zone = st.slider("Anteil zonenübergreifend", *bounds("cross_zone_slider"), key="cross_zone_slider")
    seed_lo, seed_hi = bounds("seed_input")
    seed = st.number_input("Zufalls-Seed", min_value=seed_lo, max_value=seed_hi, step=1, key="seed_input")

    st.button(
        "🎲 Neuer Zufalls-Seed", width='stretch', on_click=randomize_seed,
        help="Würfelt einen neuen Zufalls-Seed für die Auftragsgenerierung.",
    )

sync_query_params(
    {
        "n_aisles_slider": n_aisles, "nodes_per_aisle_slider": nodes_per_aisle,
        "hub_nodes_slider": hub_nodes, "trans_aisle_slider": trans_aisle,
        "trans_hub_slider": trans_hub, "handover_slider": handover,
        "n_orders_slider": n_orders, "horizon_slider": horizon,
        "cross_zone_slider": cross_zone, "seed_input": int(seed),
    }
)

network, orders, routes = _build_scenario(n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, seed)
transporters_per_zone = {aisle_id: trans_aisle for aisle_id in network.aisle_ids}
transporters_per_zone[network.hub_id] = trans_hub
orders_by_id = {o.order_id: o for o in orders}

schedules, evaluations = _run_own_methods(
    n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, seed, trans_aisle, trans_hub, handover
)

# ---- Primary view: result first ----
greedy_eval = evaluations["greedy"]
coordinated_eval = evaluations["coordinated"]

st.markdown("## 🎯 Ihr optimierter Transportplan")

wait_reduction = greedy_eval.total_transfer_wait - coordinated_eval.total_transfer_wait
wait_reduction_pct = (wait_reduction / greedy_eval.total_transfer_wait * 100) if greedy_eval.total_transfer_wait > 0 else 0.0

m1, m2, m3, m4 = st.columns(4)
m1.metric(
    "Umstiegs-Wartezeit gesamt", f"{coordinated_eval.total_transfer_wait:.0f} min",
    delta=f"{-wait_reduction:.0f} min ggü. dezentral", delta_color="inverse",
)
m2.metric("Gesamtdurchlaufzeit", f"{coordinated_eval.total_lead_time:.0f} min")
m3.metric("Pünktlichkeit", f"{coordinated_eval.on_time_rate * 100:.0f}%")
m4.metric("Letzte Auslieferung", f"{coordinated_eval.makespan:.0f} min")

if greedy_eval.total_transfer_wait > 0:
    st.success(
        f"💡 Im Vergleich zur dezentralen Disposition (jede Zone optimiert nur für sich) spart die "
        f"zonenübergreifend koordinierte Disposition rund **{wait_reduction:.0f} Minuten** "
        f"Umstiegs-Wartezeit ({wait_reduction_pct:.0f}% weniger) - Verfahren: "
        f"{METHOD_LABELS[METHOD_COORDINATED]}."
    )
else:
    st.info("Bei diesem Szenario gibt es kaum Engpässe an Umschlagpunkten - alle Verfahren liegen nah beieinander.")

st.plotly_chart(build_warehouse_figure(network), width='stretch', key="warehouse_figure_primary")

pdf_bytes = generate_dispatch_pdf(METHOD_COORDINATED, coordinated_eval, orders_by_id)
st.download_button(
    "📄 Transportplan als PDF herunterladen", data=pdf_bytes,
    file_name="transportplan.pdf", mime="application/pdf", key="pdf_primary",
)

# ---- Core theme, front and center ----
st.markdown("---")
st.subheader("📐 Warum lokale Optimierung an Umschlagpunkten scheitert")
st.markdown(
    """
Alle drei eigenen Verfahren unten lösen **exakt dasselbe Szenario** (gleicher Lagergraph,
gleiche Transporterzahl, gleiche Aufträge) - sie unterscheiden sich nur darin, in welcher
Reihenfolge ein frei werdender Transporter unter mehreren wartenden Aufträgen wählt.
**Dezentral/Greedy** wählt lokal je Zone die kürzeste Fahrzeit des aktuellen Legs (Shortest
Processing Time) - blind dafür, wie viel Reise ein Auftrag insgesamt noch vor sich hat.
**Koordiniert** übernimmt dasselbe SPT-Prinzip als dominantes Kriterium, gewichtet die
Priorität aber zusätzlich leicht mit der restlichen Reise des Auftrags über alle Zonen
hinweg - genug, um einen fast fertigen Auftrag nicht laufend von frischeren Aufträgen mit
marginal kürzerem aktuellem Leg überholen zu lassen, ohne den Effizienzvorteil von SPT
selbst zu verlieren.
"""
)
core_evals = {"baseline": evaluations["baseline"], "greedy": greedy_eval, "coordinated": coordinated_eval}
st.plotly_chart(build_transfer_wait_figure(core_evals), width='stretch', key="transfer_wait_core")

st.markdown("---")

# ---- Detail area ----
with st.expander("🔧 Wie wir das erreichen – vollständiger Methodenvergleich", expanded=False):
    tabs = st.tabs(["⏱️ Unoptimiert", "🏭 Dezentral (Greedy)", "🔗 Koordiniert", "✅ OR-Tools", "📊 Vergleich", "🎬 Animation"])

    with tabs[0]:
        render_method_panel(
            "baseline", schedules["baseline"], evaluations["baseline"], orders_by_id, network, transporters_per_zone,
            extra_caption="Keine Prioritätslogik: wer zuerst bereit ist, wird zuerst bedient.",
        )

    with tabs[1]:
        render_method_panel(
            "greedy", schedules["greedy"], evaluations["greedy"], orders_by_id, network, transporters_per_zone,
            extra_caption="Jede Zone dispatcht lokal nach kürzester Fahrzeit (SPT) - ohne Sicht auf andere Zonen.",
        )

    with tabs[2]:
        render_method_panel(
            "coordinated", schedules["coordinated"], evaluations["coordinated"], orders_by_id, network, transporters_per_zone,
            extra_caption="Wie Greedy in erster Linie kürzeste Fahrzeit (SPT), zusätzlich leicht gewichtet "
                          "mit der restlichen Reise des Auftrags über alle Zonen hinweg.",
        )

    with tabs[3]:
        st.markdown(
            "Exakter bzw. näherungsweise optimaler Solver (Google OR-Tools, CP-SAT). Button-gesteuert, da "
            "rechenintensiver als die eigenen Heuristiken."
        )
        time_limit = st.slider("Zeitlimit (s)", 1, MAX_ORTOOLS_TIME_LIMIT, DEFAULT_ORTOOLS_TIME_LIMIT, key="ortools_time_limit")

        cooldown_active = False
        last_run = st.session_state.get("ortools_last_run_at")
        last_limit = st.session_state.get("ortools_last_time_limit", DEFAULT_ORTOOLS_TIME_LIMIT)
        if last_run is not None:
            elapsed = time.time() - last_run
            cooldown_needed = last_limit + ORTOOLS_COOLDOWN_BUFFER_SECONDS
            cooldown_active = elapsed < cooldown_needed

        solve_clicked = st.button("Mit OR-Tools lösen", disabled=cooldown_active)
        if cooldown_active:
            st.caption(f"Kurze Abkühlpause aktiv - noch {cooldown_needed - elapsed:.0f}s.")

        if solve_clicked:
            with st.spinner("OR-Tools löst..."):
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
            st.info("Eingaben haben sich geändert - bitte erneut lösen.")
        else:
            st.info("Noch nicht gelöst.")

    with tabs[4]:
        compare_evals = dict(evaluations)
        ortools_schedule = st.session_state.get("ortools_schedule")
        current_key = (n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, seed, trans_aisle, trans_hub, handover)
        if ortools_schedule is not None and st.session_state.get("ortools_scenario_key") == current_key:
            compare_evals["ortools"] = evaluate_schedule(ortools_schedule, routes, orders, transporters_per_zone, handover)

        st.plotly_chart(build_kpi_comparison_figure(compare_evals), width='stretch', key="kpi_comparison")
        st.plotly_chart(build_transfer_wait_figure(compare_evals), width='stretch', key="transfer_wait_compare")

        rows = []
        for method, result in compare_evals.items():
            rows.append(
                {
                    "Verfahren": METHOD_LABELS.get(method, method),
                    "Gesamtdurchlaufzeit (min)": round(result.total_lead_time, 1),
                    "Umstiegs-Wartezeit (min)": round(result.total_transfer_wait, 1),
                    "Pünktlichkeit": f"{result.on_time_rate * 100:.0f}%",
                    "Letzte Auslieferung (min)": round(result.makespan, 1),
                }
            )
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
        st.caption("Alle Verfahren lösen dasselbe Szenario mit derselben Kennzahlen-Berechnung - fair vergleichbar.")

    with tabs[5]:
        method_choice = st.selectbox(
            "Verfahren für Animation", list(schedules.keys()), format_func=lambda m: METHOD_LABELS.get(m, m), key="anim_method",
        )
        st.plotly_chart(build_animation_figure(schedules[method_choice], network, orders), width='stretch', key="animation")

with st.expander("Wie funktioniert diese Demo?"):
    st.markdown(
        """
**Die Problemstellung:** In einem automatisierten Hochregallager sind Transporter
zonengebunden - ein Shuttle in Regalgasse A kann nicht einfach in Regalgasse B weiterfahren.
Ware, die zwischen Zonen muss, wird an einem **Umschlagpunkt** von einem Transporter auf den
nächsten übergeben. Fachlich ist das ein **Pickup-and-Delivery-Problem mit Transshipment
(PDPT)** - ein etabliertes Sonderproblem der Tourenplanung (VRP), bei dem Ladung an
definierten Punkten das Fahrzeug wechseln darf.

**Lagerlayout:** Hub-and-Spoke - mehrere Gassen-Zonen hängen an einer zentralen
Verteiler-Zone (schnellere Förderstrecke/Lift). Jede Gasse hat genau einen Umschlagpunkt zum
Hub. Ein zonenübergreifender Auftrag durchläuft damit bis zu drei **Legs**: Gasse → Hub →
Zielgasse, mit einer festen Umstiegszeit an jedem der beiden Umschlagpunkte.

**Aufträge:** Bekommen Ursprung, Ziel und eine Release-Zeit; ein einstellbarer Anteil ist
bewusst zonenübergreifend, damit Umstiege im Standardfall tatsächlich auftreten - sonst zeigt
der Kernvergleich unten keinen Unterschied (siehe Preset "Kleines Lager, wenig Verkehr").

**Vier Dispositionsverfahren, alle mit derselben Kennzahlen-Berechnung ausgewertet:**
- **Unoptimiert (FCFS):** keine Prioritätslogik, wer zuerst bereit ist, wird zuerst bedient.
- **Dezentral/Greedy:** jede Zone dispatcht lokal nach kürzester Fahrzeit des aktuellen Legs
  (Shortest Processing Time, SPT) - für eine einzelne Ressource nachweislich optimal zur
  Minimierung der Summe der Fertigstellungszeiten, aber blind dafür, wie viel Reise ein
  Auftrag über die eigene Zone hinaus noch vor sich hat.
- **Koordiniert:** eine eigene Heuristik, die SPT als dominantes Kriterium beibehält, die
  Priorität aber zusätzlich mit einem kleinen Gewicht (10 %) auf die restliche Reise des
  Auftrags über alle Zonen hinweg versieht. Eine erste Fassung, die *nur* nach kürzester
  Restroute sortierte (SPT komplett verworfen), verlor im Test über hunderte
  Zufallsszenarien öfter als sie gegen Greedy bei der Gesamtdurchlaufzeit gewann - SPTs
  Optimalität für eine einzelne Ressource ist real, sie ganz aufzugeben kostet lokal mehr,
  als die globale Sicht einbringt. Die leicht gewichtete Fassung gewinnt zuverlässig bei
  beiden Kennzahlen.
- **OR-Tools (CP-SAT):** jeder Leg ist ein Intervall fester Dauer, `AddCumulative` je Zone
  begrenzt gleichzeitig aktive Legs auf die Anzahl Transporter, eine Präzedenzbedingung
  erzwingt die Umstiegssynchronisation. Ziel: minimale Gesamtdurchlaufzeit. Button-gesteuert
  mit Zeitlimit und Cooldown, da rechenintensiver als die eigenen Heuristiken.

**Kern-Kennzahl:** Nicht nur die Gesamtdurchlaufzeit, sondern ausdrücklich die **kumulierte
Umstiegs-Wartezeit** - genau die Größe, die bei rein lokaler Disposition unbemerkt wächst,
während die Gesamtdurchlaufzeit oft ähnlich aussieht.

**In einem echten Lager** kämen weitere Nebenbedingungen dazu (Batterie-/Ladezyklen der
Shuttles, Prioritätsklassen je Auftrag, mehrstöckige Hub-Topologien) - das Grundprinzip aus
Zonenbindung, Umschlagpunkten und den vier Dispositionsverfahren bleibt aber dasselbe.
"""
    )

with st.expander("📐 Mathematische Formulierung"):
    st.markdown(
        r"""
Gegeben ein Auftrag $o$ mit einer Folge von Legs $\ell \in \{1, \ldots, L_o\}$ (Zone,
Ein-/Ausstiegsknoten, feste Fahrzeit $d_{o,\ell}$), eine Release-Zeit $r_o$, eine feste
Umstiegszeit $h$ und je Zone $z$ eine Transporteranzahl $c_z$. Gesucht sind Startzeiten
$s_{o,\ell} \geq 0$ für jeden Leg, die den gesamten Auftragsbestand bedienen und die
Gesamtdurchlaufzeit minimieren:
"""
    )
    st.latex(r"\min \; \sum_{o} \Big( s_{o,L_o} + d_{o,L_o} - r_o \Big)")
    st.latex(r"s_{o,1} \geq r_o \qquad \forall o")
    st.latex(r"s_{o,\ell+1} \geq s_{o,\ell} + d_{o,\ell} + h \qquad \forall o,\, \ell < L_o \quad \text{(Umstiegssynchronisation)}")
    st.latex(
        r"\sum_{o,\ell:\; \text{zone}(o,\ell) = z,\; s_{o,\ell} \leq t < s_{o,\ell}+d_{o,\ell}} 1 \;\leq\; c_z"
        r"\qquad \forall z,\, \forall t \quad \text{(Kapazität je Zone)}"
    )
    st.markdown(
        r"""
Die zweite Zeile ist die eigentliche Umstiegsbedingung: der nächste Leg eines Auftrags darf
erst starten, wenn der vorige Leg abgeschlossen UND die Umstiegszeit verstrichen ist - das
koppelt sonst unabhängige Zonen-Zeitpläne aneinander. Die dritte Zeile ist eine
**Kapazitätsnebenbedingung je Zone** (zu jedem Zeitpunkt höchstens $c_z$ gleichzeitig aktive
Legs) - im Code über `AddCumulative` je Zone umgesetzt (`warehouse_ortools_solver.py`), da
Transporter innerhalb einer Zone austauschbar sind und keine individuelle Zuordnung nötig ist.

Die drei eigenen Heuristiken lösen strukturell dasselbe Problem über eine ereignisgesteuerte
Simulation (`warehouse_dispatch_core.py`): sobald ein Transporter frei wird UND mindestens ein
Leg bereit ist, wird der Leg mit der höchsten Priorität zugewiesen - Start = aktueller
Zeitpunkt. Die drei Verfahren unterscheiden sich ausschließlich in der Prioritätsfunktion:
konstant bei FCFS, kürzeste Fahrzeit des aktuellen Legs bei Greedy, und bei Koordiniert
"""
    )
    st.latex(r"\text{Priorität}(o,\ell) = d_{o,\ell} + 0{,}1 \cdot \sum_{k > \ell} \big(d_{o,k} + h\big)")
    st.markdown(
        r"""
Dieselbe kürzeste-Fahrzeit-Logik wie Greedy ($d_{o,\ell}$), plus ein kleines Gewicht
(10 %) auf die gesamte noch verbleibende Reise nach dem aktuellen Leg. Eine erste
Fassung ohne den $d_{o,\ell}$-Term (reine Sortierung nach Restroute) verlor im Test
über hunderte Zufallsszenarien öfter als sie gegen Greedy bei der Gesamtdurchlaufzeit
gewann - dieselbe Simulationslogik, aber drei verschiedene Dispatchregeln.
"""
    )

st.markdown("---")
st.caption(
    "Diese Demo ist Teil des Portfolios von [Sebastian Hanisch](https://sebastianhanisch.net) – "
    "Operations Research und Machine Learning. Interesse an einer maßgeschneiderten Lösung für "
    "Ihr Unternehmen? [Kontakt aufnehmen](https://sebastianhanisch.net/kontakt.html)"
)
