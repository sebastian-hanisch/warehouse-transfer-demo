# Lagerlogistik: Transport ueber mehrere Zonen mit Umschlagpunkten

**[→ Demo live ausprobieren](https://sebastianhanisch-warehouse-transfer-demo.streamlit.app/)**

Interaktive Demo zu einem automatisierten Hochregallager: Ware bewegt sich durch mehrere
**Zonen** (Regalgassen-Shuttles + ein zentraler Verteiler/Lift). Jeder Transporter bleibt in
seiner eigenen Zone - Auftraege, die zonenuebergreifend muessen, "steigen" an einem
**Umschlagpunkt** auf den naechsten Transporter um.

## Worum geht's?

Fachlich ein **Pickup-and-Delivery-Problem mit Transshipment (PDPT)** - ein etabliertes
VRP-Sonderproblem, bei dem Ladung an definierten Umschlagpunkten das Fahrzeug wechseln darf.
Der Fokus der Demo: **lokal optimale Disposition je Zone erzeugt an Umschlagpunkten
Wartezeit, die sich kaskadenartig fortpflanzt** - und eine zonenuebergreifend koordinierte
Disposition vermeidet das systematisch.

Vier Dispositionsverfahren im direkten Vergleich, alle auf demselben Lagergraphen und mit
derselben Kennzahlen-Berechnung ausgewertet:

- **Unoptimiert (FCFS):** keine Prioritaetslogik, wer zuerst bereit ist, wird zuerst bedient.
- **Dezentral je Zone (Greedy):** jede Zone dispatcht lokal nach kuerzester Fahrzeit
  (Shortest Processing Time, SPT) - ein textbuchmaessig lokal-optimales Verfahren, das aber
  blind dafuer ist, ob ein Auftrag noch einen Umstieg vor sich hat.
- **Koordiniert (eigene Heuristik):** Auftraege, die schon einmal umgestiegen sind, haben
  Vorrang vor frischen Auftraegen; als Tie-Break gewinnt die Order mit dem meisten
  verbleibenden Arbeitsaufwand (klassische Most-Work-Remaining-Regel aus der
  Job-Shop-Literatur).
- **OR-Tools (CP-SAT):** jeder Leg ist ein Intervall fester Dauer, `AddCumulative` je Zone
  begrenzt die gleichzeitig aktiven Legs auf die Anzahl Transporter, eine
  Praezedenzbedingung erzwingt die Umstiegssynchronisation. Ziel: minimale
  Gesamtdurchlaufzeit. Button-gesteuert mit Zeitlimit und Cooldown (analog zu den
  Schwesterdemos).

## Methodik

- Lagergraph als **Hub-and-Spoke**: mehrere Gassen-Zonen haengen an einer zentralen
  Verteiler-Zone; die Anzahl Zonen, Knoten je Zone, Transporter je Zone und deren
  Geschwindigkeit sind konfigurierbar.
- Auftraege bekommen Ursprung/Ziel und eine Release-Zeit; ein Grossteil ist bewusst
  zonenuebergreifend, damit Umstiege im Standardfall tatsaechlich auftreten.
- Kern-Kennzahl fuer den Vergleich ist nicht nur die Gesamtdurchlaufzeit, sondern
  ausdruecklich die **kumulierte Umstiegs-Wartezeit** - genau die Groesse, die bei rein
  lokaler Disposition unbemerkt waechst, waehrend die Gesamtdurchlaufzeit oft aehnlich
  aussieht.
- Ein Beispielszenario ("Stosszeit mit Engpass am Umschlagpunkt") ist bewusst so
  eingestellt (nicht zufaellig getroffen), dass die Luecke zwischen dezentral und
  koordiniert deutlich sichtbar wird - dabei zeigt sich ehrlich auch der Trade-off: die
  koordinierte Heuristik senkt die Umstiegs-Wartezeit in diesem Szenario um rund 70 %,
  auf Kosten einer etwas niedrigeren Puenktlichkeit fuer ein paar Grenzfaelle.
- Animierte Paket-Bewegung, Gantt-Chart je Transporter, PDF-Export, Permalink.

## Dateistruktur

| Datei | Inhalt |
|---|---|
| `app.py` | Streamlit-Hauptablauf (Sidebar, Primaeransicht, Tabs) |
| `warehouse_constants.py` | Default-/Grenzwerte |
| `warehouse_network.py` | Hub-and-Spoke-Lagergraph (networkx) |
| `warehouse_demand.py` | Auftragsgenerierung |
| `warehouse_routing.py` | Zonen-Pfad je Auftrag (Legs) |
| `warehouse_dispatch_core.py` | Gemeinsamer Discrete-Event-Simulator fuer die drei eigenen Verfahren |
| `warehouse_dispatch_baseline.py` / `_greedy.py` / `_coordinated.py` | Die drei Prioritaetsregeln (FCFS / SPT / Continuation+MWKR) |
| `warehouse_ortools_solver.py` | CP-SAT-Modell |
| `warehouse_evaluation.py` | Gemeinsame KPI-Berechnung |
| `warehouse_visualization.py` | Lagerschema, Gantt-Chart, Animation, KPI-Vergleich |
| `warehouse_pdf_export.py` | PDF-Transportplan |
| `warehouse_presets.py` | Beispielszenarien, Permalink-Logik (`SettingSpec`-Pattern) |
| `warehouse_ui_panel.py` | Wiederverwendbares Panel je Verfahren |
| `tests/` | Netzwerk-/Routing-Korrektheit, Kein-Doppel-Buchung, Umstiegs-Praezedenz, KPI-Berechnung an Hand-Beispiel, Permalink-Clamping |

## Lokal ausfuehren

```bash
pip install -r requirements-dev.txt
streamlit run app.py
```

Tests: `pytest tests/ -v`

---

Teil des [Operations-Research-Demo-Portfolios](https://sebastianhanisch.net/demos.html) von
[Sebastian Hanisch](https://sebastianhanisch.net) - Operations Research und Machine Learning.
Interesse an einer massgeschneiderten Loesung? [Kontakt aufnehmen](https://sebastianhanisch.net/kontakt.html).
