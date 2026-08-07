import frappe
from frappe.utils.password import update_password

def run():
    # 1. Grant System Manager to CEO
    ceo_email = "ceo@sgprs.com"
    if frappe.db.exists("User", ceo_email):
        ceo = frappe.get_doc("User", ceo_email)
        ceo.add_roles("System Manager")
        frappe.logger().info(f"Granted System Manager to {ceo_email}")
        print(f"✅ Granted System Manager role to {ceo_email}")
    else:
        print(f"⚠️ User {ceo_email} not found. Please create the user first.")

    # 2. Create Doctor Vinod with permissions
    vinod_email = "vinod@sgprs.com"
    if not frappe.db.exists("User", vinod_email):
        user = frappe.get_doc({
            "doctype": "User",
            "email": vinod_email,
            "first_name": "Dr. Vinod",
            "send_welcome_email": 0,
            "roles": [
                {"role": "SGP Doctor"},
                {"role": "Physician"} # Standard healthcare permissions
            ]
        })
        user.insert(ignore_permissions=True)
        update_password(vinod_email, "Sgp@Vinod2026")
        
        frappe.logger().info(f"Created user {vinod_email}")
        print(f"✅ Created Dr. Vinod ({vinod_email}) with SGP Doctor & Physician roles.")
        print("   Temp Password: Sgp@Vinod2026")
    else:
        print(f"ℹ️ User {vinod_email} already exists.")

    frappe.db.commit()
