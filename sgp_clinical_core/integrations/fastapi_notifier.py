"""
FastAPI Notifier — sgp_clinical_core/integrations/fastapi_notifier.py
───────────────────────────────────────────────────────────────────────
ERPNext → FastAPI notification layer.

Location on Frappe server:
  /apps/sgp_clinical_core/sgp_clinical_core/integrations/fastapi_notifier.py

This module is called by hooks.py doc_events.
It enqueues background jobs to POST webhook payloads to FastAPI,
so ERPNext save operations are not blocked by HTTP calls.

Notification log:
  Failed calls are stored in SGP Notification Log DocType (see api.py)
  and retried every 5 minutes by the scheduler.

Authentication:
  FastAPI verifies the X-Frappe-Webhook-Signature HMAC-SHA256 header.
  The secret must match ERP_WEBHOOK_SECRET in FastAPI .env.
"""

import hashlib
import hmac
import json
import logging

import frappe
import requests

logger = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

def _get_config() -> dict:
    """
    Read FastAPI integration settings from Frappe Site Config.
    Add these to your site_config.json:
      {
        "fastapi_url":            "https://your-api.com",
        "fastapi_webhook_secret": "your-erp-webhook-secret"
      }
    Or set via: bench --site your-site set-config fastapi_url "https://..."
    """
    return {
        "url":    frappe.conf.get("fastapi_url", "http://localhost:8000"),
        "secret": frappe.conf.get("fastapi_webhook_secret", ""),
    }


def _sign_payload(body: bytes, secret: str) -> str:
    """Generate HMAC-SHA256 signature for the payload body."""
    return hmac.new(
        secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()


def _post_to_fastapi(endpoint: str, payload: dict) -> bool:
    """
    POST a webhook payload to FastAPI.
    Returns True on success, False on failure.
    Stores failures in SGP Notification Log for retry.
    """
    config = _get_config()
    url    = f"{config['url']}{endpoint}"
    body   = json.dumps(payload).encode()
    sig    = _sign_payload(body, config["secret"])

    headers = {
        "Content-Type":                   "application/json",
        "X-Frappe-Webhook-Signature":      sig,
        "X-Source":                        "erpnext",
    }

    try:
        resp = requests.post(url, data=body, headers=headers, timeout=10)
        if resp.status_code in (200, 201):
            logger.info(f"FastAPI notified: POST {endpoint} → {resp.status_code}")
            return True
        else:
            logger.error(f"FastAPI notification failed: {resp.status_code} {resp.text[:200]}")
            _log_failed_notification(endpoint, payload, resp.status_code, resp.text[:500])
            return False
    except Exception as e:
        logger.error(f"FastAPI notification exception: {e}")
        _log_failed_notification(endpoint, payload, 0, str(e))
        return False


def _log_failed_notification(
    endpoint: str, payload: dict, status_code: int, error: str
) -> None:
    """
    Log failed notification to Frappe Error Log.
    No custom DocType needed — frappe.log_error() is always available.
    Check logs in ERPNext: Settings -> Error Log
    """
    try:
        frappe.log_error(
            title="FastAPI Notification Failed",
            message=json.dumps({
                "endpoint":    endpoint,
                "status_code": status_code,
                "error":       error,
                "payload":     payload,
            }, indent=2),
        )
    except Exception as e:
        logger.error(f"Failed to write to Frappe error log: {e}")


# ── Hook handlers ─────────────────────────────────────────────────────────────

def on_lead_insert(doc, method=None):
    """Called by hooks.py after_insert on SGP Lead."""
    frappe.enqueue(
        "sgp_clinical_core.integrations.fastapi_notifier._notify_lead",
        doc_name=doc.name,
        trigger_event="after_insert",
        queue="short",
        now=False,   # async — don't block the save
    )


def on_lead_update(doc, method=None):
    """Called by hooks.py on_update on SGP Lead."""
    frappe.enqueue(
        "sgp_clinical_core.integrations.fastapi_notifier._notify_lead",
        doc_name=doc.name,
        trigger_event="on_update",
        queue="short",
        now=False,
    )


def _notify_lead(doc_name: str, trigger_event: str) -> None:
    """Background job: fetch SGP Lead and POST to FastAPI."""
    try:
        doc = frappe.get_doc("SGP Lead", doc_name)
        # Use as_dict() to avoid hardcoding field names that may differ per installation
        doc_data = doc.as_dict()
        doc_data = {k: str(v) if hasattr(v, 'isoformat') else v
                    for k, v in doc_data.items()
                    if not k.startswith('_')}
        payload = {
            "doctype": "SGP Lead",
            "name":    doc_name,
            "event":   trigger_event,
            "doc":     doc_data,
        }
        _post_to_fastapi("/api/v1/erp/webhook", payload)
    except Exception as e:
        logger.error(f"_notify_lead failed for {doc_name}: {e}")


def on_appointment_insert(doc, method=None):
    """Called after a new Patient Appointment is created."""
    frappe.enqueue(
        "sgp_clinical_core.integrations.fastapi_notifier._notify_appointment",
        doc_name=doc.name,
        trigger_event="after_insert",
        queue="short",
        now=False,
    )


def on_appointment_update(doc, method=None):
    frappe.enqueue(
        "sgp_clinical_core.integrations.fastapi_notifier._notify_appointment",
        doc_name=doc.name,
        trigger_event="on_update",
        queue="short",
        now=False,
    )


def _notify_appointment(doc_name: str, trigger_event: str) -> None:
    try:
        doc = frappe.get_doc("Patient Appointment", doc_name)
        payload = {
            "doctype": "Patient Appointment",
            "name":    doc_name,
            "event":   trigger_event,
            "doc": {
                "name":             doc.name,
                "patient":          doc.patient,
                "practitioner":     doc.practitioner,
                "appointment_date": str(doc.appointment_date),
                "status":           doc.status,
            },
        }
        _post_to_fastapi("/api/v1/erp/webhook", payload)
    except Exception as e:
        logger.error(f"_notify_appointment failed for {doc_name}: {e}")


def on_encounter_update(doc, method=None):
    frappe.enqueue(
        "sgp_clinical_core.integrations.fastapi_notifier._notify_encounter",
        doc_name=doc.name,
        trigger_event="on_update",
        queue="short",
        now=False,
    )


def on_encounter_submit(doc, method=None):
    frappe.enqueue(
        "sgp_clinical_core.integrations.fastapi_notifier._notify_encounter",
        doc_name=doc.name,
        trigger_event="on_submit",
        queue="short",
        now=False,
    )


def _notify_encounter(doc_name: str, trigger_event: str) -> None:
    try:
        doc = frappe.get_doc("SGP Encounter", doc_name)
        payload = {
            "doctype": "SGP Encounter",
            "name":    doc_name,
            "event":   trigger_event,
            "doc": {
                "name":                 doc.name,
                "patient":              doc.patient,
                "status":               doc.status,
                "orientation_verified": doc.orientation_verified,
                "consent_verified":     doc.consent_verified,
            },
        }
        _post_to_fastapi("/api/v1/erp/webhook", payload)
    except Exception as e:
        logger.error(f"_notify_encounter failed for {doc_name}: {e}")


# ── Scheduled: Retry failed notifications ─────────────────────────────────────

def retry_failed_notifications() -> None:
    """
    Scheduled every 5 minutes.
    Currently a no-op placeholder — failures are logged to Frappe Error Log.
    To add retry logic later: create SGP Notification Log DocType and
    restore the full implementation from the architecture document.
    """
    pass


def daily_lead_sync() -> None:
    """
    Scheduled daily.
    Posts a summary count of leads by status to FastAPI.
    Optional — useful for dashboard widgets.
    """
    try:
        counts = {}
        for status in [
            "NEW", "ORIENTATION_SCHEDULED", "ORIENTATION_ATTENDED",
            "APPOINTMENT_SCHEDULED", "CONVERTED", "DORMANT",
        ]:
            counts[status] = frappe.db.count(
                "SGP Lead", filters={"status": status}
            )
        _post_to_fastapi("/api/v1/erp/webhook", {
            "doctype": "SGP Lead",
            "name":    "daily_summary",
            "event":   "daily_sync",
            "doc":     {"lead_counts": counts},
        })
    except Exception as e:
        logger.error(f"daily_lead_sync error: {e}")