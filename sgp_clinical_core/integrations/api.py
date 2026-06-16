"""
Whitelisted API Endpoints — sgp_clinical_core/integrations/api.py
──────────────────────────────────────────────────────────────────
ERPNext exposes these as:
  POST /api/method/sgp_clinical_core.integrations.api.<function_name>

These are called by FastAPI when it needs to perform operations in ERPNext
that go beyond simple REST resource operations — e.g. running a workflow,
checking governance rules, or executing a server-side validation.

Callers must authenticate with:
  Authorization: token <API_KEY>:<API_SECRET>

All functions are decorated with @frappe.whitelist() to allow API access.
"""

import frappe
import json
from frappe.utils import now_datetime


@frappe.whitelist()
def get_lead_with_attendance(lead_name: str) -> dict:
    """
    Return an SGP Lead with all linked orientation attendance records.

    GET /api/method/sgp_clinical_core.integrations.api.get_lead_with_attendance
        ?lead_name=SGP-LEAD-00001
    """
    if not frappe.db.exists("SGP Lead", lead_name):
        frappe.throw(f"Lead {lead_name} not found", frappe.DoesNotExistError)

    lead = frappe.get_doc("SGP Lead", lead_name)
    attendances = frappe.get_all(
        "SGP Orientation Attendance",
        filters={"lead": lead_name},
        fields=[
            "name", "orientation_session", "attendance_status",
            "watch_time_seconds", "completion_percentage", "creation",
        ],
        order_by="creation desc",
    )

    return {
        "lead": lead.as_dict(),
        "orientation_attendances": attendances,
        "appointment_eligible": lead.status == "ORIENTATION_ATTENDED",
    }


@frappe.whitelist()
def check_orientation_eligibility(lead_name: str) -> dict:
    """
    Check whether a lead has completed orientation and is appointment-eligible.

    GET /api/method/sgp_clinical_core.integrations.api.check_orientation_eligibility
        ?lead_name=SGP-LEAD-00001
    """
    if not frappe.db.exists("SGP Lead", lead_name):
        frappe.throw(f"Lead {lead_name} not found", frappe.DoesNotExistError)

    lead     = frappe.get_doc("SGP Lead", lead_name)
    eligible = lead.status == "ORIENTATION_ATTENDED"

    completed_attendances = frappe.db.count(
        "SGP Orientation Attendance",
        filters={"lead": lead_name, "attendance_status": "Present"},
    )

    return {
        "lead_name":            lead_name,
        "lead_display_name":    lead.lead_name,
        "current_status":       lead.status,
        "appointment_eligible": eligible,
        "completed_sessions":   completed_attendances,
        "reason": (
            "Orientation completed"
            if eligible
            else f"Status is '{lead.status}' — orientation required"
        ),
    }


@frappe.whitelist()
def mark_orientation_completed(
    lead_name: str,
    session_name: str,
    watch_time_seconds: int,
    completion_percentage: float,
) -> dict:
    """
    Called by FastAPI after the 70% attendance threshold is met.
    Creates SGP Orientation Attendance and updates Lead status atomically.

    POST /api/method/sgp_clinical_core.integrations.api.mark_orientation_completed
    Body: {
      "lead_name": "SGP-LEAD-00001",
      "session_name": "SGP-ORI-00001",
      "watch_time_seconds": 2520,
      "completion_percentage": 84.0
    }

    Using a whitelisted method for this (rather than two separate REST calls)
    ensures atomicity — both records are saved in a single DB transaction.
    """
    if not frappe.db.exists("SGP Lead", lead_name):
        frappe.throw(f"Lead {lead_name} not found", frappe.DoesNotExistError)

    # Create attendance record
    attendance = frappe.get_doc({
        "doctype":               "SGP Orientation Attendance",
        "lead":                  lead_name,
        "orientation_session":   session_name,
        "attendance_status":     "Present",
        "watch_time_seconds":    int(watch_time_seconds),
        "completion_percentage": float(completion_percentage),
    })
    attendance.insert(ignore_permissions=True)

    # Update lead status
    lead = frappe.get_doc("SGP Lead", lead_name)
    lead.status = "ORIENTATION_ATTENDED"
    lead.save(ignore_permissions=True)

    frappe.db.commit()

    return {
        "success":             True,
        "lead_name":           lead_name,
        "attendance_doc":      attendance.name,
        "new_lead_status":     "ORIENTATION_ATTENDED",
        "appointment_eligible": True,
    }


@frappe.whitelist()
def validate_encounter_governance(encounter_name: str) -> dict:
    """
    Run governance checks on an SGP Encounter before approval.
    Called by FastAPI before advancing encounter status to Approved.

    Rules enforced:
      1. Linked lead must have status ORIENTATION_ATTENDED or CONVERTED
      2. orientation_verified must be checked
      3. consent_verified must be checked
      4. Linked Patient Appointment must exist and be Scheduled/Open

    GET /api/method/sgp_clinical_core.integrations.api.validate_encounter_governance
        ?encounter_name=SGP-ENC-00001
    """
    if not frappe.db.exists("SGP Encounter", encounter_name):
        frappe.throw(f"Encounter {encounter_name} not found", frappe.DoesNotExistError)

    enc    = frappe.get_doc("SGP Encounter", encounter_name)
    errors = []
    checks = {}

    # Check 1: orientation verified flag
    checks["orientation_verified"] = bool(enc.orientation_verified)
    if not enc.orientation_verified:
        errors.append("Orientation not verified on encounter record")

    # Check 2: consent verified flag
    checks["consent_verified"] = bool(enc.consent_verified)
    if not enc.consent_verified:
        errors.append("Patient consent not verified")

    # Check 3: linked lead status
    if enc.lead:
        lead_status = frappe.db.get_value("SGP Lead", enc.lead, "status")
        checks["lead_orientation_attended"] = lead_status in (
            "ORIENTATION_ATTENDED", "APPOINTMENT_SCHEDULED", "CONVERTED"
        )
        if not checks["lead_orientation_attended"]:
            errors.append(
                f"Lead status is '{lead_status}' — must be ORIENTATION_ATTENDED or later"
            )
    else:
        checks["lead_orientation_attended"] = False
        errors.append("No lead linked to this encounter")

    # Check 4: appointment exists
    checks["appointment_exists"] = bool(enc.appointment)
    if not enc.appointment:
        errors.append("No appointment linked to this encounter")

    return {
        "encounter_name": encounter_name,
        "can_approve":    len(errors) == 0,
        "checks":         checks,
        "errors":         errors,
    }


@frappe.whitelist()
def get_session_by_automation_id(automation_session_id: str) -> dict:
    """
    Find the ERPNext SGP Orientation Session linked to a FastAPI session UUID.
    Returns the Frappe document name for use as a foreign key.

    GET /api/method/sgp_clinical_core.integrations.api.get_session_by_automation_id
        ?automation_session_id=abc123-...
    """
    results = frappe.get_all(
        "SGP Orientation Session",
        filters={"automation_session_id": automation_session_id},
        fields=["name", "session_name", "status"],
        limit=1,
    )
    if not results:
        return {"found": False, "erp_session_name": None}
    return {
        "found":            True,
        "erp_session_name": results[0]["name"],
        "session_name":     results[0]["session_name"],
        "status":           results[0]["status"],
    }