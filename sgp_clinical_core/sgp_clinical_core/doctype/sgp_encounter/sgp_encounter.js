// SGP Encounter — Client Script
// Loads Patient Clinical History when patient field is set/changed.

frappe.ui.form.on("SGP Encounter", {

    // ── Trigger: patient field set or changed ────────────────────────────────
    patient: function (frm) {
        _load_patient_history(frm);
    },

    // ── Also refresh on form load if patient is already set ─────────────────
    onload: function (frm) {
        if (frm.doc.patient) {
            _load_patient_history(frm);
        }
    },
});

// ── History Loader ───────────────────────────────────────────────────────────

function _load_patient_history(frm) {
    const patient_field = frm.get_field("patient_history_html");
    if (!patient_field) return;

    if (!frm.doc.patient) {
        frm.set_df_property(
            "patient_history_html", "options",
            '<div class="text-muted text-center p-4">' +
            '<span style="font-size:2rem;">📋</span><br>' +
            'Select a patient to load their clinical history.' +
            '</div>'
        );
        frm.refresh_field("patient_history_html");
        return;
    }

    // Show loading state
    frm.set_df_property(
        "patient_history_html", "options",
        '<div class="text-center p-4 text-muted">' +
        '<div class="spinner-border spinner-border-sm me-2" role="status"></div>' +
        ' Loading patient history...' +
        '</div>'
    );
    frm.refresh_field("patient_history_html");

    frappe.call({
        method: "sgp_clinical_core.sgp_clinical_core.doctype.sgp_encounter" +
                ".sgp_encounter.get_patient_encounter_history",
        args: { patient: frm.doc.patient, limit: 5 },
        callback: function (r) {
            const encounters = r.message || [];
            const html = _render_history(encounters, frm.doc.name);
            frm.set_df_property("patient_history_html", "options", html);
            frm.refresh_field("patient_history_html");
        },
        error: function () {
            frm.set_df_property(
                "patient_history_html", "options",
                '<div class="alert alert-warning m-3">' +
                '⚠️ Could not load patient history. Please refresh the page.' +
                '</div>'
            );
            frm.refresh_field("patient_history_html");
        }
    });
}

// ── History Renderer ─────────────────────────────────────────────────────────

function _render_history(encounters, current_name) {
    // Filter out the current encounter (doctor may have just saved this form)
    const past = encounters.filter(e => e.name !== current_name);

    if (!past.length) {
        return (
            '<div class="text-center p-4" style="color:#6c757d;">' +
            '<span style="font-size:2.5rem;">🩺</span><br><br>' +
            '<strong>No previous encounters found for this patient.</strong><br>' +
            '<small>This will be their first recorded encounter.</small>' +
            '</div>'
        );
    }

    const cards = past.map(function (enc, idx) {
        const date   = (enc.encounter_date || "").split(" ")[0] || "—";
        const doctor = enc.doctor || "—";
        const status = enc.status || "—";

        // Vitals row
        const vitals_parts = [];
        if (enc.weight_kg)  vitals_parts.push("Wt " + enc.weight_kg + " kg");
        if (enc.bp)         vitals_parts.push("BP " + enc.bp);
        if (enc.pr)         vitals_parts.push("PR " + enc.pr);
        if (enc.temp)       vitals_parts.push("Temp " + enc.temp);
        const vitals = vitals_parts.length ? vitals_parts.join(" &nbsp;|&nbsp; ") : "—";

        // Anthropometry
        const anthro_parts = [];
        if (enc.wrist_cm) anthro_parts.push("Wrist " + enc.wrist_cm + " cm");
        if (enc.waist_cm) anthro_parts.push("Waist " + enc.waist_cm + " cm");
        if (enc.hip_cm)   anthro_parts.push("Hip " + enc.hip_cm + " cm");
        const anthro = anthro_parts.join(" &nbsp;|&nbsp; ");

        const status_color = {
            "Approved": "#198754",
            "Closed":   "#6c757d",
            "Under Review": "#fd7e14",
            "Draft":    "#0d6efd",
        }[status] || "#6c757d";

        // Encounter link (opens in ERPNext in new tab)
        const enc_link =
            "/app/sgp-encounter/" + encodeURIComponent(enc.name);

        return `
<details class="sgp-hist-card mb-2" ${idx === 0 ? "open" : ""}>
  <summary style="
      display:flex; align-items:center; justify-content:space-between;
      padding:10px 14px; cursor:pointer;
      background:#f8f9fa; border-radius:6px;
      border:1px solid #dee2e6; font-size:13px; font-weight:600;">
    <span>
      📅 &nbsp;${date}
      &nbsp;&nbsp;|&nbsp;&nbsp;
      👨‍⚕️ ${doctor}
    </span>
    <span>
      <span style="
          color:white; background:${status_color};
          padding:2px 8px; border-radius:12px; font-size:11px;">
        ${status}
      </span>
      &nbsp;
      <a href="${enc_link}" target="_blank"
         style="font-size:11px; font-weight:400; color:#0d6efd;"
         title="Open encounter">↗ ${enc.name}</a>
    </span>
  </summary>

  <div style="
      padding:12px 14px; border:1px solid #dee2e6;
      border-top:none; border-radius:0 0 6px 6px;
      font-size:12.5px; line-height:1.8; background:#fff;">

    ${_row("Chief Complaint", enc.chief_complaint)}
    ${_row("Vitals", vitals)}
    ${anthro ? _row("Anthropometry", anthro) : ""}

    <div style="border-top:1px solid #f0f0f0; margin:8px 0;"></div>
    ${_row("VPK Dominance", enc.vpk_dominance)}
    ${_row("Pulse Diagnosis", enc.pulse_diagnosis)}
    ${_row("Ayurvedic Diagnosis", enc.ayurvedic_diagnosis)}
    ${_row("Allopathic Diagnosis", enc.allopathic_diagnosis)}

    <div style="border-top:1px solid #f0f0f0; margin:8px 0;"></div>
    ${_row("Supplements (Rx)", enc.sgp_rx)}
    ${_row("Panchakarma", enc.panchakarma)}
    ${_row("Detox Procedures", enc.detox_procedures)}
    ${_row("Allopathic Medicines", enc.allopathic_medicines)}

    <div style="border-top:1px solid #f0f0f0; margin:8px 0;"></div>
    ${_row("Diet — Include", enc.diet_include)}
    ${_row("Diet — Exclude", enc.diet_exclude)}
    ${_row("Exercises & Yoga", enc.exercises_yoga)}
    ${_row("Lifestyle Advice", enc.lifestyle_advice)}
    ${_row("Home Remedies", enc.home_remedies)}

    <div style="border-top:1px solid #f0f0f0; margin:8px 0;"></div>
    ${_row("Follow-up Plan", enc.follow_up)}
    ${_row("Review After", enc.review_after)}
    ${_row("Prognosis", enc.prognosis)}
  </div>
</details>`;
    });

    return (
        '<div style="padding:12px 4px;">' +
        '<p style="font-size:12px; color:#6c757d; margin-bottom:10px;">' +
        'Showing last ' + past.length + ' encounter(s) — newest first. ' +
        'Click a row to expand / collapse.' +
        '</p>' +
        cards.join("") +
        '</div>'
    );
}

// Helper: render one labeled row; skip empty values
function _row(label, value) {
    const v = (value || "").toString().trim();
    if (!v || v === "null") return "";
    return (
        '<div><b style="color:#495057;">' + label + ':</b> ' +
        '<span style="white-space:pre-wrap;">' + v + '</span></div>'
    );
}
