"""PDF export of one method's dispatch plan (fpdf2, in-memory).

ASCII-only where formatting is concerned (no en-dash) - the core Helvetica
font that ships with fpdf2 cannot render U+2013, a bug already found and
fixed the hard way in the sibling shift-planning demo.
"""

from fpdf import FPDF

from warehouse_constants import METHOD_LABELS


def generate_dispatch_pdf(method, evaluation_result, orders_by_id):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Lagerlogistik: Transportplan", ln=True)

    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, f"Verfahren: {METHOD_LABELS.get(method, method)}", ln=True)
    pdf.cell(0, 8, f"Auftraege: {len(evaluation_result.orders)}", ln=True)
    pdf.cell(0, 8, f"Gesamtdurchlaufzeit: {evaluation_result.total_lead_time:.1f} min", ln=True)
    pdf.cell(0, 8, f"Durchschn. Durchlaufzeit: {evaluation_result.avg_lead_time:.1f} min", ln=True)
    pdf.cell(0, 8, f"Umstiegs-Wartezeit gesamt: {evaluation_result.total_transfer_wait:.1f} min", ln=True)
    pdf.cell(0, 8, f"Puenktlichkeit: {evaluation_result.on_time_rate * 100:.0f}%", ln=True)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 9)
    headers = ["Auftrag", "Von -> Nach", "Start", "Ankunft", "Laufzeit", "Umstiege", "Wartezeit", "Termin"]
    widths = [16, 55, 18, 20, 20, 18, 22, 20]
    for h, w in zip(headers, widths):
        pdf.cell(w, 7, h, border=1)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for r in evaluation_result.orders:
        order = orders_by_id[r.order_id]
        route_text = f"{order.origin_node} -> {order.destination_node}"
        row = [
            str(r.order_id),
            route_text,
            f"{r.release_time:.1f}",
            f"{r.completion_time:.1f}",
            f"{r.lead_time:.1f}",
            str(r.n_transfers),
            f"{r.transfer_wait:.1f}",
            "OK" if r.on_time else "spaet",
        ]
        for val, w in zip(row, widths):
            pdf.cell(w, 6, val, border=1)
        pdf.ln()

    return bytes(pdf.output())
