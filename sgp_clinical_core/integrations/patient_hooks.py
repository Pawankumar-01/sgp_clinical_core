# Copyright (c) 2026, Saiganga Intelligence and contributors
# For license information, please see license.txt

import frappe

def auto_generate_lead_for_walkin(doc, method=None):
    """
    Automatic Walk-in Generator Hook (before_insert on Patient).
    If a Patient record is being inserted without a custom_sgp_lead linked,
    this hook automatically generates a successor SGP Lead with WALK_IN status
    and ORIENTATION_ATTENDED so walk-in patients bypass digital orientation constraints.
    """
    # If custom_sgp_lead already has a lead ID (booked via digital app/CRM), bypass and do nothing.
    if doc.get("custom_sgp_lead"):
        return

    try:
        lead_name = doc.get("patient_name") or f"{doc.get('first_name') or ''} {doc.get('last_name') or ''}".strip()
        if not lead_name:
            lead_name = "Walk-in Patient"

        mobile_number = doc.get("mobile") or doc.get("phone") or doc.get("phone_number") or ""
        email = doc.get("email") or doc.get("email_id") or ""

        lead = frappe.get_doc({
            "doctype": "SGP Lead",
            "lead_name": lead_name,
            "mobile_number": mobile_number,
            "email": email,
            "lead_source": "WALK_IN",
            "interested_in": "CONSULTATION",
            "status": "ORIENTATION_ATTENDED",
            "orientation_completed": 1,
            "notes": "Auto-generated lead from direct in-person walk-in Patient registration."
        })
        lead.insert(ignore_permissions=True, ignore_mandatory=True)
        doc.custom_sgp_lead = lead.name
        frappe.logger().info(f"[Walk-in Hook] Auto-generated SGP Lead {lead.name} for direct walk-in patient {lead_name}")
    except Exception as e:
        frappe.logger().error(f"[Walk-in Hook Error] Failed to auto-generate SGP Lead for walk-in patient: {str(e)}")


def ensure_patient_lead_not_mandatory():
    """
    Runs automatically after bench migrate on any server deployment to ensure Patient-custom_sgp_lead is never mandatory in MariaDB.
    """
    if frappe.db.exists("Custom Field", "Patient-custom_sgp_lead"):
        frappe.db.set_value("Custom Field", "Patient-custom_sgp_lead", "reqd", 0)
        frappe.clear_cache(doctype="Patient")
        frappe.logger().info("[after_migrate] Ensured Patient-custom_sgp_lead reqd=0")
