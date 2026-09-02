# Lagerlogistik: Transport über mehrere Zonen mit Umschlagpunkten

**[→ Demo live ausprobieren](https://sebastianhanisch-warehouse-transfer-demo.streamlit.app/)**

Interaktive Demo zu einem automatisierten Hochregallager: Ware bewegt sich durch mehrere
**Zonen** (Regalgassen-Shuttles + ein zentraler Verteiler/Lift). Jeder Transporter bleibt in
seiner eigenen Zone – Aufträge, die zonenübergreifend müssen, "steigen" an einem
**Umschlagpunkt** auf den nächsten Transporter um. Transporter sind einzeln mit realer
Position modelliert, nicht nur als Kapazitätszahl: wer abgeliefert hat, muss leer zum
nächsten Einsatzort fahren (**Repositionierung**), bevor er wieder Ladung aufnehmen kann.

## Worum geht's?

Fachlich ein **Pickup-and-Delivery-Problem mit Transshipment (PDPT)** – ein etabliertes
VRP-Sonderproblem, bei dem Ladung an definierten Umschlagpunkten das Fahrzeug wechseln darf.
Der Fokus der Demo: **lokal optimale Disposition je Zone erzeugt an Umschlagpunkten
Wartezeit und schickt Transporter unnötig durchs Lager – beides pflanzt sich
kaskadenartig fort** – und eine zonenübergreifend koordinierte Disposition vermeidet
das systematisch. Einziges Optimierungs- und Vergleichskriterium für alle vier Verfahren
ist dabei die **Gesamtdurchlaufzeit**: Umstiegs-Wartezeit und Repositionierung sind keine
eigenen Ziele, sondern Ursachen, die sich in dieser einen Zahl niederschlagen und in der
App nur noch als Aufschlüsselung erklärt werden, woraus sie sich zusammensetzt.

Vier Dispositionsverfahren im direkten Vergleich, alle auf demselben Lagergraphen und mit
derselben Kennzahlen-Berechnung ausgewertet:

- **Unoptimiert (FCFS):** keine Prioritätslogik, wer zuerst bereit ist, wird zuerst bedient.
- **Dezentral je Zone (Greedy):** jede Zone dispatcht lokal nach kürzester Fahrzeit
  (Shortest Processing Time, SPT) – ein textbuchmäßig lokal-optimales Verfahren, das aber
  blind dafür ist, ob ein Auftrag noch einen Umstieg vor sich hat, UND blind dafür, wo die
  eigenen Transporter gerade stehen.
- **Koordiniert (eigene Heuristik):** übernimmt SPT als dominantes Kriterium wie Greedy,
  gewichtet die Priorität aber zusätzlich leicht mit (a) der restlichen Reise eines
  Auftrags über alle Zonen hinweg (10 %) und (b) der Entfernung zum nächsten freien
  Transporter (150 %). Eine Fassung ohne (b) verlor im Test über hunderte
  Zufallsszenarien öfter gegen Greedy bei der Gesamtdurchlaufzeit als sie gewann, sobald
  Transporter überhaupt repositionieren mussten – Greedys lokale SPT-Stärke reichte trotz
  ihrer Kurzsichtigkeit oft aus, Positionierung ganz zu ignorieren kostete mehr, als die
  Restroute-Sicht einbrachte. Erst das Positions-Gewicht macht Koordiniert wieder
  zuverlässig besser als Greedy, bei beiden Kennzahlen, über mehrere Szenario-Familien
  geprüft.
- **OR-Tools (CP-SAT):** jeder Leg ist ein Intervall fester Dauer. Da die
  Repositionierungszeit davon abhängt, WELCHER Transporter einen Leg übernimmt, bekommt
  jeder Leg eine Maschinen-Variable (welcher der $c_z$ Transporter der Zone), und für
  jedes Legpaar auf demselben Transporter erzwingt eine reifizierte Nebenbedingung die
  reale Repositionierungszeit dazwischen – ein Standardmuster für "parallele Maschinen mit
  sequenzabhängigen Rüstzeiten", deutlich aufwändiger als die `AddCumulative`-Formulierung
  vor Einführung der Repositionierung, aber weiterhin gut lösbar (< 1 s selbst am oberen
  Rand der Schieberegler-Bereiche). Ziel: minimale Gesamtdurchlaufzeit. Button-gesteuert
  mit Zeitlimit und Cooldown (analog zu den Schwesterdemos).

Zusätzlich kann ein Anteil der Aufträge als **Express** markiert werden (engere Frist).
Nur Koordiniert (Prioritäts-Faktor 0,5) und OR-Tools (Gewicht 3× im Zielwert, klassische
Weighted-Completion-Time-Formulierung) nutzen die Markierung aktiv – Unoptimiert und
Greedy ignorieren sie bewusst, um zu zeigen, dass ein rein lokales/unkoordiniertes System
gesetzte Prioritäten in der Praxis oft schlicht nicht respektiert.

## Methodik

- Lagergraph als **Hub-and-Spoke**: mehrere Gassen-Zonen hängen an einer zentralen
  Verteiler-Zone; die Anzahl Zonen, Knoten je Zone, Transporter je Zone und deren
  Geschwindigkeit sind konfigurierbar.
- Aufträge bekommen Ursprung/Ziel und eine Release-Zeit; ein Großteil ist bewusst
  zonenübergreifend, damit Umstiege im Standardfall tatsächlich auftreten.
- **Repositionierung:** jeder Transporter wird einzeln mit Position und Verfügbarkeit
  geführt (nicht nur als Kapazitätszahl je Zone), startet an seinem Zonen-Eingang und muss
  zwischen zwei Aufträgen leer zum nächsten Einstiegsknoten fahren – reale Netzwerk-Distanz,
  keine Pauschale. Im Gantt-Chart als helle, schraffierte Balken vor dem eigentlichen Leg
  sichtbar.
- Kern-Kennzahl für den Vergleich ist ausschließlich die **Gesamtdurchlaufzeit** – das
  einzige Kriterium, nach dem alle vier Verfahren disponieren und verglichen werden.
  Umstiegs-Wartezeit und Repositionierung tauchen nur noch in einer Aufschlüsselung
  (gestapeltes Balkendiagramm: reine Fahrzeit / feste Umstiegszeit / Warten) als Erklärung
  auf, woraus sich diese eine Zahl zusammensetzt – nicht mehr als eigene KPI-Kachel oder
  eigenes Vergleichschart. Bei aktiven Express-Aufträgen wird zusätzlich deren
  **Pünktlichkeit** separat von der Gesamtpünktlichkeit verfolgt.
- Ein Beispielszenario ("Stoßzeit mit Engpass am Umschlagpunkt") ist bewusst so
  eingestellt (nicht zufällig getroffen), dass die Lücke zwischen dezentral und
  koordiniert deutlich sichtbar wird.
- Animierte Paket-Bewegung, Gantt-Chart je Transporter (inkl. Repositionierungsfahrten),
  PDF-Export, Permalink.

## Dateistruktur

| Datei | Inhalt |
|---|---|
| `app.py` | Streamlit-Hauptablauf (Sidebar, Primäransicht, Tabs) |
| `warehouse_constants.py` | Default-/Grenzwerte |
| `warehouse_network.py` | Hub-and-Spoke-Lagergraph (networkx) |
| `warehouse_demand.py` | Auftragsgenerierung |
| `warehouse_routing.py` | Zonen-Pfad je Auftrag (Legs) |
| `warehouse_dispatch_core.py` | Gemeinsamer Discrete-Event-Simulator für die drei eigenen Verfahren, inkl. Transporter-Positionstracking und Repositionierung |
| `warehouse_dispatch_baseline.py` / `_greedy.py` / `_coordinated.py` | Die drei Prioritätsregeln (FCFS / lokales SPT / SPT + Restroute- und Positions-Gewicht) |
| `warehouse_ortools_solver.py` | CP-SAT-Modell (Maschinen-Zuordnung + sequenzabhängige Repositionierungszeiten) |
| `warehouse_evaluation.py` | Gemeinsame KPI-Berechnung |
| `warehouse_visualization.py` | Lagerschema, Gantt-Chart, Animation, KPI-Vergleich |
| `warehouse_pdf_export.py` | PDF-Transportplan |
| `warehouse_presets.py` | Beispielszenarien, Permalink-Logik (`SettingSpec`-Pattern) |
| `warehouse_ui_panel.py` | Wiederverwendbares Panel je Verfahren |
| `tests/` | Netzwerk-/Routing-Korrektheit, Kein-Doppel-Buchung, Umstiegs-Präzedenz, Repositionierung entspricht realer Netzwerk-Distanz, KPI-Berechnung an Hand-Beispiel, Permalink-Clamping |

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
