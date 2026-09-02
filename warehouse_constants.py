"""Default values and limits for the warehouse-transfer demo."""

# Zone layout (hub-and-spoke: N aisle zones around one central hub zone)
DEFAULT_N_AISLES = 3
MIN_N_AISLES = 2
MAX_N_AISLES = 5

DEFAULT_NODES_PER_AISLE = 5
MIN_NODES_PER_AISLE = 3
MAX_NODES_PER_AISLE = 8

DEFAULT_HUB_NODES = 2
MIN_HUB_NODES = 1
MAX_HUB_NODES = 6

# Transporters
DEFAULT_TRANSPORTERS_PER_AISLE = 1
MIN_TRANSPORTERS_PER_AISLE = 1
MAX_TRANSPORTERS_PER_AISLE = 4

DEFAULT_TRANSPORTERS_HUB = 1
MIN_TRANSPORTERS_HUB = 1
MAX_TRANSPORTERS_HUB = 6

DEFAULT_AISLE_SPEED = 1.0   # nodes per minute, shuttle in a rack aisle
DEFAULT_HUB_SPEED = 2.0     # nodes per minute, faster central conveyor/lift

# Handover: fixed time an item needs at a transfer node to physically move
# from one transporter onto the next (docking/lift/conveyor handoff).
DEFAULT_HANDOVER_MINUTES = 1.0
MIN_HANDOVER_MINUTES = 0.0
MAX_HANDOVER_MINUTES = 5.0

# Orders
DEFAULT_N_ORDERS = 20
MIN_N_ORDERS = 5
MAX_N_ORDERS = 60

DEFAULT_HORIZON_MINUTES = 60.0
MIN_HORIZON_MINUTES = 10.0
MAX_HORIZON_MINUTES = 180.0

# Share of orders that must cross zones (origin/destination in different
# aisles). The rest stay within a single aisle (no transfer needed) - keeps
# the scenario realistic instead of forcing every single order to transfer.
DEFAULT_CROSS_ZONE_SHARE = 0.7
MIN_CROSS_ZONE_SHARE = 0.0
MAX_CROSS_ZONE_SHARE = 1.0

DEFAULT_SEED = 42
MIN_SEED = 0
MAX_SEED = 9999

# Due dates (derived, not user-facing sliders): due_time = release_time +
# factor * theoretical minimum route time + DUE_DATE_BUFFER_MINUTES. Express
# orders get a tighter factor - the same generous buffer, but less slack
# multiplied onto the minimum route time.
DUE_DATE_FACTOR = 3.0
DUE_DATE_FACTOR_EXPRESS = 1.5
DUE_DATE_BUFFER_MINUTES = 5.0

# Share of orders flagged as express (tighter due date). Only the coordinated
# heuristic and OR-Tools actually use the flag as a dispatch signal - baseline
# (FCFS) and greedy (local SPT) stay blind to it by design, the same way real
# naive/local dispatch often ignores stated priorities.
DEFAULT_EXPRESS_SHARE = 0.2
MIN_EXPRESS_SHARE = 0.0
MAX_EXPRESS_SHARE = 1.0

# Coordinated: multiplies an express order's priority score down (lower score
# = served first in this codebase's convention), so it consistently jumps
# ahead of similar-priority non-express legs without discarding the
# underlying SPT + remaining-work logic.
EXPRESS_PRIORITY_FACTOR = 0.5

# OR-Tools: weight on an express order's completion time in the objective
# (weighted sum of completion times, a classic scheduling formulation) -
# higher weight makes finishing it early matter proportionally more.
EXPRESS_WEIGHT = 3

# OR-Tools
DEFAULT_ORTOOLS_TIME_LIMIT = 3
MAX_ORTOOLS_TIME_LIMIT = 5
ORTOOLS_COOLDOWN_BUFFER_SECONDS = 3

METHOD_BASELINE = "baseline"
METHOD_GREEDY = "greedy"
METHOD_COORDINATED = "coordinated"
METHOD_ORTOOLS = "ortools"

METHOD_LABELS = {
    METHOD_BASELINE: "Unoptimiert (FCFS)",
    METHOD_GREEDY: "Dezentral je Zone (Greedy)",
    METHOD_COORDINATED: "Koordiniert (eigene Heuristik)",
    METHOD_ORTOOLS: "OR-Tools (CP-SAT)",
}
