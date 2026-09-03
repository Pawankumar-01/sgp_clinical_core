// Copyright (c) 2026, Sai Ganga Panakeia and contributors
// For license information, please see license.txt

// ═══════════════════════════════════════════════════════════════════════════
// SGP Encounter — Client Script
// Populates the "📋 Patient History" tab with a rich timeline of the
// patient's previous encounters so the doctor has full clinical context.
// ═══════════════════════════════════════════════════════════════════════════

frappe.ui.form.on("SGP Encounter", {

    refresh(frm) {
        _inject_history_styles();
        if (frm.doc.patient) {
            _load_patient_history(frm);
        } else {
            _render_placeholder(frm, "Select a patient to load their clinical history.");
        }
    },

    patient(frm) {
        if (frm.doc.patient) {
            _load_patient_history(frm);
        } else {
            _render_placeholder(frm, "Select a patient to load their clinical history.");
        }
    },
});

// ── Data fetching ────────────────────────────────────────────────────────

function _load_patient_history(frm) {
    const wrapper = frm.fields_dict.patient_history_html;
    if (!wrapper) return;

    wrapper.$wrapper.html(
        `<div class="sgp-ph-loading text-center p-4">
            <div class="spinner-border spinner-border-sm text-primary" role="status"></div>
            <span class="ml-2 text-muted">Loading patient history…</span>
        </div>`
    );

    frappe.call({
        method: "sgp_clinical_core.sgp_clinical_core.doctype.sgp_encounter.sgp_encounter.get_patient_history",
        args: {
            patient: frm.doc.patient,
            exclude_encounter: frm.doc.name,
        },
        callback(r) {
            if (r.message && r.message.length > 0) {
                _render_timeline(frm, r.message);
            } else {
                _render_placeholder(frm,
                    `No previous encounters found for <strong>${frm.doc.patient_name || frm.doc.patient}</strong>.`
                );
            }
        },
        error() {
            _render_placeholder(frm, "⚠️ Failed to load patient history. Please refresh.");
        },
    });
}

// ── Placeholder ──────────────────────────────────────────────────────────

function _render_placeholder(frm, message) {
    const wrapper = frm.fields_dict.patient_history_html;
    if (!wrapper) return;
    wrapper.$wrapper.html(
        `<div class="sgp-ph-empty">
            <div class="sgp-ph-empty-icon">📋</div>
            <div class="sgp-ph-empty-text">${message}</div>
        </div>`
    );
}

// ── Timeline renderer ────────────────────────────────────────────────────

function _render_timeline(frm, encounters) {
    const wrapper = frm.fields_dict.patient_history_html;
    if (!wrapper) return;

    const patientLabel = frm.doc.patient_name || frm.doc.patient;
    const countLabel = encounters.length === 1
        ? "1 previous encounter"
        : `${encounters.length} previous encounters`;

    let html = `
        <div class="sgp-ph-container">
            <div class="sgp-ph-header">
                <span class="sgp-ph-header-title">Clinical History for ${frappe.utils.escape_html(patientLabel)}</span>
                <span class="sgp-ph-header-count">${countLabel}</span>
            </div>
            <div class="sgp-ph-timeline">
    `;

    encounters.forEach((enc, idx) => {
        html += _render_encounter_card(enc, idx);
    });

    html += `</div></div>`;
    wrapper.$wrapper.html(html);

    // Wire up collapse toggles
    wrapper.$wrapper.find(".sgp-ph-section-toggle").on("click", function () {
        const $this = $(this);
        const $body = $this.closest(".sgp-ph-section").find(".sgp-ph-section-body");
        const $icon = $this.find(".sgp-ph-chevron");
        $body.slideToggle(200);
        $icon.toggleClass("sgp-ph-chevron-open");
    });

    // Wire up card header collapse (the entire card body)
    wrapper.$wrapper.find(".sgp-ph-card-toggle").on("click", function () {
        const $this = $(this);
        const $body = $this.closest(".sgp-ph-card").find(".sgp-ph-card-body");
        const $icon = $this.find(".sgp-ph-card-chevron");
        $body.slideToggle(250);
        $icon.toggleClass("sgp-ph-chevron-open");
    });
}

function _render_encounter_card(enc, idx) {
    const date = enc.encounter_date
        ? frappe.datetime.str_to_user(enc.encounter_date)
        : "—";
    const statusClass = _status_class(enc.status);
    const doctorLabel = enc.doctor_name || enc.doctor || "—";
    const caseType = enc.case_type || "";
    const isFirst = idx === 0;

    // Build sections — only include non-empty ones
    const sections = [];

    // 1. Chief Complaint & Anamnesis
    const complaints = [];
    if (enc.chief_complaint) complaints.push(_field("Chief Complaint", enc.chief_complaint));
    if (enc.anamnesis) complaints.push(_field("Anamnesis", enc.anamnesis));
    if (complaints.length) sections.push(_section("Presenting Complaints", complaints.join(""), isFirst));

    // 2. Vitals
    const vitals = [];
    if (enc.height_cm) vitals.push(`<span class="sgp-ph-vital"><b>Ht:</b> ${enc.height_cm} cm</span>`);
    if (enc.weight_kg) vitals.push(`<span class="sgp-ph-vital"><b>Wt:</b> ${enc.weight_kg} kg</span>`);
    if (enc.bp) vitals.push(`<span class="sgp-ph-vital"><b>BP:</b> ${enc.bp}</span>`);
    if (enc.pr) vitals.push(`<span class="sgp-ph-vital"><b>PR:</b> ${enc.pr}</span>`);
    if (enc.temp) vitals.push(`<span class="sgp-ph-vital"><b>Temp:</b> ${enc.temp}</span>`);
    if (enc.rr) vitals.push(`<span class="sgp-ph-vital"><b>RR:</b> ${enc.rr}</span>`);
    if (vitals.length) sections.push(_section("Vitals", `<div class="sgp-ph-vitals-row">${vitals.join("")}</div>`, isFirst));

    // 3. Assessment & Diagnosis
    const assess = [];
    if (enc.vpk_dominance) assess.push(_field("VPK Dominance", enc.vpk_dominance));
    if (enc.ayurvedic_diagnosis) assess.push(_field("Ayurvedic Diagnosis", enc.ayurvedic_diagnosis));
    if (enc.allopathic_diagnosis) assess.push(_field("Allopathic Diagnosis", enc.allopathic_diagnosis));
    if (enc.pulse_diagnosis) assess.push(_field("Pulse Diagnosis (Text)", enc.pulse_diagnosis));
    if (enc.review_of_systems) assess.push(_field("Review of Systems", enc.review_of_systems));
    if (assess.length) sections.push(_section("Assessment & Diagnosis", assess.join(""), isFirst));

    // 4. Pulse Diagnosis Table
    if (enc.pulse_items && enc.pulse_items.length) {
        let ptable = `<table class="sgp-ph-table">
            <thead><tr><th>System</th><th>Vata</th><th>Pitta</th><th>Kapha</th></tr></thead><tbody>`;
        enc.pulse_items.forEach(p => {
            ptable += `<tr><td>${_esc(p.system)}</td><td>${_esc(p.vata)}</td><td>${_esc(p.pitta)}</td><td>${_esc(p.kapha)}</td></tr>`;
        });
        ptable += `</tbody></table>`;
        sections.push(_section("Nadi Pariksha Grid", ptable, false));
    }

    // 5. Examination
    const exam = [];
    if (enc.general_examination) exam.push(_field("General Examination", enc.general_examination));
    if (enc.systemic_examination) exam.push(_field("Systemic Examination", enc.systemic_examination));
    if (enc.investigation_reports) exam.push(_field("Investigation Reports (Brought)", enc.investigation_reports));
    if (exam.length) sections.push(_section("Examination", exam.join(""), false));

    // 6. Treatment
    const treat = [];
    if (enc.rx_quick_summary) treat.push(_field("Rx Summary", enc.rx_quick_summary));
    if (enc.sgp_rx) treat.push(_field("SGP Supplements (Rx)", enc.sgp_rx));
    if (enc.allopathic_medicines) treat.push(_field("Allopathic Medicines", enc.allopathic_medicines));
    if (enc.panchakarma) treat.push(_field("Panchakarma", enc.panchakarma));
    if (enc.detox_procedures) treat.push(_field("Detox Procedures", enc.detox_procedures));
    if (enc.home_remedies) treat.push(_field("Home Remedies", enc.home_remedies));
    if (enc.investigations_advised) treat.push(_field("Investigations Advised", enc.investigations_advised));
    if (treat.length) sections.push(_section("Treatment & Prescriptions", treat.join(""), isFirst));

    // 7. Supplements Table
    if (enc.supplements && enc.supplements.length) {
        let stable = `<table class="sgp-ph-table">
            <thead><tr><th>Supplement</th><th>Qty</th><th>Freq</th>
            <th>W1</th><th>W2</th><th>W3</th><th>W4</th><th>W5</th><th>W6</th><th>W7</th><th>W8</th>
            </tr></thead><tbody>`;
        enc.supplements.forEach(s => {
            stable += `<tr>
                <td><b>${_esc(s.supplement_name)}</b></td>
                <td>${_esc(s.quantity_mg)}</td>
                <td>${_esc(s.frequency)}</td>
                <td>${_esc(s.w1)}</td><td>${_esc(s.w2)}</td><td>${_esc(s.w3)}</td><td>${_esc(s.w4)}</td>
                <td>${_esc(s.w5)}</td><td>${_esc(s.w6)}</td><td>${_esc(s.w7)}</td><td>${_esc(s.w8)}</td>
            </tr>`;
        });
        stable += `</tbody></table>`;
        sections.push(_section("Supplements (8-Week Matrix)", stable, false));
    }

    // 8. Diet & Lifestyle
    const diet = [];
    if (enc.diet_include) diet.push(_field("Diet — Include", enc.diet_include));
    if (enc.diet_exclude) diet.push(_field("Diet — Exclude", enc.diet_exclude));
    if (enc.exercises_yoga) diet.push(_field("Exercises & Yoga", enc.exercises_yoga));
    if (enc.lifestyle_advice) diet.push(_field("Lifestyle Advice", enc.lifestyle_advice));
    if (enc.oil_applications) diet.push(_field("Oil Applications", enc.oil_applications));
    if (enc.breathing_exercises) diet.push(_field("Breathing Exercises", enc.breathing_exercises));
    if (enc.rx_daily_regimen) diet.push(_field("Daily Regimen", enc.rx_daily_regimen));
    if (diet.length) sections.push(_section("Diet & Lifestyle", diet.join(""), false));

    // 9. History (from the encounter itself)
    const hist = [];
    if (enc.past_medical_history) hist.push(_field("Past Medical History", enc.past_medical_history));
    if (enc.medication_history) hist.push(_field("Medication History", enc.medication_history));
    if (enc.surgical_history) hist.push(_field("Surgical History", enc.surgical_history));
    if (enc.allergies) hist.push(_field("Allergies", enc.allergies));
    if (enc.family_history) hist.push(_field("Family History", enc.family_history));
    if (enc.menstrual_obstetric_history) hist.push(_field("Menstrual/Obstetric History", enc.menstrual_obstetric_history));
    if (hist.length) sections.push(_section("Recorded Patient History", hist.join(""), false));

    // 10. Follow-up
    const followup = [];
    if (enc.follow_up) followup.push(_field("Follow-Up Plan", enc.follow_up));
    if (enc.prognosis) followup.push(_field("Prognosis", enc.prognosis));
    if (enc.followup_doc) followup.push(_field("Follow-Up Doctor", enc.followup_doc));
    if (enc.review_after) followup.push(_field("Review After", enc.review_after));
    if (followup.length) sections.push(_section("Follow-Up & Prognosis", followup.join(""), isFirst));

    return `
        <div class="sgp-ph-card">
            <div class="sgp-ph-card-header sgp-ph-card-toggle">
                <div class="sgp-ph-card-header-left">
                    <span class="sgp-ph-card-chevron sgp-ph-chevron ${isFirst ? 'sgp-ph-chevron-open' : ''}">▶</span>
                    <a class="sgp-ph-enc-link" href="/app/sgp-encounter/${enc.name}" onclick="event.stopPropagation();" target="_blank">${enc.name}</a>
                    <span class="sgp-ph-date">${date}</span>
                    <span class="sgp-ph-badge ${statusClass}">${enc.status || "Draft"}</span>
                    ${caseType ? `<span class="sgp-ph-case-type">${_esc(caseType)}</span>` : ""}
                </div>
                <div class="sgp-ph-card-header-right">
                    <span class="sgp-ph-doctor">👨‍⚕️ ${_esc(doctorLabel)}</span>
                </div>
            </div>
            <div class="sgp-ph-card-body" ${isFirst ? '' : 'style="display:none;"'}>
                ${sections.length ? sections.join("") : '<div class="text-muted p-2">No clinical data recorded in this encounter.</div>'}
            </div>
        </div>
    `;
}

// ── Section builder (collapsible) ────────────────────────────────────────

function _section(title, content, startOpen) {
    return `
        <div class="sgp-ph-section">
            <div class="sgp-ph-section-toggle">
                <span class="sgp-ph-chevron ${startOpen ? 'sgp-ph-chevron-open' : ''}">▶</span>
                <span class="sgp-ph-section-title">${title}</span>
            </div>
            <div class="sgp-ph-section-body" ${startOpen ? '' : 'style="display:none;"'}>
                ${content}
            </div>
        </div>
    `;
}

// ── Field renderer ───────────────────────────────────────────────────────

function _field(label, value) {
    if (!value) return "";
    const escaped = _esc(value);
    return `
        <div class="sgp-ph-field">
            <div class="sgp-ph-field-label">${label}</div>
            <div class="sgp-ph-field-value">${escaped}</div>
        </div>
    `;
}

// ── Helpers ──────────────────────────────────────────────────────────────

function _esc(val) {
    if (val === null || val === undefined) return "";
    return frappe.utils.escape_html(String(val)).replace(/\n/g, "<br>");
}

function _status_class(status) {
    const map = {
        "Draft": "sgp-ph-status-draft",
        "Under Review": "sgp-ph-status-review",
        "Approved": "sgp-ph-status-approved",
        "Closed": "sgp-ph-status-closed",
    };
    return map[status] || "sgp-ph-status-draft";
}

// ── Inject CSS (idempotent) ──────────────────────────────────────────────

function _inject_history_styles() {
    if (document.getElementById("sgp-patient-history-styles")) return;
    const style = document.createElement("style");
    style.id = "sgp-patient-history-styles";
    style.textContent = `
        /* ── Container ─────────────────────────────────── */
        .sgp-ph-container {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            padding: 0;
        }
        .sgp-ph-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 16px;
            background: linear-gradient(135deg, #1b2a4a 0%, #2d4373 100%);
            border-radius: 8px 8px 0 0;
            color: #fff;
            margin-bottom: 0;
        }
        .sgp-ph-header-title {
            font-size: 15px;
            font-weight: 600;
        }
        .sgp-ph-header-count {
            font-size: 12px;
            background: rgba(255,255,255,0.2);
            padding: 3px 10px;
            border-radius: 12px;
        }
        .sgp-ph-timeline {
            border: 1px solid #e2e8f0;
            border-top: none;
            border-radius: 0 0 8px 8px;
            background: #f8fafc;
        }

        /* ── Empty state ──────────────────────────────── */
        .sgp-ph-empty {
            text-align: center;
            padding: 48px 20px;
            color: #94a3b8;
        }
        .sgp-ph-empty-icon { font-size: 40px; margin-bottom: 12px; }
        .sgp-ph-empty-text { font-size: 14px; }

        /* ── Card ─────────────────────────────────────── */
        .sgp-ph-card {
            border-bottom: 1px solid #e2e8f0;
            background: #fff;
        }
        .sgp-ph-card:last-child {
            border-bottom: none;
            border-radius: 0 0 8px 8px;
        }
        .sgp-ph-card:first-child { border-radius: 0; }
        .sgp-ph-card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 16px;
            cursor: pointer;
            background: #fff;
            transition: background 0.15s;
            flex-wrap: wrap;
            gap: 6px;
        }
        .sgp-ph-card-header:hover { background: #f1f5f9; }
        .sgp-ph-card-header-left {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }
        .sgp-ph-card-header-right {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .sgp-ph-enc-link {
            font-weight: 600;
            font-size: 13px;
            color: #2563eb;
            text-decoration: none;
        }
        .sgp-ph-enc-link:hover { text-decoration: underline; }
        .sgp-ph-date {
            font-size: 12px;
            color: #64748b;
        }
        .sgp-ph-doctor {
            font-size: 12px;
            color: #475569;
        }
        .sgp-ph-case-type {
            font-size: 11px;
            color: #6366f1;
            background: #eef2ff;
            padding: 1px 8px;
            border-radius: 10px;
            font-weight: 500;
        }
        .sgp-ph-card-body {
            padding: 0 16px 12px 16px;
        }

        /* ── Status badges ────────────────────────────── */
        .sgp-ph-badge {
            font-size: 11px;
            font-weight: 600;
            padding: 2px 10px;
            border-radius: 10px;
            text-transform: uppercase;
            letter-spacing: 0.3px;
        }
        .sgp-ph-status-draft { background: #fef3c7; color: #92400e; }
        .sgp-ph-status-review { background: #dbeafe; color: #1e40af; }
        .sgp-ph-status-approved { background: #d1fae5; color: #065f46; }
        .sgp-ph-status-closed { background: #e2e8f0; color: #475569; }

        /* ── Chevron ──────────────────────────────────── */
        .sgp-ph-chevron {
            display: inline-block;
            font-size: 10px;
            color: #94a3b8;
            transition: transform 0.2s;
            width: 14px;
            text-align: center;
        }
        .sgp-ph-chevron-open { transform: rotate(90deg); }

        /* ── Section (collapsible) ────────────────────── */
        .sgp-ph-section {
            margin-top: 6px;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            overflow: hidden;
            background: #fff;
        }
        .sgp-ph-section-toggle {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 7px 12px;
            cursor: pointer;
            background: #f8fafc;
            transition: background 0.15s;
        }
        .sgp-ph-section-toggle:hover { background: #f1f5f9; }
        .sgp-ph-section-title {
            font-size: 12px;
            font-weight: 600;
            color: #334155;
            text-transform: uppercase;
            letter-spacing: 0.4px;
        }
        .sgp-ph-section-body {
            padding: 8px 12px;
            border-top: 1px solid #e2e8f0;
        }

        /* ── Field ────────────────────────────────────── */
        .sgp-ph-field {
            margin-bottom: 8px;
        }
        .sgp-ph-field:last-child { margin-bottom: 0; }
        .sgp-ph-field-label {
            font-size: 11px;
            font-weight: 600;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.3px;
            margin-bottom: 2px;
        }
        .sgp-ph-field-value {
            font-size: 13px;
            color: #1e293b;
            line-height: 1.5;
            white-space: pre-line;
        }

        /* ── Vitals row ───────────────────────────────── */
        .sgp-ph-vitals-row {
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
        }
        .sgp-ph-vital {
            font-size: 13px;
            background: #f1f5f9;
            padding: 4px 10px;
            border-radius: 6px;
            color: #334155;
        }

        /* ── Tables ───────────────────────────────────── */
        .sgp-ph-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
        }
        .sgp-ph-table th {
            background: #f1f5f9;
            color: #475569;
            font-weight: 600;
            text-align: left;
            padding: 6px 8px;
            border: 1px solid #e2e8f0;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.3px;
        }
        .sgp-ph-table td {
            padding: 5px 8px;
            border: 1px solid #e2e8f0;
            color: #334155;
        }
        .sgp-ph-table tr:nth-child(even) td { background: #f8fafc; }

        /* ── Loading ──────────────────────────────────── */
        .sgp-ph-loading {
            color: #64748b;
            font-size: 13px;
        }
    `;
    document.head.appendChild(style);
}
