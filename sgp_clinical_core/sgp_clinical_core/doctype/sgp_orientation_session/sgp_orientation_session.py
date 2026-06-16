import frappe
from frappe import _
from frappe.model.document import Document


class SGPOrientationSession(Document):
    pass


@frappe.whitelist()
def record_orientation_attendance(
    lead,
    orientation_session,
    joined_at,
    left_at
):
    if not frappe.db.exists("SGP Lead", lead):
        frappe.throw(_("Invalid Lead"))
    if not frappe.db.exists("SGP Orientation Session", orientation_session):
        frappe.throw(_("Invalid Orientation Session"))
    attendance = frappe.get_doc({
        "doctype": "SGP Orientation Attendance",
        "lead": lead,
        "orientation_session": orientation_session,
        "joined_at": joined_at,
        "left_at": left_at
    })
    attendance.insert(ignore_permissions=True)
    frappe.db.commit()
    return {
        "status": "success",
        "attendance": attendance.name
    }
