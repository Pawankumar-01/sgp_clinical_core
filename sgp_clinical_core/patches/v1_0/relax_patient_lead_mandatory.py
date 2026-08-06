import frappe

def execute():
    """
    Relax mandatory constraint on Patient-custom_sgp_lead so direct walk-ins can be registered without entering an SGP Lead.
    """
    if frappe.db.exists("Custom Field", "Patient-custom_sgp_lead"):
        frappe.db.set_value("Custom Field", "Patient-custom_sgp_lead", "reqd", 0)
        frappe.clear_cache(doctype="Patient")
        frappe.logger().info("[Patch] Relaxed mandatory constraint on Patient-custom_sgp_lead")
