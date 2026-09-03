import frappe
import json
import re
from frappe.model.document import Document

VALID_TRANSITIONS = {
    "Draft": ["Under Review"],
    "Under Review": ["Approved", "Draft"],
    "Approved": ["Closed"],
    "Closed": []
}

# ══════════════════════════════════════════════════════════════════════════
# DESIGN NOTE (read this before touching validate()):
#
# The print format now follows ONE consistent rule everywhere: the doctor
# -facing ERPNext field (a plain Data/Text/Small Text field on this doctype)
# is always checked FIRST. The AI-generated structured JSON in `notes` is
# only used as a fallback when the corresponding ERPNext field is empty.
#
# Because of that, narrative/free-text fields (chief_complaint, anamnesis,
# past_medical_history, allergies, general_examination, systemic_examination,
# review_of_systems, ayurvedic_diagnosis, allopathic_diagnosis,
# allopathic_medicines, panchakarma, detox_procedures, exercises_yoga,
# diet_include, diet_exclude, lifestyle_advice, home_remedies,
# investigations_advised, follow_up, followup_doc, review_after,
# rx_quick_summary, rx_daily_regimen, oil_applications, breathing_exercises)
# do NOT need to be synced into `notes` at all. Editing them in the form is
# immediately reflected on the print format with zero extra code, and the
# richer AI JSON is preserved untouched underneath as a fallback/audit trail
# instead of being partially overwritten and lost.
#
# The previous version of this file tried to sync those fields into `notes`
# and had several confirmed bugs as a result:
#   - allopathic_medicines was written to notes["treatment_and_plan"], but
#     the print format reads notes["treatment_and_background"] (key typo)
#   - ayurvedic_diagnosis / allopathic_diagnosis / rx_quick_summary /
#     rx_daily_regimen were written into notes["_final_case_sheet"]
#     ["erp_field_summaries"], a key the print format never reads at all
#   - detox_procedures / exercises_yoga wrote the SAME text into both the
#     "cleared list" fallback path and a sibling "notes" key that the print
#     format also displays, causing the text to print twice
#   - chief_complaint / anamnesis / general_examination /
#     systemic_examination overwrote the AI's structured sub-fields with a
#     stub dict, silently discarding data (aggravating factors, pallor,
#     cardiovascular findings, etc.)
#   - review_of_systems overwrote notes["review_of_systems"] with
#     {"summary": text}; the print format's ROS table only renders dict
#     values under each system key, so the doctor's text disappeared
#     entirely with no visible fallback
#
# Only the two fields that are genuinely tabular/structured — the
# supplements 8-week grid and the pulse diagnosis grid — still need real
# sync logic, because they map to Frappe child tables with their own shape.
# That logic is kept below, with fixes (see inline comments).
# ══════════════════════════════════════════════════════════════════════════


def parse_sgp_rx_text(text, existing_supplements=None):
    """Parse free-text supplement lines (used only when the doctor types
    directly into the 'SGP Supplements (Rx)' text field instead of using
    the structured table) into the same shape as the AI JSON / child table.
    """
    if not text:
        return []
    existing_map = {}
    if existing_supplements and isinstance(existing_supplements, list):
        for item in existing_supplements:
            if isinstance(item, dict) and item.get("name"):
                existing_map[str(item.get("name")).upper().strip()] = item

    results = []
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for line in lines:
        start_week_str = "1st week"
        start_idx = 0
        # NOTE: kept the original (fairly loose) week-detection regex, but
        # fixed the alternation grouping so "2nd week" / "week 2" style
        # phrases are actually matched consistently. This is still
        # best-effort text parsing, not a strict grammar — if a doctor
        # needs precise week/dose control they should use the structured
        # "SGP Supplements & Regimen Table" instead of this free-text field.
        week_match = re.search(r'(\d+)(?:st|nd|rd|th)\s*week|week\s*(\d+)', line, re.IGNORECASE)
        if week_match:
            match_text = week_match.group(0)
            num_match = re.search(r'\d+', match_text)
            if num_match:
                start_idx = max(0, min(7, int(num_match.group(0)) - 1))
                ordinal = ("st" if start_idx == 0 else
                           "nd" if start_idx == 1 else
                           "rd" if start_idx == 2 else "th")
                start_week_str = f"{start_idx + 1}{ordinal} week"
            line_without_week = line.replace(match_text, "").strip()
        else:
            line_without_week = line

        dose_match = re.search(r'(\d+/\d+(?:\s*-\s*\d+/\d+)*)', line_without_week)
        doses_list = []
        if dose_match:
            dose_str = dose_match.group(1)
            doses_list = [d.strip() for d in dose_str.split("-") if d.strip()]
            name_part = line_without_week.replace(dose_str, "").strip(" -:;,.")
        else:
            name_part = line_without_week.strip(" -:;,.")

        name = name_part.upper().strip()
        if not name:
            continue

        # FIX: default cells to "" instead of None. The print format does
        # `wk[w] if wk|length > w else ""` — a list of Nones is still
        # truthy, so every unfilled week previously printed the literal
        # word "None" instead of a blank cell.
        weeks = [""] * 8
        current_dose = ""
        for i in range(start_idx, 8):
            if (i - start_idx) < len(doses_list):
                current_dose = doses_list[i - start_idx]
            weeks[i] = current_dose

        existing = existing_map.get(name, {})
        supplement = {
            "name": name,
            "medicine_category": existing.get("medicine_category", "SGP proprietary"),
            "quantity_mg": existing.get("quantity_mg", ""),
            "weeks": weeks,
            "start_week": start_week_str,
            "dose": " -> ".join(doses_list) if doses_list else existing.get("dose", ""),
            "frequency": existing.get("frequency", "BID"),
            "route": existing.get("route", "PO (Oral)"),
            "timing": existing.get("timing", "morning and evening"),
            "remarks": existing.get("remarks", None),
            "needs_doctor_confirmation": []
        }
        results.append(supplement)
    return results


class SGPEncounter(Document):
    def validate(self):
        # ── Appointment link (optional for walk-in patients) ──────────────
        if self.appointment:
            appointment = frappe.get_doc("Patient Appointment", self.appointment)
            if appointment.get("created_from_lead"):
                lead = frappe.get_doc("SGP Lead", appointment.created_from_lead)
                self.lead = lead.name

        # ── Consent gate ──────────────────────────────────────────────────
        if self.status in ["Under Review", "Approved", "Closed"]:
            if not self.consent_verified:
                frappe.throw("Cannot proceed without consent verification.")

        old_doc = None
        if not self.is_new():
            old_doc = self.get_doc_before_save()
            # ── Status transition protection ───────────────────────────────
            if old_doc and old_doc.status != self.status:
                allowed = VALID_TRANSITIONS.get(old_doc.status, [])
                if self.status not in allowed:
                    frappe.throw(
                        f"Invalid status transition from {old_doc.status} to {self.status}"
                    )

        # ── Parse existing notes JSON ──────────────────────────────────────
        if self.notes:
            try:
                notes_dict = json.loads(self.notes) if isinstance(self.notes, str) else dict(self.notes)
            except Exception:
                notes_dict = {}
        else:
            notes_dict = {}

        notes_modified = False

        def had_rows_before(fieldname):
            """True if the child table on the doc-before-save had at least
            one row. Used to tell 'never populated yet' apart from
            'doctor intentionally deleted every row'."""
            if old_doc is None:
                return False
            return bool(old_doc.get(fieldname))

        # ══════════════════════════════════════════════════════════════════
        # SUPPLEMENT CHILD TABLE ↔ notes["ayurvedic_supplements"]
        # ══════════════════════════════════════════════════════════════════
        current_supp_rows = self.get("sgp_supplements_table") or []

        if len(current_supp_rows) > 0:
            supp_list = []
            for row in current_supp_rows:
                wks = [row.w1 or "", row.w2 or "", row.w3 or "", row.w4 or "",
                       row.w5 or "", row.w6 or "", row.w7 or "", row.w8 or ""]
                # Carry the last explicitly-entered dose forward into blank
                # trailing cells (so a doctor doesn't have to retype "1"
                # eight times). To mark a supplement as discontinued, type
                # the literal word "STOP" in the week it ends — that value
                # will itself carry forward as a visible marker instead of
                # silently repeating the last dose.
                last_val = ""
                for i in range(8):
                    if wks[i].strip():
                        last_val = wks[i].strip()
                    else:
                        wks[i] = last_val
                row.w1, row.w2, row.w3, row.w4, row.w5, row.w6, row.w7, row.w8 = wks
                supp_list.append({
                    "name": row.supplement_name or "",
                    "quantity_mg": row.quantity_mg or "",
                    "start_week": str(row.start_week or "1"),
                    "weeks": wks,
                    "frequency": row.frequency or "BID",
                    "timing": row.remarks_instructions or "",
                    "remarks": row.remarks_instructions or "",
                    "needs_doctor_confirmation": []
                })
            notes_dict["ayurvedic_supplements"] = supp_list
            notes_modified = True

        elif had_rows_before("sgp_supplements_table"):
            # FIX: doctor intentionally cleared every row — respect that
            # instead of resurrecting the old AI JSON on the next save.
            if notes_dict.get("ayurvedic_supplements"):
                notes_dict["ayurvedic_supplements"] = []
                notes_modified = True

        elif notes_dict.get("ayurvedic_supplements") and self.is_new():
            # First-load-only: seed the child table from the AI JSON.
            for item in notes_dict.get("ayurvedic_supplements", []):
                if isinstance(item, dict) and item.get("name"):
                    wks = item.get("weeks") or [""] * 8
                    wks = [("" if w is None else str(w)) for w in wks]
                    while len(wks) < 8:
                        wks.append("")
                    self.append("sgp_supplements_table", {
                        "supplement_name": item.get("name"),
                        "quantity_mg": item.get("quantity_mg") or "1000mg",
                        "start_week": str(item.get("start_week") or "1"),
                        "w1": wks[0], "w2": wks[1], "w3": wks[2], "w4": wks[3],
                        "w5": wks[4], "w6": wks[5], "w7": wks[6], "w8": wks[7],
                        "frequency": item.get("frequency") or "BID",
                        "remarks_instructions": item.get("timing") or item.get("remarks") or ""
                    })

        # SGP Rx free-text fallback → only used if the structured table is
        # genuinely empty (never populated) and the doctor typed directly
        # into the text field.
        if self.sgp_rx and len(current_supp_rows) == 0 and not had_rows_before("sgp_supplements_table"):
            existing = notes_dict.get("ayurvedic_supplements", [])
            parsed = parse_sgp_rx_text(self.sgp_rx, existing)
            if parsed:
                notes_dict["ayurvedic_supplements"] = parsed
                notes_modified = True

        # ══════════════════════════════════════════════════════════════════
        # PULSE CHILD TABLE ↔ notes["pulse_diagnosis"]["systems"]
        # ══════════════════════════════════════════════════════════════════
        current_pulse_rows = self.get("sgp_pulse_table") or []
        existing_pulse = notes_dict.get("pulse_diagnosis")
        if not isinstance(existing_pulse, dict):
            existing_pulse = {"overall_vpk": {}}

        if len(current_pulse_rows) > 0:
            pulse_list = []
            for row in current_pulse_rows:
                pulse_list.append({
                    "system": row.system or "",
                    "vata": row.vata or "",
                    "pitta": row.pitta or "",
                    "kapha": row.kapha or ""
                })
            existing_pulse["systems"] = pulse_list
            notes_dict["pulse_diagnosis"] = existing_pulse
            notes_modified = True

        elif had_rows_before("sgp_pulse_table"):
            # FIX: same intentional-clear protection as supplements above.
            if existing_pulse.get("systems"):
                existing_pulse["systems"] = []
                notes_dict["pulse_diagnosis"] = existing_pulse
                notes_modified = True

        elif isinstance(notes_dict.get("pulse_diagnosis"), dict) and self.is_new():
            for item in notes_dict["pulse_diagnosis"].get("systems", []):
                if isinstance(item, dict) and item.get("system"):
                    self.append("sgp_pulse_table", {
                        "system": item.get("system"),
                        "vata": item.get("vata") or "",
                        "pitta": item.get("pitta") or "",
                        "kapha": item.get("kapha") or ""
                    })

        if notes_modified:
            self.notes = json.dumps(notes_dict, ensure_ascii=False)

    def before_save(self):
        if not self.is_new():
            old_doc = self.get_doc_before_save()
            if old_doc and old_doc.status == "Approved" and self.status == "Approved":
                frappe.throw("Approved encounters cannot be edited.")


# ══════════════════════════════════════════════════════════════════════════
# PATIENT HISTORY API — serves the "📋 Patient History" tab
# ══════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def get_patient_history(patient, exclude_encounter=None):
    """Return previous SGP Encounters for a patient, ordered newest-first.

    Called by the client-side JS in sgp_encounter.js to populate the
    'Patient History' tab with a rich timeline of past visits.
    """
    if not patient:
        return []

    filters = {"patient": patient, "docstatus": ["in", [0, 1]]}
    if exclude_encounter:
        filters["name"] = ["!=", exclude_encounter]

    encounters = frappe.get_all(
        "SGP Encounter",
        filters=filters,
        fields=[
            "name", "encounter_date", "status", "doctor", "case_type",
            # Presenting complaints
            "chief_complaint", "anamnesis",
            # History
            "past_medical_history", "medication_history",
            "surgical_history", "allergies",
            "family_history", "menstrual_obstetric_history",
            "personal_history_diet", "personal_history_sleep",
            # Vitals
            "height_cm", "weight_kg", "bp", "temp", "pr", "rr",
            # Examination
            "general_examination", "systemic_examination",
            # Assessment & Diagnosis
            "vpk_dominance", "pulse_diagnosis",
            "ayurvedic_diagnosis", "allopathic_diagnosis",
            "review_of_systems", "investigation_reports",
            # Treatment
            "sgp_rx", "allopathic_medicines", "panchakarma",
            "detox_procedures", "home_remedies",
            "investigations_advised",
            # Diet & Lifestyle
            "diet_include", "diet_exclude",
            "lifestyle_advice", "exercises_yoga",
            # Summary
            "rx_quick_summary", "rx_daily_regimen",
            "oil_applications", "breathing_exercises",
            # Follow-up
            "follow_up", "prognosis", "followup_doc",
            "review_after",
        ],
        order_by="encounter_date desc",
        limit_page_length=50,
    )

    for enc in encounters:
        # Supplement child table
        enc["supplements"] = frappe.get_all(
            "SGP Supplement Item",
            filters={"parent": enc["name"]},
            fields=[
                "supplement_name", "quantity_mg", "frequency",
                "start_week", "remarks_instructions",
                "w1", "w2", "w3", "w4", "w5", "w6", "w7", "w8",
            ],
            order_by="idx",
        )
        # Pulse diagnosis child table
        enc["pulse_items"] = frappe.get_all(
            "SGP Pulse Item",
            filters={"parent": enc["name"]},
            fields=["system", "vata", "pitta", "kapha"],
            order_by="idx",
        )
        # Resolve practitioner name
        if enc.get("doctor"):
            enc["doctor_name"] = frappe.db.get_value(
                "Healthcare Practitioner", enc["doctor"], "practitioner_name"
            ) or enc["doctor"]
        else:
            enc["doctor_name"] = ""

    return encounters