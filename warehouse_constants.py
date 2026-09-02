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
# theoretical minimum route time + a FIXED extra allowance in minutes -
# additive, not a multiplier on the minimum route time, so a long route
# doesn't earn proportionally more slack than a short one just for being
# long. Express orders get a smaller fixed allowance than normal orders;
# every order's deadline still stays at least the theoretical minimum
# above release time, so it's always physically reachable.
DUE_DATE_BUFFER_MINUTES = 20.0
DUE_DATE_BUFFER_MINUTES_EXPRESS = 8.0

# Share of orders flagged as express (tighter due date). Only the coordinated
# heuristic and OR-Tools actually use the flag as a dispatch signal - baseline
# (FCFS) and greedy (local SPT) stay blind to it by design, the same way real
# naive/local dispatch often ignores stated priorities.
DEFAULT_EXPRESS_SHARE = 0.2
MIN_EXPRESS_SHARE = 0.0
MAX_EXPRESS_SHARE = 1.0

# Weight on an express order's completion time - genuinely SHARED between
# OR-Tools' objective (weighted sum of completion times) and Koordiniert's
# ATCS priority index (as the w in its w/p term) - higher weight makes
# finishing an express order early matter proportionally more, the same
# way in both. Used to be two independently-tuned numbers
# (EXPRESS_PRIORITY_FACTOR for coordinated, this one for OR-Tools) until
# coordinated was rebuilt around ATCS, which naturally takes a weight
# instead of a discount factor.
EXPRESS_WEIGHT = 3

# OR-Tools ONLY: cost of one minute of lateness (completion_time beyond
# due_time), relative to one minute of ordinary completion time (whose
# implicit weight is 1) - blended into the same weighted-completion-time
# objective via a `max(0, completion - due)` tardiness variable per order.
# Originally meant to be the SAME constant/mechanism for coordinated too,
# but that gated ("already late") version turned out empirically inert
# there (see warehouse_dispatch_coordinated.py's module docstring for why)
# - coordinated now expresses due-date pressure as continuous slack inside
# its ATCS index instead, a genuinely different mechanism. Baseline and
# greedy do not use this - they stay blind to due dates entirely, same as
# they already are to is_express, by design.
TARDINESS_PENALTY_WEIGHT = 0.5

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
