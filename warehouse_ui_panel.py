"""Reusable Streamlit panel: renders one dispatch method's result (KPI
metrics, order table, Gantt chart, PDF download) - used identically for all
four tabs so they stay visually consistent."""

import pandas as pd
import streamlit as st

from warehouse_pdf_export import generate_dispatch_pdf
from warehouse_visualization import build_gantt_figure


def render_method_panel(method, schedule, evaluation_result, orders_by_id, network, transporters_per_zone, extra_caption=None):
    has_express = any(r.is_express for r in evaluation_result.orders)
    cols = st.columns(5 if has_express else 4)
    cols[0].metric("Gesamtdurchlaufzeit", f"{evaluation_result.total_lead_time:.0f} min")
    cols[1].metric("Umstiegs-Wartezeit gesamt", f"{evaluation_result.total_transfer_wait:.0f} min")
    cols[2].metric("Pünktlichkeit", f"{evaluation_result.on_time_rate * 100:.0f}%")
    cols[3].metric("Letzte Auslieferung", f"{evaluation_result.makespan:.0f} min")
    if has_express:
        cols[4].metric("Pünktlichkeit Express", f"{evaluation_result.on_time_rate_express * 100:.0f}%")

    if extra_caption:
        st.caption(extra_caption)

    st.plotly_chart(build_gantt_figure(schedule, network, transporters_per_zone), width='stretch', key=f"gantt_{method}")

    with st.expander("Auftragstabelle"):
        rows = []
        for r in evaluation_result.orders:
            order = orders_by_id[r.order_id]
            rows.append(
                {
                    "Auftrag": r.order_id,
                    "Express": "🚀" if r.is_express else "",
                    "Von": order.origin_node,
                    "Nach": order.destination_node,
                    "Start": round(r.release_time, 1),
                    "Ankunft": round(r.completion_time, 1),
                    "Laufzeit (min)": round(r.lead_time, 1),
                    "Umstiege": r.n_transfers,
                    "Wartezeit (min)": round(r.transfer_wait, 1),
                    "Termin": "OK" if r.on_time else "spät",
                }
            )
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

    pdf_bytes = generate_dispatch_pdf(method, evaluation_result, orders_by_id)
    st.download_button(
        "PDF-Transportplan herunterladen", data=pdf_bytes,
        file_name=f"transportplan_{method}.pdf", mime="application/pdf", key=f"pdf_{method}",
    )
