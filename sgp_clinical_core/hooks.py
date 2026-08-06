"""
ERPNext Hooks — sgp_clinical_core/hooks.py
───────────────────────────────────────────
This file belongs inside the ERPNext custom app: sgp_clinical_core

Location on your Frappe server:
  /apps/sgp_clinical_core/sgp_clinical_core/hooks.py

These hooks fire server-side Python inside ERPNext and send webhook
notifications to the FastAPI automation engine when relevant documents change.

HOW TO APPLY:
  1. Copy this content into your existing hooks.py
  2. bench restart
  3. bench --site your-site.com migrate  (if adding new scheduled jobs)

IMPORTANT:
  - doc_events fire synchronously inside ERPNext — keep them fast.
  - The actual HTTP call to FastAPI is done via a background job (enqueue)
    to avoid slowing down the ERPNext save operation.
"""

app_name        = "sgp_clinical_core"
app_title       = "SGP Clinical Core"
app_publisher   = "SGP"
app_description = "Clinical core for SGP hospital automation"
app_email       = "dev@sgp.com"
app_license     = "MIT"

# ── Document Event Hooks ──────────────────────────────────────────────────────
# These trigger the FastAPI notification when ERPNext documents are saved.

doc_events = {

    # SGP Lead: notify FastAPI whenever a lead status changes
    "SGP Lead": {
        "on_update":    "sgp_clinical_core.integrations.fastapi_notifier.on_lead_update",
        "after_insert": "sgp_clinical_core.integrations.fastapi_notifier.on_lead_insert",
    },

    # Patient Appointment: notify FastAPI when a new appointment is booked
    "Patient Appointment": {
        "after_insert": "sgp_clinical_core.integrations.fastapi_notifier.on_appointment_insert",
        "on_update":    "sgp_clinical_core.integrations.fastapi_notifier.on_appointment_update",
    },

    # SGP Encounter: notify FastAPI on status transitions
    "SGP Encounter": {
        "on_update":    "sgp_clinical_core.integrations.fastapi_notifier.on_encounter_update",
        "on_submit":    "sgp_clinical_core.integrations.fastapi_notifier.on_encounter_submit",
    },

    # Patient: auto-generate SGP Lead for direct walk-in registrations
    "Patient": {
        "before_insert": "sgp_clinical_core.integrations.patient_hooks.auto_generate_lead_for_walkin",
    },
}

# ── Scheduled Jobs ────────────────────────────────────────────────────────────
# Runs in the ERPNext background worker (bench worker)

scheduler_events = {
    # Every 5 minutes: retry any failed FastAPI notification calls
    "cron": {
        "*/5 * * * *": [
            "sgp_clinical_core.integrations.fastapi_notifier.retry_failed_notifications",
        ]
    },
    # Daily: sync lead count summary to FastAPI (optional reporting)
    "daily": [
        "sgp_clinical_core.integrations.fastapi_notifier.daily_lead_sync",
    ],
}

# ── Fixtures (auto-export these DocTypes with bench export-fixtures) ──────────
fixtures = [
    {"dt": "Custom Field", "filters": [["dt", "in", [
        "SGP Lead",
        "SGP Orientation Session",
        "SGP Orientation Attendance",
        "SGP Encounter",
        "Patient",
    ]]]},
    {"dt": "Property Setter", "filters": [["doc_type", "in", [
        "SGP Lead",
        "SGP Encounter",
    ]]]},
]
jinja = {
    "methods": [
        "sgp_clinical_core.jinja_helpers.parse_notes_json"
    ]
}
