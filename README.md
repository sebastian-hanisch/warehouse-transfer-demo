# Lagerlogistik: Transport über mehrere Zonen mit Umschlagpunkten

**[→ Demo live ausprobieren](https://sebastianhanisch-warehouse-transfer-demo.streamlit.app/)**

Interaktive Demo zu einem automatisierten Hochregallager: Ware bewegt sich durch mehrere
**Zonen** (Regalgassen-Shuttles + ein zentraler Verteiler/Lift). Jeder Transporter bleibt in
seiner eigenen Zone – Aufträge, die zonenübergreifend müssen, "steigen" an einem
**Umschlagpunkt** auf den nächsten Transporter um.

## Worum geht's?

Fachlich ein **Pickup-and-Delivery-Problem mit Transshipment (PDPT)** – ein etabliertes
VRP-Sonderproblem, bei dem Ladung an definierten Umschlagpunkten das Fahrzeug wechseln darf.
Der Fokus der Demo: **lokal optimale Disposition je Zone erzeugt an Umschlagpunkten
Wartezeit, die sich kaskadenartig fortpflanzt** – und eine zonenübergreifend koordinierte
Disposition vermeidet das systematisch.

Vier Dispositionsverfahren im direkten Vergleich, alle auf demselben Lagergraphen und mit
derselben Kennzahlen-Berechnung ausgewertet:

- **Unoptimiert (FCFS):** keine Prioritätslogik, wer zuerst bereit ist, wird zuerst bedient.
- **Dezentral je Zone (Greedy):** jede Zone dispatcht lokal nach kürzester Fahrzeit
  (Shortest Processing Time, SPT) – ein textbuchmäßig lokal-optimales Verfahren, das aber
  blind dafür ist, ob ein Auftrag noch einen Umstieg vor sich hat.
- **Koordiniert (eigene Heuristik):** übernimmt SPT als dominantes Kriterium wie Greedy,
  gewichtet die Priorität aber zusätzlich leicht (10 %) mit der restlichen Reise eines
  Auftrags über alle Zonen hinweg. Eine erste Fassung sortierte *nur* nach kürzester
  Restroute (SPT komplett verworfen, Shortest-Remaining-Work-First) – verlor im Test über
  hunderte Zufallsszenarien aber öfter als sie gegen Greedy bei der Gesamtdurchlaufzeit
  gewann: SPTs Optimalität für eine einzelne Ressource ist real, sie ganz aufzugeben
  kostet lokal mehr, als die globale Sicht einbringt. Die leicht gewichtete Fassung
  schlägt Greedy zuverlässig bei beiden Kennzahlen.
- **OR-Tools (CP-SAT):** jeder Leg ist ein Intervall fester Dauer, `AddCumulative` je Zone
  begrenzt die gleichzeitig aktiven Legs auf die Anzahl Transporter, eine
  Präzedenzbedingung erzwingt die Umstiegssynchronisation. Ziel: minimale
  Gesamtdurchlaufzeit. Button-gesteuert mit Zeitlimit und Cooldown (analog zu den
  Schwesterdemos).

## Methodik

- Lagergraph als **Hub-and-Spoke**: mehrere Gassen-Zonen hängen an einer zentralen
  Verteiler-Zone; die Anzahl Zonen, Knoten je Zone, Transporter je Zone und deren
  Geschwindigkeit sind konfigurierbar.
- Aufträge bekommen Ursprung/Ziel und eine Release-Zeit; ein Großteil ist bewusst
  zonenübergreifend, damit Umstiege im Standardfall tatsächlich auftreten.
- Kern-Kennzahl für den Vergleich ist nicht nur die Gesamtdurchlaufzeit, sondern
  ausdrücklich die **kumulierte Umstiegs-Wartezeit** – genau die Größe, die bei rein
  lokaler Disposition unbemerkt wächst, während die Gesamtdurchlaufzeit oft ähnlich
  aussieht.
- Ein Beispielszenario ("Stoßzeit mit Engpass am Umschlagpunkt") ist bewusst so
  eingestellt (nicht zufällig getroffen), dass die Lücke zwischen dezentral und
  koordiniert deutlich sichtbar wird: die koordinierte Heuristik senkt die
  Umstiegs-Wartezeit in diesem Szenario um rund 46 % gegenüber Greedy, bei gleichzeitig
  niedrigerer Gesamtdurchlaufzeit als sowohl die unoptimierte Basis als auch Greedy selbst,
  und ohne Pünktlichkeits-Einbußen – Minimierung der Umstiegs-Wartezeit und der
  Gesamtdurchlaufzeit ziehen hier in dieselbe Richtung, nicht gegeneinander. Im
  Standardszenario landet die koordinierte Heuristik sogar exakt auf dem OR-Tools-Optimum.
- Animierte Paket-Bewegung, Gantt-Chart je Transporter, PDF-Export, Permalink.

## Dateistruktur

| Datei | Inhalt |
|---|---|
| `app.py` | Streamlit-Hauptablauf (Sidebar, Primäransicht, Tabs) |
| `warehouse_constants.py` | Default-/Grenzwerte |
| `warehouse_network.py` | Hub-and-Spoke-Lagergraph (networkx) |
| `warehouse_demand.py` | Auftragsgenerierung |
| `warehouse_routing.py` | Zonen-Pfad je Auftrag (Legs) |
| `warehouse_dispatch_core.py` | Gemeinsamer Discrete-Event-Simulator für die drei eigenen Verfahren |
| `warehouse_dispatch_baseline.py` / `_greedy.py` / `_coordinated.py` | Die drei Prioritätsregeln (FCFS / lokales SPT / SPT + leicht gewichtete Restroute) |
| `warehouse_ortools_solver.py` | CP-SAT-Modell |
| `warehouse_evaluation.py` | Gemeinsame KPI-Berechnung |
| `warehouse_visualization.py` | Lagerschema, Gantt-Chart, Animation, KPI-Vergleich |
| `warehouse_pdf_export.py` | PDF-Transportplan |
| `warehouse_presets.py` | Beispielszenarien, Permalink-Logik (`SettingSpec`-Pattern) |
| `warehouse_ui_panel.py` | Wiederverwendbares Panel je Verfahren |
| `tests/` | Netzwerk-/Routing-Korrektheit, Kein-Doppel-Buchung, Umstiegs-Präzedenz, KPI-Berechnung an Hand-Beispiel, Permalink-Clamping |

## Lokal ausführen

```bash
pip install -r requirements-dev.txt
streamlit run app.py
```

Tests: `pytest tests/ -v`

---

Teil des [Operations-Research-Demo-Portfolios](https://sebastianhanisch.net/demos.html) von
[Sebastian Hanisch](https://sebastianhanisch.net) – Operations Research und Machine Learning.
Interesse an einer maßgeschneiderten Lösung? [Kontakt aufnehmen](https://sebastianhanisch.net/kontakt.html).
