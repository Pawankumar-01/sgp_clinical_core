import frappe
from frappe.model.document import Document

class SGPOrientationAttendance(Document):

    def validate(self):

        # Calculate watch time if join/leave exists
        if self.joined_at and self.left_at:
            diff = frappe.utils.time_diff_in_seconds(self.left_at, self.joined_at)
            self.watch_minutes = int(diff / 60)

        # Inherit minimum required from session if not set
        if not self.min_required_minutes and self.orientation_session:
            session = frappe.get_doc("SGP Orientation Session", self.orientation_session)
            self.min_required_minutes = session.min_watch_minutes

        # Determine completion
        if self.watch_minutes and self.min_required_minutes:
            if self.watch_minutes >= self.min_required_minutes:
                self.orientation_completed = 1
                self.appointment_eligible = 1
                self._update_lead_status()

    def _update_lead_status(self):
        if not self.lead:
            return

        lead = frappe.get_doc("SGP Lead", self.lead)

        if lead.status != "Orientation Completed":
            lead.status = "Orientation Completed"
            lead.orientation_completed = 1
            lead.save(ignore_permissions=True)