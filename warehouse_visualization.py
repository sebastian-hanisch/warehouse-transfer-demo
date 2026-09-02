"""Plotly visualizations: static warehouse layout, per-transporter Gantt
chart (the main "hook" view - gaps are idle transporters, color shows which
order/leg they carried, light hatched bars are repositioning/deadhead
travel), an order-level transfer-wait chart, a package animation, and a
cross-method KPI comparison."""

import plotly.graph_objects as go

ZONE_COLOR_SEQUENCE = [
    "#2563eb", "#059669", "#d97706", "#dc2626", "#7c3aed", "#0891b2",
]


def zone_colors(network):
    colors = {network.hub_id: "#334155"}
    for i, aisle_id in enumerate(network.aisle_ids):
        colors[aisle_id] = ZONE_COLOR_SEQUENCE[i % len(ZONE_COLOR_SEQUENCE)]
    return colors


def build_warehouse_figure(network):
    colors = zone_colors(network)
    fig = go.Figure()

    for zone_id, zone in network.zones.items():
        xs, ys = [], []
        for u, v in zone.graph.edges():
            x0, y0 = network.positions[u]
            x1, y1 = network.positions[v]
            xs += [x0, x1, None]
            ys += [y0, y1, None]
        fig.add_trace(
            go.Scatter(
                x=xs, y=ys, mode="lines", line=dict(color=colors[zone_id], width=4),
                name=zone_id, hoverinfo="skip", showlegend=True,
            )
        )

    transfer_nodes = set(network.transfer_node_of_aisle.values())
    for zone_id, zone in network.zones.items():
        node_x, node_y, node_text, node_symbol = [], [], [], []
        for node in zone.nodes:
            x, y = network.positions[node]
            node_x.append(x)
            node_y.append(y)
            is_transfer = node in transfer_nodes
            node_text.append(f"{node} (Umschlagpunkt)" if is_transfer else node)
            node_symbol.append("diamond" if is_transfer else "circle")
        fig.add_trace(
            go.Scatter(
                x=node_x, y=node_y, mode="markers", marker=dict(size=10, color=colors[zone_id], symbol=node_symbol),
                text=node_text, hoverinfo="text", showlegend=False,
            )
        )

    fig.update_layout(
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        margin=dict(l=10, r=10, t=30, b=10), height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


REPOSITIONING_COLOR = "#cbd5e1"  # light gray - deliberately muted vs. the zone colors of loaded legs


def build_gantt_figure(schedule, network, transporters_per_zone):
    colors = zone_colors(network)
    transporter_order = []
    for zone_id in [network.hub_id] + network.aisle_ids:
        for slot in range(transporters_per_zone.get(zone_id, 0)):
            transporter_order.append(f"{zone_id}#{slot}")

    fig = go.Figure()
    legend_shown = False
    for a in sorted(schedule.assignments, key=lambda a: a.start):
        wait = max(a.start - a.ready_time, 0.0)  # same definition as warehouse_evaluation.py's transfer_wait
        if a.repositioning_time > 0:
            fig.add_trace(
                go.Bar(
                    x=[a.repositioning_time],
                    y=[a.transporter_id],
                    base=[a.start - a.repositioning_time],
                    orientation="h",
                    marker=dict(color=REPOSITIONING_COLOR, pattern=dict(shape="/")),
                    name="Leerfahrt (Repositionierung)",
                    legendgroup="repositioning",
                    showlegend=not legend_shown,
                    hovertext=(
                        f"Leerfahrt zu Auftrag {a.order_id}, Leg {a.leg_index}<br>"
                        f"Ziel: {a.entry_node}<br>"
                        f"{a.start - a.repositioning_time:.1f} - {a.start:.1f} min"
                    ),
                    hoverinfo="text",
                )
            )
            legend_shown = True
        fig.add_trace(
            go.Bar(
                x=[a.end - a.start],
                y=[a.transporter_id],
                base=[a.start],
                orientation="h",
                marker=dict(color=colors[a.zone_id]),
                hovertext=(
                    f"Auftrag {a.order_id}, Leg {a.leg_index}<br>"
                    f"{a.entry_node} -> {a.exit_node}<br>"
                    f"{a.start:.1f} - {a.end:.1f} min<br>"
                    f"Umstiegs-Wartezeit: {wait:.1f} min"
                ),
                hoverinfo="text",
                showlegend=False,
            )
        )

    fig.update_layout(
        barmode="overlay",
        xaxis_title="Zeit (min)",
        yaxis=dict(categoryorder="array", categoryarray=list(reversed(transporter_order))),
        margin=dict(l=10, r=10, t=30, b=10), height=max(320, 28 * len(transporter_order)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def build_transfer_wait_figure(evaluations):
    """evaluations: dict method -> EvaluationResult, for the comparison view."""
    fig = go.Figure()
    for method, result in evaluations.items():
        order_ids = [o.order_id for o in result.orders]
        waits = [o.transfer_wait for o in result.orders]
        fig.add_trace(go.Bar(x=order_ids, y=waits, name=method))

    fig.update_layout(
        barmode="group",
        xaxis_title="Auftrag",
        yaxis_title="Umstiegs-Wartezeit (min)",
        margin=dict(l=10, r=10, t=30, b=10), height=360,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def build_kpi_comparison_figure(evaluations):
    methods = list(evaluations.keys())
    lead = [evaluations[m].avg_lead_time for m in methods]
    wait = [evaluations[m].avg_transfer_wait for m in methods]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=methods, y=lead, name="Durchschn. Durchlaufzeit (min)"))
    fig.add_trace(go.Bar(x=methods, y=wait, name="Durchschn. Umstiegs-Wartezeit (min)"))
    fig.update_layout(
        barmode="group", margin=dict(l=10, r=10, t=30, b=10), height=360,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def _interpolate(p0, p1, t):
    return (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)


def _package_position(network, order, legs_sorted, t):
    """legs_sorted: this order's LegAssignments sorted by leg_index."""
    if t < order.release_time:
        return None
    if t >= legs_sorted[-1].end:
        return network.positions[legs_sorted[-1].exit_node]

    for a in legs_sorted:
        if a.start <= t <= a.end:
            entry_pos = network.positions[a.entry_node]
            exit_pos = network.positions[a.exit_node]
            span = a.end - a.start
            frac = 0.0 if span <= 0 else (t - a.start) / span
            return _interpolate(entry_pos, exit_pos, frac)

    # between legs -> waiting at the handover node
    for prev_a, next_a in zip(legs_sorted, legs_sorted[1:]):
        if prev_a.end <= t <= next_a.start:
            return network.positions[prev_a.exit_node]
    return network.positions[legs_sorted[0].entry_node]


def build_animation_figure(schedule, network, orders, n_frames=30):
    base_fig = build_warehouse_figure(network)
    static_traces = list(base_fig.data)

    by_order = {}
    for a in schedule.assignments:
        by_order.setdefault(a.order_id, []).append(a)
    for legs in by_order.values():
        legs.sort(key=lambda a: a.leg_index)

    makespan = max((legs[-1].end for legs in by_order.values()), default=1.0)
    orders_by_id = {o.order_id: o for o in orders}
    times = [makespan * i / max(n_frames - 1, 1) for i in range(n_frames)]

    frames = []
    for t in times:
        xs, ys, texts = [], [], []
        for order_id, legs in by_order.items():
            order = orders_by_id[order_id]
            pos = _package_position(network, order, legs, t)
            if pos is None:
                continue
            xs.append(pos[0])
            ys.append(pos[1])
            texts.append(f"Auftrag {order_id}")
        frames.append(
            go.Frame(
                data=static_traces + [go.Scatter(x=xs, y=ys, mode="markers", marker=dict(size=9, color="#f97316", symbol="square"), text=texts, hoverinfo="text", showlegend=False)],
                name=f"{t:.1f}",
            )
        )

    fig = go.Figure(data=frames[0].data if frames else static_traces, frames=frames)
    fig.update_layout(
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        margin=dict(l=10, r=10, t=30, b=10), height=460,
        updatemenus=[
            dict(
                type="buttons", showactive=False, y=1.08, x=0.0,
                buttons=[
                    dict(label="Play", method="animate", args=[None, {"frame": {"duration": 200, "redraw": True}, "fromcurrent": True}]),
                    dict(label="Pause", method="animate", args=[[None], {"frame": {"duration": 0}, "mode": "immediate"}]),
                ],
            )
        ],
        sliders=[
            dict(
                steps=[
                    dict(method="animate", args=[[f.name], {"frame": {"duration": 0, "redraw": True}, "mode": "immediate"}], label=f.name)
                    for f in frames
                ],
                x=0.0, y=-0.02, len=1.0,
            )
        ],
    )
    return fig
