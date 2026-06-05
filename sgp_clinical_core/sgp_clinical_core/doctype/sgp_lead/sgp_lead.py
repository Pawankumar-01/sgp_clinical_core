import frappe
from frappe.model.document import Document

# Status transition rules — values must exactly match the Status Select field options
VALID_TRANSITIONS = {
    "NEW": [
        "ORIENTATION_SCHEDULED",
        "ORIENTATION_ATTENDED",   # allow direct jump from automation
        "DORMANT",
    ],
    "New": [                      # legacy mixed-case alias
        "ORIENTATION_SCHEDULED",
        "ORIENTATION_ATTENDED",
        "DORMANT",
    ],
    "ORIENTATION_SCHEDULED": [
        "ORIENTATION_ATTENDED",
        "REORIENTATION_REQUIRED",
        "DORMANT",
    ],
    "ORIENTATION_ATTENDED": [
        "APPOINTMENT_SCHEDULED",
        "REORIENTATION_REQUIRED",
        "DORMANT",
    ],
    "APPOINTMENT_SCHEDULED": [
        "CONVERTED",
        "REORIENTATION_REQUIRED",
        "DORMANT",
    ],
    "CONVERTED": [],
    "REORIENTATION_REQUIRED": [
        "ORIENTATION_SCHEDULED",
        "DORMANT",
    ],
    "DORMANT": [
        "NEW",
        "ORIENTATION_SCHEDULED",
    ],
}


class SGPLead(Document):

    def validate(self):
        self._validate_status_transition()
        self._sync_device_interest()

    def _validate_status_transition(self):
        """Block invalid status transitions based on VALID_TRANSITIONS map."""
        if self.is_new():
            return  # No transition validation on create

        old_doc = self.get_doc_before_save()
        if not old_doc:
            return
        if old_doc.status == self.status:
            return  # No change — nothing to validate

        allowed = VALID_TRANSITIONS.get(old_doc.status, [])
        if self.status not in allowed:
            frappe.throw(
                f"Invalid status transition: {old_doc.status} → {self.status}. "
                f"Allowed next statuses: {', '.join(allowed) if allowed else 'none (terminal state)'}"
            )

    def _sync_device_interest(self):
        """Auto-set device_interested checkbox when interested_in includes device."""
        if self.interested_in in ("DEVICE", "BOTH"):
            self.device_interested = 1
        else:
            self.device_interested = 0