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

        # ── Status transition protection & manual field synchronization ────
        if not self.is_new():
            old_doc = self.get_doc_before_save()
            if old_doc and old_doc.status != self.status:
                allowed = VALID_TRANSITIONS.get(old_doc.status, [])
                if self.status not in allowed:
                    frappe.throw(
                        f"Invalid status transition from {old_doc.status} to {self.status}"
                    )

            # Reconcile manual UI edits into self.notes JSON blob for Print Format consistency
            if old_doc and self.notes:
                try:
                    notes_dict = json.loads(self.notes) if isinstance(self.notes, str) else self.notes
                    modified = False

                    # Sync sgp_rx (Ayurvedic Supplements)
                    if self.sgp_rx and self.sgp_rx != old_doc.sgp_rx:
                        existing = notes_dict.get("ayurvedic_supplements", [])
                        notes_dict["ayurvedic_supplements"] = parse_sgp_rx_text(self.sgp_rx, existing)
                        modified = True

                    # Sync panchakarma
                    if self.panchakarma and self.panchakarma != old_doc.panchakarma:
                        if isinstance(notes_dict.get("panchakarma"), dict):
                            notes_dict["panchakarma"]["sessions"] = []
                            notes_dict["panchakarma"]["overall_remarks"] = self.panchakarma
                        else:
                            notes_dict["panchakarma"] = {"sessions": [], "overall_remarks": self.panchakarma}
                        modified = True

                    # Sync detox_procedures
                    if self.detox_procedures and self.detox_procedures != old_doc.detox_procedures:
                        if isinstance(notes_dict.get("detox_procedures"), dict):
                            notes_dict["detox_procedures"]["detox_items"] = []
                            notes_dict["detox_procedures"]["overall_detox_notes"] = self.detox_procedures
                        else:
                            notes_dict["detox_procedures"] = {"detox_items": [], "overall_detox_notes": self.detox_procedures}
                        modified = True

                    # Sync exercises_yoga
                    if self.exercises_yoga and self.exercises_yoga != old_doc.exercises_yoga:
                        if isinstance(notes_dict.get("exercises_yoga"), dict):
                            notes_dict["exercises_yoga"]["exercises"] = []
                            notes_dict["exercises_yoga"]["general_activity_advice"] = self.exercises_yoga
                        else:
                            notes_dict["exercises_yoga"] = {"exercises": [], "general_activity_advice": self.exercises_yoga}
                        modified = True

                    # Sync chief_complaint
                    if self.chief_complaint and self.chief_complaint != old_doc.chief_complaint:
                        if isinstance(notes_dict.get("chief_complaint"), dict):
                            notes_dict["chief_complaint"]["summary"] = self.chief_complaint
                        else:
                            notes_dict["chief_complaint"] = {"summary": self.chief_complaint, "complaints": []}
                        modified = True

                    # Sync anamnesis
                    if self.anamnesis and self.anamnesis != old_doc.anamnesis:
                        if isinstance(notes_dict.get("anamnesis"), dict):
                            notes_dict["anamnesis"]["onset"] = None
                            notes_dict["anamnesis"]["progression"] = None
                            notes_dict["anamnesis"]["summary"] = self.anamnesis
                        else:
                            notes_dict["anamnesis"] = {"summary": self.anamnesis}
                        modified = True

                    # Sync general_examination
                    if self.general_examination and self.general_examination != old_doc.general_examination:
                        if isinstance(notes_dict.get("general_examination"), dict):
                            notes_dict["general_examination"]["other_findings"] = [self.general_examination]
                        else:
                            notes_dict["general_examination"] = {"other_findings": [self.general_examination]}
                        modified = True

                    if modified:
                        self.notes = json.dumps(notes_dict)
                except Exception as e:
                    frappe.logger().error(f"Failed to reconcile manual SGP Encounter field edits into notes JSON: {str(e)}")

    def before_save(self):
        if not self.is_new():
            old_doc = self.get_doc_before_save()
            if old_doc and old_doc.status == "Approved" and self.status == "Approved":
                frappe.throw("Approved encounters cannot be edited.")

