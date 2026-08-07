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


def parse_sgp_rx_text(text, existing_supplements=None):
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
        # Check for start week keywords like "2nd week", "week 2", "3rd week"
        start_week_str = "1st week"
        start_idx = 0
        week_match = re.search(r'(\d+)st|\d+nd|\d+rd|\d+th\s*week|week\s*(\d+)', line, re.IGNORECASE)
        if week_match:
            match_text = week_match.group(0)
            num_match = re.search(r'\d+', match_text)
            if num_match:
                start_idx = max(0, int(num_match.group(0)) - 1)
                start_week_str = f"{start_idx + 1}{'st' if start_idx==0 else ('nd' if start_idx==1 else ('rd' if start_idx==2 else 'th'))} week"
            line_without_week = line.replace(match_text, "").strip()
        else:
            line_without_week = line

        # Check for dosage fraction patterns like "1/4-1/2-3/4" or "1/8 - 1/4" or single "1/4"
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

        weeks = [None] * 8
        current_dose = None
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

        # ── Status transition protection ───────────────────────────────────
        if not self.is_new():
            old_doc = self.get_doc_before_save()
            if old_doc and old_doc.status != self.status:
                allowed = VALID_TRANSITIONS.get(old_doc.status, [])
                if self.status not in allowed:
                    frappe.throw(
                        f"Invalid status transition from {old_doc.status} to {self.status}"
                    )
        else:
            old_doc = None

        # ── Parse existing notes JSON ──────────────────────────────────────
        if self.notes:
            try:
                notes_dict = json.loads(self.notes) if isinstance(self.notes, str) else dict(self.notes)
            except Exception:
                notes_dict = {}
        else:
            notes_dict = {}

        notes_modified = False

        # ══════════════════════════════════════════════════════════════════
        # RULE: Manual text edits ALWAYS take priority.
        # If a doctor changed a field, write their value into notes_dict
        # and clear any conflicting structured JSON so the print format
        # shows the manual text via its fallback path.
        # ══════════════════════════════════════════════════════════════════

        def field_changed(field_name):
            """True if the field was changed from its previous value."""
            if old_doc is None:
                return False
            return getattr(self, field_name, None) != getattr(old_doc, field_name, None)

        # Chief Complaint
        if field_changed("chief_complaint"):
            notes_dict["chief_complaint"] = {"summary": self.chief_complaint or "", "complaints": []}
            notes_modified = True

        # Anamnesis / History of Present Illness
        if field_changed("anamnesis"):
            notes_dict["anamnesis"] = {"onset": "", "progression": "", "summary": self.anamnesis or ""}
            notes_modified = True

        # Pulse Diagnosis text field (clears the AI JSON so table fallback shows doc field in print)
        if field_changed("pulse_diagnosis"):
            # Preserve overall_vpk, clear systems array so print format falls back to text
            existing_pulse = notes_dict.get("pulse_diagnosis", {})
            if isinstance(existing_pulse, dict):
                existing_pulse["systems"] = []
            else:
                existing_pulse = {"systems": [], "overall_vpk": {}}
            notes_dict["pulse_diagnosis"] = existing_pulse
            # Also clear the child table so it doesn't override the text
            self.set("sgp_pulse_table", [])
            notes_modified = True

        # Past Medical History
        if field_changed("past_medical_history"):
            existing_pmh = notes_dict.get("past_medical_history", {})
            if isinstance(existing_pmh, dict):
                existing_pmh["medical"] = []
                existing_pmh["summary"] = self.past_medical_history or ""
            else:
                existing_pmh = {"medical": [], "surgical": [], "summary": self.past_medical_history or ""}
            notes_dict["past_medical_history"] = existing_pmh
            notes_modified = True

        # Allopathic Medicines (current medications)
        if field_changed("allopathic_medicines"):
            existing_tx = notes_dict.get("treatment_and_plan", {})
            if isinstance(existing_tx, dict):
                existing_tx["current_medications"] = []
                existing_tx["allopathic_medicines_text"] = self.allopathic_medicines or ""
            else:
                existing_tx = {"current_medications": [], "allopathic_medicines_text": self.allopathic_medicines or ""}
            notes_dict["treatment_and_plan"] = existing_tx
            notes_modified = True

        # Allergies
        if field_changed("allergies"):
            existing_pmh = notes_dict.get("past_medical_history", {})
            if isinstance(existing_pmh, dict):
                existing_pmh["allergies"] = []
                existing_pmh["allergies_text"] = self.allergies or ""
            else:
                existing_pmh = {"medical": [], "allergies": [], "allergies_text": self.allergies or ""}
            notes_dict["past_medical_history"] = existing_pmh
            notes_modified = True

        # Review of Systems
        if field_changed("review_of_systems"):
            notes_dict["review_of_systems"] = {"summary": self.review_of_systems or ""}
            notes_modified = True

        # General Examination
        if field_changed("general_examination"):
            notes_dict["general_examination"] = {"other_findings": [], "summary": self.general_examination or ""}
            notes_modified = True

        # Systemic Examination
        if field_changed("systemic_examination"):
            notes_dict["systemic_examination"] = {"summary": self.systemic_examination or ""}
            notes_modified = True

        # Ayurvedic Diagnosis
        if field_changed("ayurvedic_diagnosis"):
            erp_summaries = notes_dict.get("_final_case_sheet", {}).get("erp_field_summaries", {})
            erp_summaries["ayurvedic_diagnosis"] = self.ayurvedic_diagnosis or ""
            if "_final_case_sheet" not in notes_dict:
                notes_dict["_final_case_sheet"] = {}
            notes_dict["_final_case_sheet"]["erp_field_summaries"] = erp_summaries
            notes_modified = True

        # Allopathic Diagnosis
        if field_changed("allopathic_diagnosis"):
            erp_summaries = notes_dict.get("_final_case_sheet", {}).get("erp_field_summaries", {})
            erp_summaries["allopathic_diagnosis"] = self.allopathic_diagnosis or ""
            if "_final_case_sheet" not in notes_dict:
                notes_dict["_final_case_sheet"] = {}
            notes_dict["_final_case_sheet"]["erp_field_summaries"] = erp_summaries
            notes_modified = True

        # Executive Prescription Summary
        if field_changed("rx_quick_summary"):
            erp_summaries = notes_dict.get("_final_case_sheet", {}).get("erp_field_summaries", {})
            erp_summaries["rx_quick_summary"] = self.rx_quick_summary or ""
            if "_final_case_sheet" not in notes_dict:
                notes_dict["_final_case_sheet"] = {}
            notes_dict["_final_case_sheet"]["erp_field_summaries"] = erp_summaries
            notes_modified = True

        # Daily Regimen Instructions
        if field_changed("rx_daily_regimen"):
            erp_summaries = notes_dict.get("_final_case_sheet", {}).get("erp_field_summaries", {})
            erp_summaries["rx_daily_regimen"] = self.rx_daily_regimen or ""
            if "_final_case_sheet" not in notes_dict:
                notes_dict["_final_case_sheet"] = {}
            notes_dict["_final_case_sheet"]["erp_field_summaries"] = erp_summaries
            notes_modified = True

        # Panchakarma
        if field_changed("panchakarma"):
            notes_dict["panchakarma"] = {"sessions": [], "overall_remarks": self.panchakarma or ""}
            notes_modified = True

        # Detox Procedures
        if field_changed("detox_procedures"):
            notes_dict["detox_procedures"] = {"detox_items": [], "overall_detox_notes": self.detox_procedures or ""}
            notes_modified = True

        # Exercises / Yoga
        if field_changed("exercises_yoga"):
            notes_dict["exercises_yoga"] = {"exercises": [], "general_activity_advice": self.exercises_yoga or ""}
            notes_modified = True

        # SGP Rx text (supplement fallback if table not used)
        if field_changed("sgp_rx") and not self.get("sgp_supplements_table"):
            existing = notes_dict.get("ayurvedic_supplements", [])
            notes_dict["ayurvedic_supplements"] = parse_sgp_rx_text(self.sgp_rx, existing)
            notes_modified = True

        # ══════════════════════════════════════════════════════════════════
        # CHILD TABLE SYNC — only runs when table rows exist.
        # Manual text edits above have already cleared conflicting JSON,
        # so these only trigger when the child table itself has actual data.
        # ══════════════════════════════════════════════════════════════════

        # Supplement child table → notes JSON
        if self.get("sgp_supplements_table") and len(self.get("sgp_supplements_table")) > 0:
            supp_list = []
            for row in self.get("sgp_supplements_table"):
                wks = [row.w1 or "", row.w2 or "", row.w3 or "", row.w4 or "",
                       row.w5 or "", row.w6 or "", row.w7 or "", row.w8 or ""]
                # Auto-fill carry-forward
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
        elif notes_dict.get("ayurvedic_supplements") and not self.get("sgp_supplements_table"):
            # Populate table from AI JSON (first load only)
            for item in notes_dict.get("ayurvedic_supplements", []):
                if isinstance(item, dict) and item.get("name"):
                    wks = item.get("weeks") or [""] * 8
                    while len(wks) < 8:
                        wks.append("")
                    self.append("sgp_supplements_table", {
                        "supplement_name": item.get("name"),
                        "quantity_mg": item.get("quantity_mg") or "1000mg",
                        "start_week": str(item.get("start_week") or "1"),
                        "w1": str(wks[0] or ""), "w2": str(wks[1] or ""),
                        "w3": str(wks[2] or ""), "w4": str(wks[3] or ""),
                        "w5": str(wks[4] or ""), "w6": str(wks[5] or ""),
                        "w7": str(wks[6] or ""), "w8": str(wks[7] or ""),
                        "frequency": item.get("frequency") or "BID",
                        "remarks_instructions": item.get("timing") or item.get("remarks") or ""
                    })

        # Pulse child table → notes JSON (only if text field was NOT just edited)
        if self.get("sgp_pulse_table") and len(self.get("sgp_pulse_table")) > 0 and not field_changed("pulse_diagnosis"):
            pulse_base = notes_dict.get("pulse_diagnosis", {})
            if not isinstance(pulse_base, dict):
                pulse_base = {"overall_vpk": {}}
            pulse_list = []
            for row in self.get("sgp_pulse_table"):
                pulse_list.append({
                    "system": row.system or "",
                    "vata": row.vata or "",
                    "pitta": row.pitta or "",
                    "kapha": row.kapha or ""
                })
            pulse_base["systems"] = pulse_list
            notes_dict["pulse_diagnosis"] = pulse_base
            notes_modified = True
        elif notes_dict.get("pulse_diagnosis") and isinstance(notes_dict["pulse_diagnosis"], dict) \
                and not self.get("sgp_pulse_table"):
            # Populate pulse table from AI JSON (first load only)
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

