"""
Lagerlogistik: Transport über mehrere Zonen mit Umschlagpunkten – interaktive Demo
Sebastian Hanisch - Operations Research und Machine Learning

Fachlich das Gesamtbild eines Pickup-and-Delivery-Problems mit Transshipment (PDPT,
eine VRP-Familie): Ware bewegt sich durch mehrere Zonen (Regalgassen-Shuttles +
zentraler Verteiler/Lift), zonengebundene Transporter dürfen ihre eigene Zone nicht
verlassen, zonenübergreifende Aufträge müssen an einem Umschlagpunkt auf den nächsten
Transporter umsteigen. Die Zonenfolge je Auftrag ist beim Hub-and-Spoke-Layout fix
(Gasse -> Hub -> Zielgasse oder nur die eigene Gasse, `warehouse_routing.py`) - aber
WELCHES Leg ein Transporter als nächstes übernimmt, ist eine echte
Sequenzierungsentscheidung mit einer Distanzmatrix dazwischen (Repositionierungszeit
zwischen Ausstiegsknoten des einen und Einstiegsknoten des nächsten Legs) - strukturell
dieselbe Kombinatorik wie eine VRP-Tour für ein einzelnes Fahrzeug, keine andere. Was
diese Aufgabe näher an die Scheduling- als an die VRP-Literatur rückt, ist nicht das
Fehlen einer Sequenzierung, sondern (a) die Zielgröße - gewichtete Fertigstellungszeit
und Verspätung relativ zu Fristen, nicht Gesamtdistanz - und (b) die Präzedenz
zwischen Legs DESSELBEN Auftrags auf VERSCHIEDENEN Transportern/Zonen (Leg 2 darf erst
starten, wenn Leg 1 in einer anderen Zone fertig ist) - eher mehrstufige
Job-Shop-Struktur als eine einzelne Fahrzeugtour. Deshalb baut Koordiniert auf einer
Scheduling-Regel (ATCS) statt einer klassischen VRP-Heuristik auf, obwohl beide
Sichtweisen dieselbe zugrunde liegende Kombinatorik beschreiben. Transporter werden
einzeln mit Position geführt (nicht nur als Kapazitätszahl) - wer gerade abgeliefert
hat, muss leer zum nächsten Einsatzort fahren (Repositionierung), genau wie ein echtes
Shuttle/AGV.

Vier Dispositionsverfahren im Vergleich: Unoptimiert (FCFS), Dezentral je Zone
(Greedy: lokales SPT je Leg, blind für Repositionierungskosten), Koordiniert (ATCS -
Apparent Tardiness Cost with Setups, eine literaturbekannte Dispatching-Regel aus der
Scheduling-Forschung für genau diese Problemstruktur: parallele Maschinen mit
sequenzabhängigen Rüstzeiten und Fristen) und OR-Tools (CP-SAT mit sequenzabhängigen
Rüstzeiten je Transporter). HAUPTKRITERIUM für alle vier Verfahren ist die
Gesamtdurchlaufzeit (Summe aller Auftrags-Durchlaufzeiten) - Umstiegs-Wartezeit und
Repositionierung sind keine eigenen Ziele, sondern Ursachen, die sich in der
Gesamtdurchlaufzeit niederschlagen; sie tauchen in der App nur noch als Erklärung auf,
WORAUS sich die Gesamtdurchlaufzeit zusammensetzt (siehe
`build_lead_time_composition_figure`), nicht als eigene KPI-Kacheln oder
Vergleichscharts. Koordiniert und OR-Tools blenden zusätzlich einen kleinen
Verspätungs-/Dringlichkeitsterm mit ein (Details unten je Verfahren) -
Gesamtdurchlaufzeit bleibt dominant, Pünktlichkeit ist kein zweites, gleichrangiges
Ziel, sondern ein mitgewichteter Nebenaspekt derselben Zielfunktion. Kernthema: lokal
optimale Disposition je Zone erzeugt an Umschlagpunkten Wartezeit, die sich
kaskadenartig fortpflanzt und die Gesamtdurchlaufzeit verschlechtert - eine
zonenübergreifend koordinierte Disposition vermeidet das systematisch.

Koordiniert hat drei Anläufe gebraucht, dokumentiert in
`warehouse_dispatch_coordinated.py`, weil jede plausibel klingende Formel erst
geschweept werden musste, bevor sie sich als tatsächlich richtig herausstellte: reines
"kürzeste Restroute zuerst" verlor gegen Greedy, sobald Repositionierung Teil des
Modells wurde; eine handgestrickte lineare Kombination aus drei unabhängig
geschweepten Gewichten (SPT, Restroute, Repositionierungsdistanz, später auch
Zeitpuffer) funktionierte danach leidlich, wirkte aber nie wie etwas, das man absichtlich
so gebaut hätte. Seit 2026-09-02 ersetzt durch ATCS - dieselben drei Signale (SPT,
Zeitpuffer, Rüstzeit/Repositionierung), aber als eine publizierte Formel mit
exponentieller Abklingfunktion statt drei linearer Gewichte, geschweept über dieselben
Szenario-Familien: schlägt die alte Version bei der Gesamtverspätung in JEDER
getesteten Szenario-Familie, nicht nur manchen.

Ein Anteil der Aufträge kann als Express markiert werden (engere Frist). Nur Koordiniert
(EXPRESS_WEIGHT als Gewicht im ATCS-Index) und OR-Tools (dasselbe EXPRESS_WEIGHT im
Zielwert PLUS echter Verspätungs-Strafterm) nutzen Frist bzw. Markierung aktiv -
Unoptimiert und Greedy ignorieren beides bewusst, um zu zeigen, dass ein rein
lokales/unkoordiniertes System gesetzte Prioritäten in der Praxis oft schlicht nicht
respektiert. Koordinierts Dringlichkeits-Term wurde bewusst NICHT als reine "Strafe
für bereits eingetretene Verspätung" gebaut (eine erste, zu OR-Tools symmetrische
Fassung erwies sich als wirkungslos - ein Auftrag ist zu dem Zeitpunkt, an dem er
nachweislich zu spät dran ist, in der Warteschlange fast immer schon allein, also gibt
es nichts mehr umzusortieren), sondern als kontinuierliches Signal auf den
verbleibenden Zeitpuffer, das über eine Abklingfunktion (ATCS_K1) schon vor
tatsächlicher Verspätung wirkt.

Selbe Struktur wie bei den anderen Demos in diesem Workspace: Ergebnis zuerst,
vollständiger Methodenvergleich sekundär im Expander, dazu "Wie funktioniert diese
Demo?" und "Mathematische Formulierung" als eigene Expander.

Code-Struktur: Modell, Dispositionsverfahren, Kennzahlen, PDF-Export und
Visualisierung liegen in den Modulen warehouse_*.py neben dieser Datei.
"""

import time

import pandas as pd
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

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
    build_lead_time_composition_figure,
    build_lead_time_figure,
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
        method: evaluate_schedule(schedule, routes, orders, handover) for method, schedule in schedules.items()
    }
    return schedules, evaluations


def _rerun_fragment_or_app():
    """st.rerun(scope="fragment") only works while an actual fragment
    rerun is in progress - calling it while the fragment's body is merely
    being executed as PART OF a full-app rerun raises
    StreamlitInvalidLayoutContextError (this happens right after the
    ortools solve's own st.rerun() below, since that's a full rerun and
    _render_ortools_tab() runs again as part of it, immediately hitting
    the still-active cooldown branch). ctx.fragment_ids_this_run is empty
    exactly in that situation - fall back to a full rerun there instead of
    crashing."""
    ctx = get_script_run_ctx()
    if ctx and ctx.fragment_ids_this_run:
        st.rerun(scope="fragment")
    else:
        st.rerun()


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

lead_reduction = greedy_eval.total_lead_time - coordinated_eval.total_lead_time
lead_reduction_pct = (lead_reduction / greedy_eval.total_lead_time * 100) if greedy_eval.total_lead_time > 0 else 0.0

m1, m2, m3, m4 = st.columns(4)
m1.metric(
    "Gesamtdurchlaufzeit", f"{coordinated_eval.total_lead_time:.0f} min",
    delta=f"{-lead_reduction:.0f} min ggü. dezentral", delta_color="inverse",
)
m2.metric("Ø Durchlaufzeit je Auftrag", f"{coordinated_eval.avg_lead_time:.1f} min")
m3.metric("Pünktlichkeit", f"{coordinated_eval.on_time_rate * 100:.0f}%")
m4.metric("Letzte Auslieferung", f"{coordinated_eval.makespan:.0f} min")

if lead_reduction > 0:
    st.success(
        f"💡 Im Vergleich zur dezentralen Disposition (jede Zone optimiert nur für sich) spart die "
        f"zonenübergreifend koordinierte Disposition rund **{lead_reduction:.0f} Minuten Gesamtdurchlaufzeit** "
        f"({lead_reduction_pct:.0f}% weniger) - Verfahren: {METHOD_LABELS[METHOD_COORDINATED]}. Wie das gelingt, "
        f"zeigt der Abschnitt unten."
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
und wartet am Hub nur noch auf seinen letzten, kurzen Leg zur Zielgasse - beim ersten Umstieg
ist bereits Zeit von seinem Frist-Puffer draufgegangen. Zur selben Zeit wird Auftrag B frisch
freigegeben - sein allererster Leg ist rein zufällig eine Idee kürzer als A's letzter Leg, und
B hat noch seinen vollen Puffer. Greedy sieht in der Hub-Zone nur die beiden Legs vor sich und
ihre Dauer, nicht die Vorgeschichte der Aufträge - also gewinnt B, obwohl A eigentlich fast
fertig ist und ihn diese Verspätung härter trifft. **Koordiniert** dämpft die Priorität eines
Legs mit einer Exponentialfunktion über den verbleibenden Zeitpuffer bis zur Frist (Teil der
ATCS-Regel, Details im Math-Expander) - A's bereits angeknabberter Puffer macht seinen Leg
dringlicher, genug, um den knappen Vorsprung zurückzubekommen, ohne dass Koordiniert deshalb
insgesamt schlechter disponiert als Greedy: SPT bleibt der dominante Faktor, weil es für die
Gesamtdurchlaufzeit einer einzelnen Ressource nachweislich das Beste ist.

**Ein zweites Beispiel zeigt, warum Greedy auch bei der reinen Gesamtdurchlaufzeit
zurückfällt:** Zwei Legs werden gleichzeitig frei, einer davon am anderen Ende der Gasse als
der aktuell freie Shuttle steht, der andere direkt daneben - beide nominell fast gleich lang.
Greedy sieht nur die Fahrzeit des Legs selbst und ist bei einem Unentschieden indifferent; oft
genug schickt es den Shuttle auf die weite Leerfahrt. Diese Leerfahrt (Repositionierung) zählt
für die Auslieferung nicht mit, kostet aber echte Zeit - Greedy "sieht" sie beim Entscheiden gar
nicht. Koordiniert dämpft die Priorität eines Legs mit einer zweiten Exponentialfunktion über
die Distanz zum nächsten freien Transporter und bevorzugt bei ähnlich dringenden Legs
konsequent den näherliegenden - sichtbar an den hellen, schraffierten Balken im Gantt-Chart
unten (Leerfahrten), die bei Koordiniert spürbar kürzer ausfallen als bei Greedy.

**Beide Effekte zahlen auf dieselbe Zielgröße ein:** die Gesamtdurchlaufzeit je
Auftrag. Das folgende Diagramm zeigt sie Auftrag für Auftrag im direkten Vergleich.
"""
)
core_evals = {"baseline": evaluations["baseline"], "greedy": greedy_eval, "coordinated": coordinated_eval}
st.plotly_chart(build_lead_time_figure(core_evals), width='stretch', key="lead_time_core")

st.markdown(
    """
**Woraus setzt sich diese Zeit zusammen?** Reine Fahrzeit ist unvermeidbar (die Strecke muss
gefahren werden), Umstiegszeit ist ein fester Overhead pro Umschlagpunkt - beides ist bei allen
drei Verfahren identisch, weil sie exakt dieselben Routen fahren. Was sich unterscheidet, ist
der Rest: Wartezeit auf einen freien Transporter, an Umschlagpunkten und durch Leerfahrten.
Genau das ist der Hebel, an dem Koordiniert ansetzt.
"""
)
st.plotly_chart(build_lead_time_composition_figure(core_evals, handover), width='stretch', key="composition_core")

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
        @st.fragment
        def _render_ortools_tab():
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
                remaining = cooldown_needed - elapsed
                st.caption(f"Kurze Abkühlpause aktiv - noch {remaining:.0f}s.")
                # A plain st.rerun() only recomputes this on the NEXT user
                # interaction - without it, the countdown sits frozen at
                # whatever it showed right after solving, and the disabled
                # button stays disabled-looking indefinitely. Prefers
                # scope="fragment" (fires up to once a second while the
                # cooldown ticks down, and a full rerun that often would
                # needlessly re-simulate baseline/greedy/coordinated on
                # every tick) but falls back to a full rerun on the one
                # pass right after the solve's own full st.rerun() below,
                # where scope="fragment" would raise (see
                # _rerun_fragment_or_app's docstring).
                time.sleep(min(remaining, 1.0))
                _rerun_fragment_or_app()

            if solve_clicked:
                with st.spinner("OR-Tools löst..."):
                    schedule, status = solve_ortools(network, routes, orders, transporters_per_zone, handover, time_limit, horizon)
                st.session_state["ortools_last_run_at"] = time.time()
                st.session_state["ortools_last_time_limit"] = time_limit
                st.session_state["ortools_schedule"] = schedule
                st.session_state["ortools_status"] = status
                st.session_state["ortools_scenario_key"] = (n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, express, seed, trans_aisle, trans_hub, handover)
                # A fragment-scoped rerun here would only patch THIS
                # fragment's own DOM region - the Vergleich tab (tabs[4],
                # outside the fragment) reads ortools_schedule too, but
                # would keep showing whatever it rendered during the last
                # FULL script run (i.e. without OR-Tools) until some
                # unrelated full rerun happened elsewhere on the page - a
                # real bug found live (OR-Tools missing from the Vergleich
                # comparison right after solving). A full st.rerun() (no
                # scope, even though we're inside a fragment) re-executes
                # the whole script exactly once per solve, which is cheap
                # relative to the solve itself, and is what actually
                # propagates the new schedule to the rest of the page -
                # also happens to fix the cooldown-not-showing-immediately
                # issue this rerun always existed for.
                st.rerun()

            current_key = (n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, express, seed, trans_aisle, trans_hub, handover)
            stale = st.session_state.get("ortools_scenario_key") != current_key
            ortools_schedule = st.session_state.get("ortools_schedule")

            if ortools_schedule is not None and not stale:
                st.caption(f"Status: {status_label(st.session_state['ortools_status'])}")
                ortools_eval = evaluate_schedule(ortools_schedule, routes, orders, handover)
                render_method_panel("ortools", ortools_schedule, ortools_eval, orders_by_id, network, transporters_per_zone)
            elif ortools_schedule is not None and stale:
                st.info("Eingaben haben sich geändert - bitte erneut lösen.")
            else:
                st.info("Noch nicht gelöst.")

        _render_ortools_tab()

    with tabs[4]:
        compare_evals = dict(evaluations)
        ortools_schedule = st.session_state.get("ortools_schedule")
        current_key = (n_aisles, nodes_per_aisle, hub_nodes, n_orders, horizon, cross_zone, express, seed, trans_aisle, trans_hub, handover)
        if ortools_schedule is not None and st.session_state.get("ortools_scenario_key") == current_key:
            compare_evals["ortools"] = evaluate_schedule(ortools_schedule, routes, orders, handover)

        st.plotly_chart(build_kpi_comparison_figure(compare_evals), width='stretch', key="kpi_comparison")
        st.caption(
            "Einzige Kennzahl, auf die hin disponiert wird: die Gesamtdurchlaufzeit. Die Aufschlüsselung "
            "darunter zeigt, woraus sie sich zusammensetzt."
        )
        st.plotly_chart(build_lead_time_composition_figure(compare_evals, handover), width='stretch', key="composition_compare")

        has_express = any(o.is_express for o in orders)
        rows = []
        for method, result in compare_evals.items():
            row = {
                "Verfahren": METHOD_LABELS.get(method, method),
                "Gesamtdurchlaufzeit (min)": round(result.total_lead_time, 1),
                "Ø je Auftrag (min)": round(result.avg_lead_time, 1),
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

**Einordnung, mit Vorsicht formuliert:** PDPT beschreibt das große Bild - warum es
Umschlagpunkte überhaupt gibt. Die Zonenfolge je Auftrag ist beim Hub-and-Spoke-Layout
fix (eigene Gasse, oder Gasse → Hub → Zielgasse) - keine Wahl. Aber WELCHES Leg ein
Transporter als nächstes übernimmt, IST eine echte Sequenzierungsentscheidung mit einer
Distanzmatrix dazwischen (Repositionierungszeit zwischen dem Ausstiegsknoten des einen
und dem Einstiegsknoten des nächsten Legs) - strukturell dieselbe Kombinatorik wie eine
VRP-Tour für ein einzelnes Fahrzeug, kein anderes Problem. Was diese Aufgabe näher an
die Scheduling- als an die VRP-Literatur rückt, ist nicht das Fehlen einer
Sequenzierung, sondern zweierlei: (a) die Zielgröße - gewichtete Fertigstellungszeit
und Verspätung relativ zu Fristen, nicht Gesamtdistanz -, und (b) die Präzedenz
zwischen Legs DESSELBEN Auftrags auf VERSCHIEDENEN Transportern/Zonen (Leg 2 darf erst
starten, wenn Leg 1 in einer anderen Zone fertig ist) - eher mehrstufige
Job-Shop-Struktur als eine einzelne Fahrzeugtour. Deshalb baut Koordiniert unten auf
einer Scheduling-Regel (ATCS) statt einer klassischen Tourenplanungs-Heuristik auf -
beide Sichtweisen beschreiben dieselbe zugrunde liegende Kombinatorik, nur mit
unterschiedlichem Fokus.

**Lagerlayout:** Hub-and-Spoke - mehrere Gassen-Zonen hängen an einer zentralen
Verteiler-Zone (schnellere Förderstrecke/Lift). Jede Gasse hat genau einen Umschlagpunkt zum
Hub. Ein zonenübergreifender Auftrag durchläuft damit bis zu drei **Legs**: Gasse → Hub →
Zielgasse, mit einer festen Umstiegszeit an jedem der beiden Umschlagpunkte.

**Ein Auftrag Schritt für Schritt:** Vom Moment der Freigabe (= abholbereit) bis zur
tatsächlichen Ankunft am Ziel zählt lückenlos jede Minute in die Gesamtdurchlaufzeit -
Fahrzeit, Umstiegszeit, jede Wartezeit auf einen Transporter und jede Repositionierung, ohne
Ausnahme. Auftrag 7 soll von einem Lagerplatz in Gasse 2 zu einer
Position in Gasse 4. *Leg 1:* Gassen-Shuttle fährt in Gasse 2 zum Hub-Anschluss, sagen wir 3
Minuten. *Umstieg 1:* feste Umstiegszeit, z. B. 1 Minute, für die Übergabe an den
Hub-Transporter - plus die Zeit, die Auftrag 7 zusätzlich warten muss, falls gerade kein
Hub-Transporter frei ist. *Leg 2:* Hub-Transporter fährt quer durch den Verteiler zum
Anschluss von Gasse 4, z. B. 4 Minuten. *Umstieg 2:* wieder Umstiegszeit plus eventuelle
Wartezeit, diesmal auf ein freies Gassen-Shuttle in Gasse 4. *Leg 3:* letztes Stück zur
Zielposition, z. B. 2 Minuten. Reine Fahrzeit also 9 Minuten plus 2 Minuten Umstiegszeit =
11 Minuten bestenfalls - jede zusätzliche Minute, die Auftrag 7 an einem der beiden
Umschlagpunkte auf einen freien Transporter wartet, zählt direkt in seine
**Gesamtdurchlaufzeit** hinein, der einzigen Größe, an der alle vier Verfahren gemessen
werden. Die Wartezeit selbst ist keine eigene Kennzahl mehr in dieser Demo, sondern nur
noch ein Bestandteil, den das Aufschlüsselungs-Diagramm oben sichtbar macht.

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

**Express-Aufträge (🚀):** Ein einstellbarer Anteil der Aufträge bekommt eine engere Frist:
`Freigabe + theoretische Mindestlaufzeit + fester Puffer` (Normal: 20 min, Express: 8 min) -
additiv, nicht proportional zur Routenlänge, damit ein langer Auftrag nicht allein wegen
seiner Länge mehr absolute Luft bekommt als ein kurzer, egal ob Normal oder Express. Interessant
ist nicht die Frist selbst, sondern wer sie überhaupt beachtet: Unoptimiert und Dezentral/Greedy
ignorieren die Markierung bewusst - beide bleiben bei ihrer jeweiligen Logik (Ankunftsreihenfolge bzw.
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
- **Koordiniert:** kein Formel-Sammelsurium mehr, sondern eine literaturbekannte
  Dispatching-Regel - **ATCS (Apparent Tardiness Cost with Setups)**, entwickelt für
  genau diese Problemklasse (parallele Maschinen, sequenzabhängige Rüstzeiten,
  Fristen). Der Index kombiniert drei Signale multiplikativ statt additiv: SPT
  (Gewicht/Fahrzeit), eine Exponentialfunktion, die mit schrumpfendem Zeitpuffer
  wächst, und eine zweite Exponentialfunktion, die mit wachsender Repositionierdistanz
  zum nächsten freien Transporter schrumpft. Zwei frühere Fassungen wurden verworfen:
  reines "kürzeste Restroute zuerst" verlor gegen Greedy, sobald Repositionierung Teil
  des Modells wurde; die danach gebaute Linearkombination aus drei unabhängig
  geschweepten Gewichten (Restroute, Repositionierdistanz, Zeitpuffer) funktionierte,
  wirkte aber nie wie ein Verfahren, das man absichtlich genau so entworfen hätte. ATCS
  schlägt diese Linearkombination bei der Gesamtverspätung in **jeder** getesteten
  Szenario-Familie, nicht nur manchen - ein durchgängiger, nicht nur gelegentlicher
  Gewinn. Express-Aufträge bekommen ein höheres Gewicht im SPT-Term (EXPRESS_WEIGHT,
  dieselbe Konstante wie bei OR-Tools unten) statt eines eigenen Faktors.
- **OR-Tools (CP-SAT):** jeder Leg ist ein Intervall fester Dauer. Weil Repositionierung
  davon abhängt, WELCHER Transporter einen Leg übernimmt, sind Transporter hier keine
  anonyme Kapazität mehr wie zuvor ohne Repositionierung: jeder Leg bekommt eine
  Maschinen-Variable (welcher der c_z Transporter der Zone ihn übernimmt), und für jedes
  Legpaar auf demselben Transporter erzwingt eine Präzedenzbedingung die reale
  Repositionierungszeit dazwischen - ein Standardmuster für "parallele Maschinen mit
  sequenzabhängigen Rüstzeiten". Ziel: minimale **gewichtete** Gesamtdurchlaufzeit -
  Express-Aufträge zählen 3-fach im Zielwert (klassische Weighted-Completion-Time-
  Formulierung, dasselbe EXPRESS_WEIGHT wie in Koordiniert's ATCS-Index), nur als
  echtes Optimierungsziel statt als Heuristik-Regel. Zusätzlich fließt eine echte
  Verspätungsstrafe ein: pro Auftrag eine Variable für `max(0, Fertigstellung - Frist)`,
  mit eigenem Gewicht zur gewichteten Gesamtdurchlaufzeit addiert - anders als bei
  Koordiniert funktioniert dieses gegatete "nur bei tatsächlicher Verspätung"-Muster
  hier, weil OR-Tools global über den gesamten Plan optimiert statt Leg für Leg lokal zu
  entscheiden. Button-gesteuert mit Zeitlimit und Cooldown, da rechenintensiver als die
  eigenen Heuristiken.

**Kern-Kennzahl:** Die **Gesamtdurchlaufzeit** (Summe bzw. Durchschnitt über
alle Auftrags-Durchlaufzeiten) - das Hauptkriterium, nach dem alle vier Verfahren
disponieren und verglichen werden. Umstiegs-Wartezeit und Repositionierung sind keine
eigenen Ziele, sondern Ursachen, die sich in dieser einen Zahl niederschlagen; die
Aufschlüsselungs-Diagramme oben und im Vergleichstab zeigen nur, WORAUS sie sich
zusammensetzt. Koordiniert und OR-Tools blenden zusätzlich einen kleinen
Verspätungs-/Dringlichkeitsterm in dieselbe Zielfunktion ein (Details oben je
Verfahren) - Pünktlichkeit ist damit kein zweites, gleichrangiges Ziel, sondern ein
mitgewichteter Nebenaspekt, der bei Bedarf leicht in Gesamtdurchlaufzeit "eintauscht".
Zusätzlich verfolgt, wenn Express-Aufträge aktiv sind: deren **Pünktlichkeit** separat
von der Gesamtpünktlichkeit.

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
der die gewichtete Summe aller Durchlaufzeiten PLUS eine kleine Verspätungsstrafe minimiert -
unter drei Arten von Nebenbedingungen: (1) ein Auftrag darf seinen nächsten Leg erst
antreten, wenn der vorige fertig ist UND die Umstiegszeit verstrichen ist, (2) eine Zone kann
zu keinem Zeitpunkt mehr Legs gleichzeitig bedienen, als sie Transporter hat, und (3) folgen
zwei Legs auf demselben Transporter aufeinander, muss dazwischen genug Zeit für die reale
Repositionierungsfahrt liegen. Formal:

Gegeben ein Auftrag $o$ mit einer Folge von Legs $\ell \in \{1, \ldots, L_o\}$ (Zone,
Ein-/Ausstiegsknoten, feste Fahrzeit $d_{o,\ell}$), eine Release-Zeit $r_o$, eine feste
Umstiegszeit $h$, je Zone $z$ eine Transporteranzahl $c_z$, ein Gewicht $w_o$ (3 für
Express-Aufträge, sonst 1), eine Frist $\delta_o$ (`due_time_for_order()`) und ein kleines
Verspätungsgewicht $\lambda$. Gesucht sind Startzeiten $s_{o,\ell} \geq 0$ für jeden Leg, die
den gesamten Auftragsbestand bedienen und die **gewichtete** Gesamtdurchlaufzeit PLUS
Verspätungsstrafe minimieren:
"""
    )
    st.latex(
        r"\min \; \sum_{o} w_o \Big( s_{o,L_o} + d_{o,L_o} - r_o \Big)"
        r" \;+\; \lambda \sum_{o} \max\big(0,\; s_{o,L_o} + d_{o,L_o} - \delta_o\big)"
    )
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
        r"I(o,\ell) = \frac{w_o}{d_{o,\ell}} \cdot "
        r"\exp\!\left(-\frac{\max(\sigma_{o,\ell},\,0)}{K_1 \, \bar d}\right) \cdot "
        r"\exp\!\left(-\frac{\min_{\text{frei } t} \rho(t, e_{o,\ell})}{K_2 \, \bar d}\right),"
        r" \qquad w_o = 3 \text{ falls } o \text{ Express, sonst } 1"
    )
    st.markdown(
        r"""
Bedient wird die Warteschlange nach dem HÖCHSTEN $I(o,\ell)$ (umgekehrte Konvention zu den
anderen Prioritätswerten hier - im Code als $-I$ zurückgegeben, damit "niedriger zuerst"
weiter für alle drei Verfahren gilt). Das ist die **Apparent-Tardiness-Cost-with-Setups
(ATCS)**-Regel aus der Scheduling-Literatur, keine selbst erfundene Formel: $w_o/d_{o,\ell}$
ist gewichtetes SPT (dieselbe Logik wie Greedy, nur mit Express-Gewicht), die erste
Exponentialfunktion dämpft mit wachsendem Zeitpuffer $\sigma_{o,\ell}$, die zweite mit
wachsender Repositionierdistanz zum nächsten freien Transporter $t$. $\bar d$ ist die
durchschnittliche Leg-Fahrzeit über das gesamte Szenario (einmal berechnet, nicht pro
Entscheidung) - derselbe Skalierungsfaktor für beide Exponentialfunktionen, weil
Repositionierdistanzen und Leg-Fahrzeiten dieselbe Art Größe sind (beides
Knoten-zu-Knoten-Fahrzeiten innerhalb einer Zone). $K_1, K_2$ sind Abkling-Parameter,
empirisch geschweept (aktuell $K_1{=}1{,}0$, $K_2{=}0{,}15$) - kleines $K_2$ heißt, die
Rüstzeit-Dämpfung greift schon bei kurzen Distanzen hart durch; ein zu großes $K_2$ verlor
im Sweep gegen Greedy in bis zu 33 von 40 Szenarien.

$\sigma_{o,\ell} = \delta_o - (t + d_{o,\ell} + \sum_{k>\ell}(d_{o,k}+h))$ ist der
Zeitpuffer bis zur Frist $\delta_o$ ab dem aktuellen Entscheidungszeitpunkt $t$ (nicht ab
$r_{o,\ell}$, da mehrere zeitgleich wartende Legs denselben Referenzzeitpunkt brauchen, um
fair vergleichbar zu sein). FCFS: Priorität konstant 0; Greedy: kürzeste Fahrzeit des
aktuellen Legs, kein Express-, Zeitpuffer- oder Repositionierungs-Term.

Zwei frühere Fassungen wurden verworfen, bevor diese stand: reines "kürzeste Restroute
zuerst" verlor gegen Greedy, sobald Repositionierung Teil des Modells wurde; die danach
gebaute Linearkombination aus drei unabhängig geschweepten additiven Gewichten
funktionierte, aber nicht durchgängig - bei der Gesamtverspätung schlägt die jetzige
ATCS-Fassung sie in JEDER getesteten Szenario-Familie, nicht nur einigen.
"""
    )

st.markdown("---")
st.caption(
    "Diese Demo ist Teil des Portfolios von [Sebastian Hanisch](https://sebastianhanisch.net) – "
    "Operations Research und Machine Learning. Interesse an einer maßgeschneiderten Lösung für "
    "Ihr Unternehmen? [Kontakt aufnehmen](https://sebastianhanisch.net/kontakt.html)"
)
