// SGP Orientation Session — Client Script

const FASTAPI_BASE = "http://122.175.42.237:8001/api/v1";

frappe.ui.form.on("SGP Orientation Session", {

  refresh(frm) {

    // ── Join as Host ───────────────────────────────────────────────────────
    if (frm.doc.room_name) {
      frm.add_custom_button("🩺 Join as Host", () => {
        const hostUrl = `http://122.175.42.237:8001/meet/host.html?session=${frm.doc.room_name}&name=${encodeURIComponent(frappe.session.user)}`;
        window.open(hostUrl, "_blank");
      }, "Actions");
    }

    // ── Schedule & Notify Leads ────────────────────────────────────────────
    frm.add_custom_button("📋 Schedule & Notify Leads", () => {
      _openLeadPickerDialog(frm);
    }, "Actions");

    // ── Copy Patient Join Link ─────────────────────────────────────────────
    if (frm.doc.room_name) {
      frm.add_custom_button("🔗 Copy Patient Join Link", () => {
        const link = `http://122.175.42.237:8001/meet/index.html?session=${frm.doc.room_name}`;
        navigator.clipboard.writeText(link);
        frappe.show_alert({ message: "Join link copied!", indicator: "green" });
      }, "Actions");
    }

    // ── Session info panel ─────────────────────────────────────────────────
    if (frm.doc.room_name) {
      frm.set_intro(
        `<b>Session ID:</b> ${frm.doc.room_name}<br>
         <b>Patient Join:</b> http://122.175.42.237/:8001/meet/index.html?session=${frm.doc.room_name}<br>
         <b>Host Join:</b> http://122.175.42.237:8001/meet/host.html?session=${frm.doc.room_name}`,
        "blue"
      );
    }
  },
});


// ── Lead Picker Dialog ────────────────────────────────────────────────────────
async function _openLeadPickerDialog(frm) {
  frappe.show_progress("Loading leads…", 30, 100);

  let leads = [];
  try {
    const res = await fetch(`${FASTAPI_BASE}/leads?limit=200`);
    if (!res.ok) throw new Error("Failed to fetch leads");
    const all = await res.json();
    // Filter eligible statuses
    leads = all.filter(l => ["NEW", "WEBSITE", "WALK_IN", "REFERRAL", "REORIENTATION_REQUIRED"].includes(l.status));
  } catch (e) {
    frappe.hide_progress();
    frappe.msgprint({ title: "Error", message: `Could not load leads: ${e.message}`, indicator: "red" });
    return;
  }
  frappe.hide_progress();

  if (!leads.length) {
    frappe.msgprint({ title: "No Leads", message: "No eligible leads found.", indicator: "orange" });
    return;
  }

  const rows = leads.map(l => `
    <div class="lead-row" style="padding:6px 0; border-bottom:1px solid #f0f0f0; display:flex; align-items:center; gap:10px;">
      <input type="checkbox" id="lead_${l.id}" value="${l.id}" data-name="${l.name}" data-phone="${l.phone || ''}">
      <label for="lead_${l.id}" style="cursor:pointer; flex:1;">
        <strong>${l.name}</strong>
        <span style="color:#888; font-size:12px; margin-left:8px;">${l.phone || 'No phone'}</span>
        <span style="color:#aaa; font-size:11px; margin-left:8px;">${l.id}</span>
        <span style="color:#aaa; font-size:11px; margin-left:8px;">[${l.status}]</span>
      </label>
    </div>`).join("");

  const d = new frappe.ui.Dialog({
    title: "Schedule Orientation & Notify Leads",
    size: "large",
    fields: [
      {
        fieldtype: "HTML",
        options: `
          <div style="margin-bottom:12px;">
            <button class="btn btn-xs btn-default" onclick="document.querySelectorAll('.lead-row input').forEach(c => c.checked = true)">Select All</button>
            <button class="btn btn-xs btn-default" style="margin-left:6px;" onclick="document.querySelectorAll('.lead-row input').forEach(c => c.checked = false)">Clear</button>
            <span style="color:#888; font-size:12px; margin-left:12px;">${leads.length} eligible leads</span>
          </div>
          <div style="max-height:350px; overflow-y:auto; border:1px solid #eee; padding:8px; border-radius:4px;">
            ${rows}
          </div>
        `,
      },
    ],
    primary_action_label: "📱 Create Session & Send WhatsApp",
    primary_action: async () => {
      const selected = [...document.querySelectorAll(".lead-row input:checked")].map(c => c.value);
      if (!selected.length) {
        frappe.show_alert({ message: "Please select at least one lead.", indicator: "orange" });
        return;
      }
      d.hide();
      await _createSessionAndNotify(frm, selected);
    },
  });

  d.show();
}


// ── Create Session + Notify ───────────────────────────────────────────────────
async function _createSessionAndNotify(frm, leadIds) {
  frappe.show_progress("Creating orientation room…", 20, 100);

  try {
    if (frm.is_dirty()) await frm.save();

    const title       = frm.doc.session_title || frm.doc.name;
    const scheduledAt = frm.doc.orientation_date && frm.doc.start_time
      ? `${frm.doc.orientation_date}T${frm.doc.start_time}` : null;

    // 1. Create session in FastAPI
    const sessionRes = await fetch(`${FASTAPI_BASE}/orientation/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, scheduled_at: scheduledAt, lead_ids: leadIds }),
    });
    if (!sessionRes.ok) {
      const err = await sessionRes.json();
      throw new Error(err.detail || "Session creation failed");
    }
    const session = await sessionRes.json();

    frappe.show_progress("Sending WhatsApp notifications…", 60, 100);

    // 2. Update ERPNext doc with session ID
    await frm.set_value("room_name", session.id);
    await frm.set_value("status", "Scheduled");
    await frm.save();

    // 3. Send WhatsApp
    const waRes = await fetch(`${FASTAPI_BASE}/whatsapp/notify-orientation`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id:    session.id,
        session_title: title,
        scheduled_at:  scheduledAt,
        lead_ids:      leadIds,
      }),
    });

    frappe.hide_progress();

    const waData = waRes.ok ? await waRes.json() : null;
    frappe.show_alert({
      message: waData
        ? `✅ Session created & WhatsApp sent to ${waData.sent}/${leadIds.length} leads!`
        : `✅ Room created (${session.id}) but WhatsApp failed. Send manually.`,
      indicator: waData ? "green" : "orange",
    });

    frm.refresh();

  } catch (e) {
    frappe.hide_progress();
    frappe.msgprint({ title: "Error", message: e.message, indicator: "red" });
  }
}