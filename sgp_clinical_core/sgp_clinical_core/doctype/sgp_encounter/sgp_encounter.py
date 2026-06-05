import frappe
from frappe.model.document import Document

VALID_TRANSITIONS = {
    "Draft": ["Under Review"],
    "Under Review": ["Approved", "Draft"],
    "Approved": ["Closed"],
    "Closed": []
}

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

        # ── Status transition protection ──────────────────────────────────
        if not self.is_new():
            old_doc = self.get_doc_before_save()
            if old_doc and old_doc.status != self.status:
                allowed = VALID_TRANSITIONS.get(old_doc.status, [])
                if self.status not in allowed:
                    frappe.throw(
                        f"Invalid status transition from {old_doc.status} to {self.status}"
                    )

    def before_save(self):
        if not self.is_new():
            old_doc = self.get_doc_before_save()
            if old_doc and old_doc.status == "Approved" and self.status == "Approved":
                frappe.throw("Approved encounters cannot be edited.")
