"""
Lagerlogistik: Transport über mehrere Zonen mit Umschlagpunkten – interaktive Demo
Sebastian Hanisch - Operations Research und Machine Learning

Fachlich ein Pickup-and-Delivery-Problem mit Transshipment (PDPT): Ware bewegt sich
durch mehrere Zonen (Regalgassen-Shuttles + zentraler Verteiler/Lift), zonengebundene
Transporter dürfen ihre eigene Zone nicht verlassen, zonenübergreifende Aufträge
müssen an einem Umschlagpunkt auf den nächsten Transporter umsteigen. Transporter
werden einzeln mit Position geführt (nicht nur als Kapazitätszahl) - wer gerade
abgeliefert hat, muss leer zum nächsten Einsatzort fahren (Repositionierung), genau
wie ein echtes Shuttle/AGV.

Vier Dispositionsverfahren im Vergleich: Unoptimiert (FCFS), Dezentral je Zone
(Greedy: lokales SPT je Leg, blind für Repositionierungskosten), Koordiniert (eigene
Heuristik: SPT je Leg plus kleine Gewichte auf die restliche Reise des Auftrags UND
auf die Distanz zum nächsten freien Transporter) und OR-Tools (CP-SAT mit
sequenzabhängigen Rüstzeiten je Transporter). Kernthema: lokal optimale Disposition
je Zone erzeugt an Umschlagpunkten Wartezeit, die sich kaskadenartig fortpflanzt -
eine zonenübergreifend koordinierte Disposition vermeidet das systematisch. Reines
"kürzeste Restroute zuerst" ohne Repositionierungs-Gewicht wurde zuerst probiert,
verlor aber im Sweep über hunderte Zufallsszenarien öfter als es gegen Greedy bei der
Gesamtdurchlaufzeit gewann, sobald Repositionierung Teil des Modells wurde - Greedy
blieb trotz seiner Kurzsichtigkeit lokal stark genug, dass ihn zu ignorieren mehr
kostete, als die globale Sicht einbrachte. Erst das zusätzliche Gewicht auf die Distanz
zum nächsten freien Transporter (dieselbe sequenzabhängige Rüstzeit-Logik, die
OR-Tools exakt löst) macht Koordiniert wieder zuverlässig besser als Greedy - bei
beiden Kennzahlen, über mehrere Szenario-Familien geprüft.

Ein Anteil der Aufträge kann als Express markiert werden (engere Frist). Nur Koordiniert
(Prioritäts-Faktor 0,5) und OR-Tools (Gewicht 3 im Zielwert, klassische
Weighted-Completion-Time-Formulierung) nutzen die Markierung aktiv - Unoptimiert und
Greedy ignorieren sie bewusst, um zu zeigen, dass ein rein lokales/unkoordiniertes
System gesetzte Prioritäten in der Praxis oft schlicht nicht respektiert.

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
def _build_scenario(n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, express, seed):
    network = build_network(n_aisles, nodes_per_aisle, hub_nodes, DEFAULT_AISLE_SPEED, DEFAULT_HUB_SPEED)
    orders = generate_orders(network, n_orders, horizon, cross_zone, int(seed), express)
    routes = route_orders(network, orders)
    return network, orders, routes


@st.cache_data
def _run_own_methods(n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, express, seed, trans_aisle, trans_hub, handover):
    network, orders, routes = _build_scenario(n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, express, seed)
    tpz = {aisle_id: trans_aisle for aisle_id in network.aisle_ids}
    tpz[network.hub_id] = trans_hub

    schedules = {
        "baseline": dispatch_baseline(network, routes, orders, tpz, handover),
        "greedy": dispatch_greedy(network, routes, orders, tpz, handover),
        "coordinated": dispatch_coordinated(network, routes, orders, tpz, handover),
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
seiner eigenen Zone - ein Shuttle aus Gasse 2 fährt nie in Gasse 4. Muss eine Palette von
Gasse 2 zum Wareneingang in Gasse 4, wird sie am zentralen Verteiler (Hub) von einem
Gassen-Shuttle auf den Hub-Transporter umgeladen und später am Zielgassen-Anschluss noch
einmal - jede dieser Übergaben ist ein **Umschlagpunkt**. Transporter sind dabei keine
anonyme Kapazitätszahl, sondern haben eine reale Position: wer gerade abgeliefert hat, muss
leer zur nächsten Abholung fahren (**Repositionierung**), bevor er wieder Ladung aufnehmen
kann. Kernthema ist, wie stark **lokal optimale Disposition je Zone** an Umschlagpunkten
Wartezeit erzeugt und Transporter unnötig durchs Lager schickt - beides pflanzt sich
kaskadenartig fort - und wie viel eine **zonenübergreifend koordinierte Disposition** davon
vermeidet, *ohne* dabei die Gesamtdurchlaufzeit zu verschlechtern. Ein konkretes
Beispiel dazu im Abschnitt "📐 Warum lokale Optimierung an Umschlagpunkten scheitert" unten,
der komplette Ablauf eines Auftrags im Expander "Wie funktioniert diese Demo?" sowie die
Formalisierung im Expander "📐 Mathematische Formulierung".
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
    n_aisles = st.slider(
        "Anzahl Gassen-Zonen", *bounds("n_aisles_slider"), key="n_aisles_slider",
        help="Anzahl unabhängiger Regalgassen, jede mit eigener Shuttle-Flotte, alle an "
             "denselben zentralen Verteiler (Hub) angebunden.",
    )
    nodes_per_aisle = st.slider(
        "Knoten je Gasse", *bounds("nodes_per_aisle_slider"), key="nodes_per_aisle_slider",
        help="Länge einer Regalgasse in Lagerplätzen - mehr Knoten bedeuten längere "
             "Fahrzeiten innerhalb der Gasse.",
    )
    hub_nodes = st.slider(
        "Knoten im Verteiler/Hub", *bounds("hub_nodes_slider"), key="hub_nodes_slider",
        help="Länge der zentralen Förderstrecke. Wenige Knoten + viele Gassen bedeuten, "
             "dass sich mehrere Gassen denselben, kurzen Hub-Abschnitt teilen - typischer "
             "Engpass, siehe Preset 'Stoßzeit mit Engpass am Umschlagpunkt'.",
    )

    st.markdown("**Transporter**")
    trans_aisle = st.slider(
        "Shuttle je Gasse", *bounds("trans_aisle_slider"), key="trans_aisle_slider",
        help="Wie viele Shuttle gleichzeitig in derselben Gasse unterwegs sein dürfen - "
             "mehr Shuttle verringern Warteschlangen innerhalb der Gasse.",
    )
    trans_hub = st.slider(
        "Transporter im Hub", *bounds("trans_hub_slider"), key="trans_hub_slider",
        help="Wie viele Transporter gleichzeitig im zentralen Verteiler unterwegs sein "
             "dürfen. Ein einzelner Hub-Transporter ist in diesem Modell der typische "
             "Engpass, an dem sich lokale und koordinierte Disposition am stärksten "
             "unterscheiden.",
    )
    handover = st.slider(
        "Umstiegszeit (min)", *bounds("handover_slider"), key="handover_slider",
        help="Feste Zeit, die eine Übergabe an einem Umschlagpunkt braucht (Andocken, "
             "Lift, Förderband) - fällt bei jedem Zonenwechsel zusätzlich zur Fahrzeit an.",
    )

    st.markdown("**Aufträge**")
    n_orders = st.slider("Anzahl Aufträge", *bounds("n_orders_slider"), key="n_orders_slider")
    horizon = st.slider(
        "Zeithorizont (min)", *bounds("horizon_slider"), key="horizon_slider",
        help="Zeitraum, über den die Release-Zeiten der Aufträge verteilt werden - kürzerer "
             "Horizont bei gleicher Auftragszahl bedeutet mehr gleichzeitigen Andrang.",
    )
    cross_zone = st.slider(
        "Anteil zonenübergreifend", *bounds("cross_zone_slider"), key="cross_zone_slider",
        help="Anteil der Aufträge, deren Ziel in einer anderen Gasse liegt als der Ursprung "
             "- nur diese durchlaufen überhaupt einen Umschlagpunkt. Bei 0 gibt es keine "
             "Umstiege und alle vier Verfahren liefern dasselbe Ergebnis.",
    )
    express = st.slider(
        "Anteil Express-Aufträge", *bounds("express_slider"), key="express_slider",
        help="Anteil der Aufträge mit engerer Frist. Nur Koordiniert und OR-Tools nutzen "
             "das als Dispositionssignal und ziehen Express-Aufträge konsequent vor - "
             "Unoptimiert und Dezentral/Greedy ignorieren es bewusst, genau wie ein rein "
             "lokales System in der Praxis oft an gesetzten Prioritäten vorbeidisponiert.",
    )
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
        "cross_zone_slider": cross_zone, "express_slider": express, "seed_input": int(seed),
    }
)

network, orders, routes = _build_scenario(n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, express, seed)
transporters_per_zone = {aisle_id: trans_aisle for aisle_id in network.aisle_ids}
transporters_per_zone[network.hub_id] = trans_hub
orders_by_id = {o.order_id: o for o in orders}

schedules, evaluations = _run_own_methods(
    n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, express, seed, trans_aisle, trans_hub, handover
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
Processing Time, SPT) - blind dafür, wie viel Reise ein Auftrag insgesamt noch vor sich hat.

**Ein Beispiel macht sichtbar, wo das schiefgeht:** Auftrag A ist schon einmal umgestiegen
und wartet am Hub nur noch auf seinen letzten, kurzen Leg zur Zielgasse. Zur selben Zeit wird
Auftrag B frisch freigegeben - sein allererster Leg ist rein zufällig eine Idee kürzer als A's
letzter Leg. Greedy sieht in der Hub-Zone nur die beiden Legs vor sich und ihre Dauer, nicht
die Vorgeschichte der Aufträge - also gewinnt B, obwohl A eigentlich fast fertig ist. A wartet
länger, genau die Wartezeit, die vorher schon einmal an Umstieg 1 entstanden ist, addiert sich
so zu Umstieg 2. **Koordiniert** wägt zusätzlich leicht ab, wie viel Reise nach diesem Leg noch
übrig bleibt (10 % Gewicht neben der SPT-Fahrzeit) - genug, damit A den knappen Vorsprung
zurückbekommt, ohne dass Koordiniert deshalb insgesamt schlechter disponiert als Greedy: SPT
bleibt das Hauptkriterium, weil es für die Gesamtdurchlaufzeit einer einzelnen Ressource
nachweislich das Beste ist.

**Ein zweites Beispiel zeigt, warum Greedy auch bei der reinen Gesamtdurchlaufzeit
zurückfällt:** Zwei Legs werden gleichzeitig frei, einer davon am anderen Ende der Gasse als
der aktuell freie Shuttle steht, der andere direkt daneben - beide nominell fast gleich lang.
Greedy sieht nur die Fahrzeit des Legs selbst und ist bei einem Unentschieden indifferent; oft
genug schickt es den Shuttle auf die weite Leerfahrt. Diese Leerfahrt (Repositionierung) zählt
für die Auslieferung nicht mit, kostet aber echte Zeit - Greedy "sieht" sie beim Entscheiden gar
nicht. Koordiniert bezieht die Distanz zum nächsten freien Transporter mit einem zweiten
kleinen Gewicht (150 % der SPT-Fahrzeit) in die Priorität ein und bevorzugt bei ähnlich
dringenden Legs konsequent den näherliegenden - sichtbar an den hellen, schraffierten Balken im
Gantt-Chart unten (Leerfahrten), die bei Koordiniert spürbar kürzer ausfallen als bei Greedy.
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
            extra_caption="Jede Zone dispatcht lokal nach kürzester Fahrzeit (SPT) - ohne Sicht auf andere Zonen "
                          "und blind für Repositionierungskosten (helle, schraffierte Balken im Gantt-Chart).",
        )

    with tabs[2]:
        render_method_panel(
            "coordinated", schedules["coordinated"], evaluations["coordinated"], orders_by_id, network, transporters_per_zone,
            extra_caption="Wie Greedy in erster Linie kürzeste Fahrzeit (SPT), zusätzlich leicht gewichtet mit der "
                          "restlichen Reise des Auftrags UND der Entfernung zum nächsten freien Transporter - "
                          "sichtbar an kürzeren/selteneren Leerfahrten im Gantt-Chart.",
        )

    with tabs[3]:
        st.markdown(
            "Googles Open-Source-Solver OR-Tools (CP-SAT) plant nicht Schritt für Schritt wie die drei "
            "Heuristiken oben, sondern sucht direkt nach dem bestmöglichen Gesamtplan - liefert bei genug "
            "Zeit die nachweislich optimale Lösung, ist dafür aber deutlich rechenintensiver. Button-gesteuert "
            "statt automatisch bei jeder Eingabe, damit die App nicht bei jeder Reglerbewegung neu rechnet."
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
                schedule, status = solve_ortools(network, routes, orders, transporters_per_zone, handover, time_limit, horizon)
            st.session_state["ortools_last_run_at"] = time.time()
            st.session_state["ortools_last_time_limit"] = time_limit
            st.session_state["ortools_schedule"] = schedule
            st.session_state["ortools_status"] = status
            st.session_state["ortools_scenario_key"] = (n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, express, seed, trans_aisle, trans_hub, handover)

        current_key = (n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, express, seed, trans_aisle, trans_hub, handover)
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
        current_key = (n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, express, seed, trans_aisle, trans_hub, handover)
        if ortools_schedule is not None and st.session_state.get("ortools_scenario_key") == current_key:
            compare_evals["ortools"] = evaluate_schedule(ortools_schedule, routes, orders, transporters_per_zone, handover)

        st.plotly_chart(build_kpi_comparison_figure(compare_evals), width='stretch', key="kpi_comparison")
        st.plotly_chart(build_transfer_wait_figure(compare_evals), width='stretch', key="transfer_wait_compare")

        has_express = any(o.is_express for o in orders)
        rows = []
        for method, result in compare_evals.items():
            row = {
                "Verfahren": METHOD_LABELS.get(method, method),
                "Gesamtdurchlaufzeit (min)": round(result.total_lead_time, 1),
                "Umstiegs-Wartezeit (min)": round(result.total_transfer_wait, 1),
                "Pünktlichkeit": f"{result.on_time_rate * 100:.0f}%",
                "Letzte Auslieferung (min)": round(result.makespan, 1),
            }
            if has_express:
                row["Pünktlichkeit Express"] = f"{result.on_time_rate_express * 100:.0f}%"
            rows.append(row)
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
        st.caption("Alle Verfahren lösen dasselbe Szenario mit derselben Kennzahlen-Berechnung - fair vergleichbar.")
        if has_express:
            st.caption(
                "🚀 Express-Aufträge sind in der Auftragstabelle jedes Verfahrens markiert. Nur Koordiniert "
                "und OR-Tools nutzen die Markierung als Dispositionssignal - Unoptimiert und Dezentral/Greedy "
                "ignorieren sie bewusst."
            )

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

**Ein Auftrag Schritt für Schritt:** Auftrag 7 soll von einem Lagerplatz in Gasse 2 zu einer
Position in Gasse 4. *Leg 1:* Gassen-Shuttle fährt in Gasse 2 zum Hub-Anschluss, sagen wir 3
Minuten. *Umstieg 1:* feste Umstiegszeit, z. B. 1 Minute, für die Übergabe an den
Hub-Transporter - plus die Zeit, die Auftrag 7 zusätzlich warten muss, falls gerade kein
Hub-Transporter frei ist (das ist die **Umstiegs-Wartezeit**, die zentrale Kennzahl dieser
Demo). *Leg 2:* Hub-Transporter fährt quer durch den Verteiler zum Anschluss von Gasse 4, z.
B. 4 Minuten. *Umstieg 2:* wieder Umstiegszeit plus eventuelle Wartezeit, diesmal auf ein
freies Gassen-Shuttle in Gasse 4. *Leg 3:* letztes Stück zur Zielposition, z. B. 2 Minuten.
Reine Fahrzeit also 9 Minuten plus 2 Minuten Umstiegszeit = 11 Minuten bestenfalls - jede
zusätzliche Minute, die Auftrag 7 an einem der beiden Umschlagpunkte auf einen freien
Transporter wartet, zählt in die Umstiegs-Wartezeit, die im Vergleich unten je Verfahren
sichtbar wird.

**Repositionierung:** "Frei" heißt nicht "vor Ort". Steht der einzige freie Gassen-Shuttle
in Gasse 2 gerade am anderen Ende der Gasse, muss er erst leer zum Lagerplatz von Auftrag 7
fahren, bevor Leg 1 überhaupt beginnt - diese Leerfahrt zählt real mit, auch wenn sie in
keiner der drei Kennzahlen "Leg" explizit auftaucht. Im Gantt-Chart (Tab "Wie wir das
erreichen") sind Leerfahrten als helle, schraffierte Balken vor dem eigentlichen Leg
sichtbar. Jeder Transporter startet die Simulation an seinem Zonen-Eingang; danach hängt
seine Position immer von seinem letzten Auftrag ab.

**Aufträge:** Bekommen Ursprung, Ziel und eine Release-Zeit; ein einstellbarer Anteil ist
bewusst zonenübergreifend, damit Umstiege im Standardfall tatsächlich auftreten - sonst zeigt
der Kernvergleich unten keinen Unterschied (siehe Preset "Kleines Lager, wenig Verkehr").

**Express-Aufträge (🚀):** Ein einstellbarer Anteil der Aufträge bekommt eine engere Frist
(Faktor 1,5 statt 3,0 auf die theoretische Mindestlaufzeit). Interessant ist nicht die
Frist selbst, sondern wer sie überhaupt beachtet: Unoptimiert und Dezentral/Greedy ignorieren
die Markierung bewusst - beide bleiben bei ihrer jeweiligen Logik (Ankunftsreihenfolge bzw.
kürzeste Fahrzeit), egal ob ein Auftrag als dringend markiert ist oder nicht. Das ist keine
Vereinfachung, sondern der Punkt: ein rein lokales oder unkoordiniertes System disponiert in
der Praxis oft tatsächlich an gesetzten Prioritäten vorbei, weil es sie schlicht nicht als
Signal nutzt. Koordiniert und OR-Tools tun das dagegen aktiv (Details unten je Verfahren).

**Vier Dispositionsverfahren, alle mit derselben Kennzahlen-Berechnung ausgewertet:**
- **Unoptimiert (FCFS):** keine Prioritätslogik, wer zuerst bereit ist, wird zuerst bedient.
- **Dezentral/Greedy:** jede Zone dispatcht lokal nach kürzester Fahrzeit des aktuellen Legs
  (Shortest Processing Time, SPT) - für eine einzelne Ressource nachweislich optimal zur
  Minimierung der Summe der Fertigstellungszeiten, aber blind dafür, wie viel Reise ein
  Auftrag über die eigene Zone hinaus noch vor sich hat UND blind dafür, wo die eigenen
  Transporter gerade stehen - es kann einen Shuttle quer durchs Lager schicken, wenn dessen
  Leg nominell am kürzesten ist, egal wie weit die Leerfahrt dorthin wäre.
- **Koordiniert:** eine eigene Heuristik, die SPT als dominantes Kriterium beibehält, die
  Priorität aber zusätzlich mit zwei kleinen Gewichten versieht: 10 % auf die restliche
  Reise des Auftrags über alle Zonen hinweg, und 150 % auf die Entfernung zum nächsten
  freien Transporter. Eine erste Fassung ganz ohne Positionsbewusstsein (nur SPT + Restroute)
  verlor im Test über hunderte Zufallsszenarien öfter als sie gegen Greedy bei der
  Gesamtdurchlaufzeit gewann, sobald Transporter überhaupt repositionieren mussten - Greedys
  lokale SPT-Stärke reichte trotz ihrer Kurzsichtigkeit oft aus, das komplett zu ignorieren
  kostete mehr, als die Restroute-Sicht einbrachte. Erst das zusätzliche Positions-Gewicht
  macht Koordiniert wieder zuverlässig besser als Greedy, bei beiden Kennzahlen, über
  mehrere Szenario-Familien geprüft. Express-Aufträge bekommen zusätzlich einen
  Prioritäts-Bonus (die gesamte Priorität wird mit 0,5 multipliziert, niedriger = früher
  dran) - dieselbe Logik, nur konsequent nach vorn gezogen.
- **OR-Tools (CP-SAT):** jeder Leg ist ein Intervall fester Dauer. Weil Repositionierung
  davon abhängt, WELCHER Transporter einen Leg übernimmt, sind Transporter hier keine
  anonyme Kapazität mehr wie zuvor ohne Repositionierung: jeder Leg bekommt eine
  Maschinen-Variable (welcher der c_z Transporter der Zone ihn übernimmt), und für jedes
  Legpaar auf demselben Transporter erzwingt eine Präzedenzbedingung die reale
  Repositionierungszeit dazwischen - ein Standardmuster für "parallele Maschinen mit
  sequenzabhängigen Rüstzeiten". Ziel: minimale **gewichtete** Gesamtdurchlaufzeit -
  Express-Aufträge zählen 3-fach im Zielwert (klassische Weighted-Completion-Time-
  Formulierung), das genaue Analogon zu Koordiniert's Prioritäts-Bonus, nur als echtes
  Optimierungsziel statt als Heuristik-Regel. Button-gesteuert mit Zeitlimit und Cooldown,
  da rechenintensiver als die eigenen Heuristiken.

**Kern-Kennzahlen:** Nicht nur die Gesamtdurchlaufzeit, sondern ausdrücklich die **kumulierte
Umstiegs-Wartezeit** - genau die Größe, die bei rein lokaler Disposition unbemerkt wächst,
während die Gesamtdurchlaufzeit oft ähnlich aussieht - sowie, wenn Express-Aufträge aktiv
sind, deren **Pünktlichkeit** separat von der Gesamtpünktlichkeit.

**In einem echten Lager** kämen weitere Nebenbedingungen dazu (Batterie-/Ladezyklen der
Shuttles, mehrstöckige Hub-Topologien, tatsächliche Kollisionsvermeidung innerhalb einer
Gasse) - das Grundprinzip aus Zonenbindung, Umschlagpunkten und den vier
Dispositionsverfahren bleibt aber dasselbe.
"""
    )

with st.expander("📐 Mathematische Formulierung"):
    st.markdown(
        r"""
**In Worten, vor der Notation:** Gesucht ist für jeden Leg jedes Auftrags ein Startzeitpunkt,
der die Summe aller Durchlaufzeiten (Ankunft minus Freigabe) minimiert - unter drei Arten von
Nebenbedingungen: (1) ein Auftrag darf seinen nächsten Leg erst antreten, wenn der vorige
fertig ist UND die Umstiegszeit verstrichen ist, (2) eine Zone kann zu keinem Zeitpunkt mehr
Legs gleichzeitig bedienen, als sie Transporter hat, und (3) folgen zwei Legs auf demselben
Transporter aufeinander, muss dazwischen genug Zeit für die reale Repositionierungsfahrt
liegen. Formal:

Gegeben ein Auftrag $o$ mit einer Folge von Legs $\ell \in \{1, \ldots, L_o\}$ (Zone,
Ein-/Ausstiegsknoten, feste Fahrzeit $d_{o,\ell}$), eine Release-Zeit $r_o$, eine feste
Umstiegszeit $h$, je Zone $z$ eine Transporteranzahl $c_z$, und ein Gewicht $w_o$ (3 für
Express-Aufträge, sonst 1). Gesucht sind Startzeiten $s_{o,\ell} \geq 0$ für jeden Leg, die
den gesamten Auftragsbestand bedienen und die **gewichtete** Gesamtdurchlaufzeit
minimieren:
"""
    )
    st.latex(r"\min \; \sum_{o} w_o \Big( s_{o,L_o} + d_{o,L_o} - r_o \Big)")
    st.latex(r"s_{o,1} \geq r_o \qquad \forall o")
    st.latex(r"s_{o,\ell+1} \geq s_{o,\ell} + d_{o,\ell} + h \qquad \forall o,\, \ell < L_o \quad \text{(Umstiegssynchronisation)}")
    st.markdown(
        r"""
Weil die Repositionierungszeit zwischen zwei Legs davon abhängt, WELCHER konkrete Transporter
beide übernimmt, bekommt jeder Leg $(o,\ell)$ in Zone $z$ eine Maschinen-Variable
$m_{o,\ell} \in \{0, \ldots, c_z - 1\}$ (welcher der $c_z$ Transporter ihn fährt). Für jedes
Paar von Legs $(o,\ell)$, $(o',\ell')$ in derselben Zone gilt dann, sequenzabhängig auf dem
gleichen Transporter:
"""
    )
    st.latex(
        r"m_{o,\ell} = m_{o',\ell'} \;\Rightarrow\; "
        r"\Big[ s_{o',\ell'} \geq s_{o,\ell} + d_{o,\ell} + \rho\big(x_{o,\ell}, e_{o',\ell'}\big) \Big]"
        r"\;\lor\; \Big[ s_{o,\ell} \geq s_{o',\ell'} + d_{o',\ell'} + \rho\big(x_{o',\ell'}, e_{o,\ell}\big) \Big]"
    )
    st.markdown(
        r"""
$x_{o,\ell}$ ist der Ausstiegsknoten von Leg $(o,\ell)$, $e_{o,\ell}$ sein Einstiegsknoten,
$\rho(\cdot,\cdot)$ die reale Fahrzeit zwischen zwei Knoten in dieser Zone
(`network.travel_time`). In Worten: landen zwei Legs auf demselben Transporter, muss einer
den anderen vollständig samt Repositionierungsfahrt abschließen, bevor der andere beginnt -
auf verschiedenen Transportern gibt es dagegen gar keine Bedingung zwischen ihnen (das ist es,
was gleichzeitiges Arbeiten überhaupt erlaubt). Ein Standardmuster für **parallele Maschinen
mit sequenzabhängigen Rüstzeiten**, im Code über paarweise reifizierte Nebenbedingungen
umgesetzt (`warehouse_ortools_solver.py`) - bewusst keine `AddCumulative`-Kapazitätsformel
mehr wie vor Einführung der Repositionierung, weil Transporter innerhalb einer Zone dafür
austauschbar sein müssten, was mit positionsabhängigen Rüstzeiten nicht mehr gilt.

Die drei eigenen Heuristiken lösen strukturell dasselbe Problem über eine ereignisgesteuerte
Simulation (`warehouse_dispatch_core.py`): sobald ein Transporter frei wird UND mindestens ein
Leg bereit ist, wird der Leg mit der höchsten Priorität zugewiesen, dann - unter allen gerade
freien Transportern der Zone - der mit der geringsten Repositionierungsfahrt zu diesem Leg.
Start = aktueller Zeitpunkt plus diese Fahrzeit. Die drei Verfahren unterscheiden sich
ausschließlich in der Prioritätsfunktion: konstant bei FCFS, kürzeste Fahrzeit des aktuellen
Legs bei Greedy, und bei Koordiniert
"""
    )
    st.latex(
        r"\text{Priorität}(o,\ell) = p_o \cdot \Big( d_{o,\ell} + 0{,}1 \cdot \sum_{k > \ell} \big(d_{o,k} + h\big)"
        r" + 1{,}5 \cdot \min_{\text{frei } t} \rho(t, e_{o,\ell}) \Big), \qquad p_o = 0{,}5 \text{ falls } o \text{ Express, sonst } 1"
    )
    st.markdown(
        r"""
Dieselbe kürzeste-Fahrzeit-Logik wie Greedy ($d_{o,\ell}$), plus ein kleines Gewicht (10 %)
auf die gesamte noch verbleibende Reise nach dem aktuellen Leg, plus ein zweites Gewicht
(150 %) auf die Fahrzeit zum NÄCHSTEN gerade freien Transporter $t$ - beides zusammen mit
$p_o$ skaliert, niedrigerer Wert wird zuerst bedient. Eine erste Fassung ohne den
Repositionierungs-Term verlor im Test über hunderte Zufallsszenarien öfter als sie gegen
Greedy bei der Gesamtdurchlaufzeit gewann, sobald Transporter überhaupt repositionieren
mussten - dieselbe Simulationslogik, aber drei verschiedene Dispatchregeln, deren einziger
Unterschied diese eine Formel ist (FCFS: Priorität konstant 0; Greedy: $p_o \equiv 1$, kein
Restroute- und kein Repositionierungs-Term).
"""
    )

st.markdown("---")
st.caption(
    "Diese Demo ist Teil des Portfolios von [Sebastian Hanisch](https://sebastianhanisch.net) – "
    "Operations Research und Machine Learning. Interesse an einer maßgeschneiderten Lösung für "
    "Ihr Unternehmen? [Kontakt aufnehmen](https://sebastianhanisch.net/kontakt.html)"
)
