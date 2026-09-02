# Lagerlogistik: Transport über mehrere Zonen mit Umschlagpunkten

**[→ Demo live ausprobieren](https://sebastianhanisch-warehouse-transfer-demo.streamlit.app/)**

Interaktive Demo zu einem automatisierten Hochregallager: Ware bewegt sich durch mehrere
**Zonen** (Regalgassen-Shuttles + ein zentraler Verteiler/Lift). Jeder Transporter bleibt in
seiner eigenen Zone – Aufträge, die zonenübergreifend müssen, "steigen" an einem
**Umschlagpunkt** auf den nächsten Transporter um. Transporter sind einzeln mit realer
Position modelliert, nicht nur als Kapazitätszahl: wer abgeliefert hat, muss leer zum
nächsten Einsatzort fahren (**Repositionierung**), bevor er wieder Ladung aufnehmen kann.

## Worum geht's?

Fachlich das Gesamtbild eines **Pickup-and-Delivery-Problems mit Transshipment (PDPT)** –
ein etabliertes VRP-Sonderproblem, bei dem Ladung an definierten Umschlagpunkten das
Fahrzeug wechseln darf. Die Zonenfolge je Auftrag ist beim Hub-and-Spoke-Layout fix
(eigene Gasse, oder Gasse → Hub → Zielgasse) – aber WELCHES Leg ein Transporter als
nächstes übernimmt, ist eine echte Sequenzierungsentscheidung mit einer Distanzmatrix
dazwischen (Repositionierungszeit zwischen Ausstiegs- und nächstem Einstiegsknoten) –
strukturell dieselbe Kombinatorik wie eine VRP-Tour für ein einzelnes Fahrzeug, kein
anderes Problem. Was diese Aufgabe näher an die Scheduling- als an die VRP-Literatur
rückt, ist nicht das Fehlen einer Sequenzierung, sondern (a) die Zielgröße – gewichtete
Fertigstellungszeit und Verspätung relativ zu Fristen, nicht Gesamtdistanz –, und (b) die
Präzedenz zwischen Legs desselben Auftrags auf verschiedenen Transportern/Zonen – eher
mehrstufige Job-Shop-Struktur als eine einzelne Fahrzeugtour. Deshalb baut Koordiniert auf
einer Scheduling-Regel (ATCS) statt einer klassischen Tourenplanungs-Heuristik auf, obwohl
beide Sichtweisen dieselbe zugrunde liegende Kombinatorik beschreiben.

Der Fokus der Demo: **lokal optimale Disposition je Zone erzeugt an Umschlagpunkten
Wartezeit und schickt Transporter unnötig durchs Lager – beides pflanzt sich
kaskadenartig fort** – und eine zonenübergreifend koordinierte Disposition vermeidet
das systematisch. Hauptkriterium für alle vier Verfahren ist dabei die
**Gesamtdurchlaufzeit**: Umstiegs-Wartezeit und Repositionierung sind keine eigenen
Ziele, sondern Ursachen, die sich in dieser einen Zahl niederschlagen und in der App
nur noch als Aufschlüsselung erklärt werden, woraus sie sich zusammensetzt. Koordiniert
und OR-Tools blenden zusätzlich einen kleinen Verspätungs-/Dringlichkeitsterm mit ein
(siehe unten) – Pünktlichkeit bleibt dabei ein mitgewichteter Nebenaspekt derselben
Zielfunktion, kein zweites, gleichrangiges Ziel.

Vier Dispositionsverfahren im direkten Vergleich, alle auf demselben Lagergraphen und mit
derselben Kennzahlen-Berechnung ausgewertet:

- **Unoptimiert (FCFS):** keine Prioritätslogik, wer zuerst bereit ist, wird zuerst bedient.
- **Dezentral je Zone (Greedy):** jede Zone dispatcht lokal nach kürzester Fahrzeit
  (Shortest Processing Time, SPT) – ein textbuchmäßig lokal-optimales Verfahren, das aber
  blind dafür ist, ob ein Auftrag noch einen Umstieg vor sich hat, UND blind dafür, wo die
  eigenen Transporter gerade stehen.
- **Koordiniert (ATCS):** keine handgestrickte Formel, sondern **Apparent Tardiness Cost
  with Setups** – eine literaturbekannte Dispatching-Regel (Vepsalainen & Morton 1987,
  Setup-Erweiterung u. a. Lee/Bhaskaran/Pinedo 1997) für genau diese Problemklasse:
  parallele Maschinen mit sequenzabhängigen Rüstzeiten und Fristen. Der Index
  `I = (w/p) · exp(-Zeitpuffer / (K₁·p̄)) · exp(-Repositionierdistanz / (K₂·p̄))`
  kombiniert gewichtetes SPT mit zwei Exponentialfunktionen (Dringlichkeit,
  Rüstzeit/Repositionierung) statt drei unabhängig geschweepten additiven Gewichten.
  Zwei frühere Fassungen wurden verworfen: reines "kürzeste Restroute zuerst" verlor
  gegen Greedy, sobald Repositionierung Teil des Modells wurde; die danach gebaute
  Linearkombination (SPT + Restroute-Gewicht + Repositionierungs-Gewicht + später
  Zeitpuffer-Gewicht, alle unabhängig geschweept) funktionierte, aber nicht durchgängig.
  ATCS schlägt diese Linearkombination bei der Gesamtverspätung in **jeder** getesteten
  Szenario-Familie, nicht nur einigen – $K_1{=}1{,}0$, $K_2{=}0{,}15$, ebenfalls geschweept
  (schwache Rüstzeit-Dämpfung, also großes $K_2$, verlor gegen Greedy in bis zu 33 von 40
  Szenarien).
- **OR-Tools (CP-SAT):** jeder Leg ist ein Intervall fester Dauer. Da die
  Repositionierungszeit davon abhängt, WELCHER Transporter einen Leg übernimmt, bekommt
  jeder Leg eine Maschinen-Variable (welcher der $c_z$ Transporter der Zone), und für
  jedes Legpaar auf demselben Transporter erzwingt eine reifizierte Nebenbedingung die
  reale Repositionierungszeit dazwischen – ein Standardmuster für "parallele Maschinen mit
  sequenzabhängigen Rüstzeiten", deutlich aufwändiger als die `AddCumulative`-Formulierung
  vor Einführung der Repositionierung, aber weiterhin gut lösbar (< 1 s selbst am oberen
  Rand der Schieberegler-Bereiche). Ziel: minimale gewichtete Gesamtdurchlaufzeit PLUS
  eine echte Verspätungsstrafe (`max(0, Fertigstellung - Frist)` je Auftrag) – anders als
  bei Koordiniert funktioniert das gegatete Muster hier, weil OR-Tools global über den
  gesamten Plan optimiert statt Leg für Leg lokal zu entscheiden. Button-gesteuert mit
  Zeitlimit und Cooldown (analog zu den Schwesterdemos).

Zusätzlich kann ein Anteil der Aufträge als **Express** markiert werden (engere Frist).
Nur Koordiniert (EXPRESS_WEIGHT als Gewicht $w$ im ATCS-Index) und OR-Tools (dasselbe
EXPRESS_WEIGHT im Zielwert, klassische Weighted-Completion-Time-Formulierung, plus die
Verspätungsstrafe) nutzen Frist bzw. Markierung aktiv – dieselbe Konstante für beide,
nicht mehr zwei unabhängig gewählte Zahlen für dieselbe Idee. Unoptimiert und Greedy
ignorieren beides bewusst, um zu zeigen, dass ein rein lokales/unkoordiniertes System
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
- Kern-Kennzahl für den Vergleich ist die **Gesamtdurchlaufzeit** – das Hauptkriterium,
  nach dem alle vier Verfahren disponieren und verglichen werden. Umstiegs-Wartezeit und
  Repositionierung tauchen nur noch in einer Aufschlüsselung (gestapeltes Balkendiagramm:
  reine Fahrzeit / feste Umstiegszeit / Warten) als Erklärung auf, woraus sich diese eine
  Zahl zusammensetzt – nicht mehr als eigene KPI-Kachel oder eigenes Vergleichschart.
  Koordiniert und OR-Tools blenden zusätzlich einen kleinen Verspätungs-/
  Dringlichkeitsterm in dieselbe Zielfunktion ein (s. o.). Bei aktiven Express-Aufträgen
  wird zusätzlich deren **Pünktlichkeit** separat von der Gesamtpünktlichkeit verfolgt.
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
| `warehouse_dispatch_baseline.py` / `_greedy.py` / `_coordinated.py` | Die drei Prioritätsregeln (FCFS / lokales SPT / ATCS-Index) |
| `warehouse_ortools_solver.py` | CP-SAT-Modell (Maschinen-Zuordnung, sequenzabhängige Repositionierungszeiten, Verspätungsstrafe) |
| `warehouse_evaluation.py` | Gemeinsame KPI-Berechnung inkl. Fristberechnung (`due_time_for_order`) |
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
