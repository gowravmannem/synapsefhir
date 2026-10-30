"""HTML builders for the SynapseFHIR dashboard. Every builder returns a single-line string for st.markdown."""
import html
from datetime import date
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from config import MODEL_FAST, MODEL_REASONING
from fhir_utils import iter_resources, resource_date, resource_display, resource_value

CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Source+Serif+4:opsz,wght@8..60,400;8..60,500&family=JetBrains+Mono:wght@400;500&display=swap');
:root{--ink:#18212F;--muted:#5B6676;--faint:#8A94A3;--line:#E3E7ED;--card:#FFFFFF;--page:#F6F7F9;--soft:#EEF1F5;
--accent:#1D5FA8;--accent-bg:#E8F0FA;--ok:#1E7B4F;--ok-bg:#E7F4EC;--warn:#8A5A00;--warn-line:#D99A1E;--warn-bg:#FDF3DC;--bad:#B42318;--bad-bg:#FDECEA;}
.stApp{background:var(--page);}
.stApp, .stApp p, .stApp button, .stApp input{font-family:'Inter',system-ui,sans-serif;}
#MainMenu, footer, [data-testid="stDecoration"], [data-testid="stToolbar"]{visibility:hidden;height:0;}
[data-testid="stHeader"]{background:transparent;}
.block-container{padding-top:1.6rem;padding-bottom:3rem;max-width:1240px;}
.sf-brand{display:flex;align-items:center;gap:12px;}
.sf-logo{width:36px;height:36px;border-radius:10px;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:600;font-size:15px;}
.sf-brand h1{font-size:20px !important;font-weight:600 !important;margin:0 !important;padding:0 !important;color:var(--ink);letter-spacing:-.01em;}
.sf-brand p{margin:0 !important;font-size:12.5px;color:var(--muted);}
.sf-card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin-bottom:14px;}
.sf-label{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--faint);font-weight:600;margin:0 0 12px;}
.sf-row{display:flex;align-items:center;gap:12px;flex-wrap:wrap;}
.sf-pill{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:500;padding:3px 10px;border-radius:999px;white-space:nowrap;}
.ok{background:var(--ok-bg);color:var(--ok);} .warn{background:var(--warn-bg);color:var(--warn);} .bad{background:var(--bad-bg);color:var(--bad);}
.info{background:var(--accent-bg);color:var(--accent);} .neutral{background:var(--soft);color:var(--muted);}
.payer{background:#F1ECFB;color:#5B3FA8;}
.sf-avatar{width:46px;height:46px;border-radius:50%;background:var(--accent-bg);color:var(--accent);display:flex;align-items:center;justify-content:center;font-weight:600;font-size:14px;flex:none;}
.sf-title{font-size:16px;font-weight:600;color:var(--ink);margin:0;}
.sf-sub{font-size:13px;color:var(--muted);margin:2px 0 0;}
.sf-mono{font-family:'JetBrains Mono',monospace;font-size:11.5px;}
.sf-steps{display:flex;gap:10px;flex-wrap:wrap;}
.sf-step{flex:1 1 105px;min-width:105px;border-top:3px solid var(--line);padding-top:8px;}
.sf-step b{display:block;font-size:13px;font-weight:600;color:var(--ink);}
.sf-step span{display:block;font-size:12px;color:var(--muted);}
.sf-step.done{border-color:var(--ok);} .sf-step.drift{border-color:var(--warn-line);} .sf-step.drift span{color:var(--warn);}
.sf-step.run{border-color:var(--accent);animation:sfpulse 1.1s ease-in-out infinite;} .sf-step.pending b{color:var(--faint);}
@keyframes sfpulse{50%{opacity:.45;}}
.sf-event{margin-top:12px;font-size:12.5px;color:var(--warn);background:var(--warn-bg);border-radius:8px;padding:6px 10px;display:inline-block;}
.sf-linked{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(0,1fr);gap:14px;margin-bottom:14px;}
@media (max-width:900px){.sf-linked{grid-template-columns:minmax(0,1fr);}}
.sf-linked .sf-card{margin-bottom:0;}
.sf-memo{font-family:'Source Serif 4',Georgia,serif;font-size:16.5px;line-height:1.75;color:var(--ink);}
.sf-memo p{margin:0 0 10px !important;font-family:inherit !important;font-size:inherit !important;}
.sf-memo .unsupported{text-decoration:underline wavy var(--bad);text-underline-offset:4px;}
.sf-chip{font-family:'JetBrains Mono',monospace;font-size:11px;padding:1px 7px;border-radius:6px;background:var(--accent-bg);color:var(--accent);margin-left:4px;white-space:nowrap;cursor:default;transition:all .12s;}
.sf-chip.rej{background:var(--bad-bg);color:var(--bad);text-decoration:line-through;}
.sf-alert{border-left:3px solid var(--warn-line);background:var(--warn-bg);color:var(--warn);padding:8px 12px;font-size:13px;line-height:1.5;margin-top:8px;}
.sf-ev{display:flex;justify-content:space-between;gap:10px;padding:9px 10px;border:1px solid transparent;border-radius:9px;font-size:13px;cursor:default;transition:all .12s;}
.sf-ev + .sf-ev{margin-top:2px;}
.sf-ev .name{color:var(--ink);font-weight:500;} .sf-ev .meta{color:var(--faint);text-align:right;white-space:nowrap;}
.sf-hint{font-size:12px;color:var(--faint);margin-top:12px;}
.sf-item{display:flex;gap:12px;padding:11px 0;border-top:1px solid var(--line);}
.sf-item:first-of-type{border-top:none;padding-top:2px;}
.sf-icon{width:22px;height:22px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;flex:none;margin-top:1px;}
.sf-item .body{flex:1;min-width:0;} .sf-item .name{font-size:13.5px;font-weight:500;color:var(--ink);}
.sf-item .note{font-size:12.5px;color:var(--muted);line-height:1.45;margin-top:2px;}
.sf-item .name.struck{text-decoration:line-through;color:var(--faint);}
.sf-src{display:flex;justify-content:space-between;gap:10px;font-size:12.5px;padding:5px 0;}
.sf-src a{color:var(--accent);text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.sf-gov{display:flex;gap:10px;align-items:flex-start;border-radius:10px;padding:10px 12px;font-size:13px;line-height:1.5;margin-bottom:12px;}
.sf-tl{border-left:2px solid var(--line);margin:4px 0 4px 6px;padding-left:14px;}
.sf-tl div{position:relative;font-size:12.5px;color:var(--muted);padding:3px 0;}
.sf-tl div:before{content:"";position:absolute;left:-20px;top:9px;width:10px;height:10px;border-radius:50%;background:var(--line);}
.sf-tl div.w:before{background:var(--warn-line);} .sf-tl div.g:before{background:var(--ok);}
.sf-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;}
@media (max-width:900px){.sf-metrics{grid-template-columns:repeat(2,minmax(0,1fr));}}
.sf-metric{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;}
.sf-metric .k{font-size:12px;color:var(--muted);} .sf-metric .v{font-size:22px;font-weight:600;color:var(--ink);margin-top:2px;letter-spacing:-.01em;}
.sf-metric .s{font-size:11.5px;color:var(--faint);margin-top:2px;}
.sf-foot{font-size:11.5px;color:var(--faint);text-align:center;margin-top:18px;}
div[data-testid="stExpander"] details{background:var(--card);border:1px solid var(--line);border-radius:12px;}
</style>"""

NODE_META = {
    "ingest": ("Ingest", "SHA-256 snapshot"),
    "fast_triage": ("Triage", "Nemotron Lightning"),
    "fetch_guidelines": ("Guidelines", "Tavily search"),
    "deep_synthesis": ("Synthesis", "Nemotron Ultra"),
    "validate_citations": ("Validate", "Citation check"),
    "governance": ("Governance", "Hash verify"),
    "reconcile": ("Reconcile", "Nemotron Ultra"),
}
BASE_PATH = ["ingest", "fast_triage", "fetch_guidelines", "deep_synthesis", "validate_citations", "governance"]

def esc(value: Any) -> str:
    return html.escape(str(value)) if value is not None else ""

def css_attr(value: str) -> str:
    return "".join(ch for ch in str(value) if ch.isalnum() or ch in "-_.")

def card(inner: str, label: Optional[str] = None, extra_class: str = "") -> str:
    head = f'<div class="sf-label">{esc(label)}</div>' if label else ""
    return f'<div class="sf-card {extra_class}">{head}{inner}</div>'

def pill(text: str, tone: str) -> str:
    return f'<span class="sf-pill {tone}">{esc(text)}</span>'

def brand() -> str:
    return ('<div class="sf-brand"><div class="sf-logo">S</div><div><h1>SynapseFHIR</h1>'
            '<p>Verifiable referral workups on Nebius Token Factory with NVIDIA Nemotron and Tavily</p></div></div>')

def _patient(bundle: Dict[str, Any]) -> Dict[str, Any]:
    return next((r for r in iter_resources(bundle) if r.get("resourceType") == "Patient"), {})

def _age(birth: Optional[str]) -> Optional[int]:
    try:
        b = date.fromisoformat(birth[:10])
    except (TypeError, ValueError):
        return None
    today = date.today()
    return today.year - b.year - ((today.month, today.day) < (b.month, b.day))

def patient_header(bundle: Dict[str, Any], res: Optional[Dict[str, Any]] = None) -> str:
    patient = _patient(bundle)
    age = _age(patient.get("birthDate"))
    sex = (patient.get("gender") or "").capitalize()
    avatar = f"{age if age is not None else ''}{sex[:1]}" or "P"
    triage = (res or {}).get("triage_result", {})
    referral = (res or {}).get("final_referral", {})
    specialty = referral.get("specialty") or triage.get("suspected_specialty")
    sub = " · ".join(x for x in [sex, f"{age} years" if age is not None else None,
                                  f"Referral to {specialty}" if specialty else "Awaiting triage"] if x)
    reason = triage.get("primary_referral_reason")

    badges = []
    if res:
        urgency = (referral.get("urgency_level") or "").strip()
        if urgency:
            badges.append(pill(urgency, "bad" if urgency.lower() in ("urgent", "stat") else "neutral"))
        report = res.get("citation_report") or {}
        if report:
            if report.get("all_verified"):
                badges.append(pill(f"{report['citations_valid']}/{report['citations_total']} citations verified", "ok"))
            else:
                badges.append(pill(f"{report['claims_verified']}/{report['claims_total']} claims verified", "warn"))
        if res.get("guidelines_mocked"):
            badges.append(pill("Offline guideline fallback", "warn"))
        else:
            sources = res.get("guideline_sources", [])
            payer = sum(s.get("kind") == "payer" for s in sources)
            badges.append(pill(f"{len(sources) - payer} guideline sources", "info"))
        if res.get("guideline_sources"):
            payer = sum(s.get("kind") == "payer" for s in res["guideline_sources"])
            badges.append(pill(f"{payer} payer policies" if payer else "No payer policy found", "payer" if payer else "neutral"))

    reason_html = f'<div class="sf-sub" style="margin-top:6px;color:var(--ink)">{esc(reason)}</div>' if reason else ""
    return card(
        f'<div class="sf-row"><div class="sf-avatar">{esc(avatar)}</div>'
        f'<div style="flex:1;min-width:220px"><div class="sf-title">Patient <span class="sf-mono">{esc(patient.get("id", "unknown"))}</span></div>'
        f'<div class="sf-sub">{esc(sub)}</div>{reason_html}</div>'
        f'<div class="sf-row" style="gap:8px">{"".join(badges)}</div></div>'
    )

def _step_note(entry: Dict[str, Any]) -> str:
    note = entry.get("note")
    return f'{entry["sec"]:.1f}s · {note}' if note else f'{entry["sec"]:.1f}s'

def stepper(timings: List[Dict[str, Any]], running: Optional[str], events: List[Dict[str, Any]], started_wall: float) -> str:
    cells = []
    for entry in timings:
        title, model = NODE_META.get(entry["node"], (entry["node"], ""))
        tone = "drift" if entry.get("drift") else "done"
        cells.append(f'<div class="sf-step {tone}"><b>{esc(title)}</b><span>{esc(model)}</span><span>{esc(_step_note(entry))}</span></div>')
    if running:
        title, model = NODE_META.get(running, (running, ""))
        cells.append(f'<div class="sf-step run"><b>{esc(title)}</b><span>{esc(model)}</span><span>Running…</span></div>')
    seen = {t["node"] for t in timings} | ({running} if running else set())
    if "governance" not in {t["node"] for t in timings}:
        for node in BASE_PATH:
            if node not in seen:
                title, model = NODE_META[node]
                cells.append(f'<div class="sf-step pending"><b>{esc(title)}</b><span>{esc(model)}</span><span>Waiting</span></div>')
    external = [e for e in events if e["source"] != "SynapseFHIR"]
    event_html = "".join(
        f'<div class="sf-event">{esc(e["resource"])} filed by {esc(e["source"])} at +{e["time"] - started_wall:.1f}s, while the agent was mid-run</div>'
        for e in external)
    return card(f'<div class="sf-steps">{"".join(cells)}</div>{event_html}', label="Agent trajectory")

def activity_feed(step_logs: List[Dict[str, Any]]) -> str:
    if not step_logs:
        return card('<div class="sf-sub">Reading the patient record…</div>', label="Live activity")
    rows = "".join(
        f'<div class="sf-src"><span><b style="font-weight:500;color:var(--ink)">{esc(s["step"])}</b> '
        f'<span style="color:var(--muted)">{esc(s["details"])}</span></span>'
        f'<span class="sf-mono" style="color:var(--faint)">{esc(s["model"].split("/")[-1])}</span></div>'
        for s in step_logs)
    return card(rows, label="Live activity")

def memo_and_evidence(res: Dict[str, Any]) -> str:
    referral = res["final_referral"]
    bundle = res["raw_bundle"]
    added = {rid for log in res.get("reconciliation_log", []) for rid in log["diff"]["added"]}

    claims = []
    for claim in referral.get("patient_summary", []):
        chips = "".join(f'<span class="sf-chip" data-ref="{css_attr(c)}">{esc(c)}</span>' for c in claim.get("citation_ids", []))
        chips += "".join(f'<span class="sf-chip rej" title="Not found in the record">{esc(c)}</span>' for c in claim.get("rejected_citations", []))
        if claim.get("verification") == "UNSUPPORTED":
            claims.append(f'<p><span class="unsupported">{esc(claim["claim_text"])}</span> {pill("Unsupported", "bad")}{chips}</p>')
        else:
            claims.append(f'<p>{esc(claim["claim_text"])}{chips}</p>')
    alerts = "".join(f'<div class="sf-alert">{esc(a)}</div>' for a in referral.get("contraindications_and_alerts", []))
    memo = card(f'<div class="sf-memo">{"".join(claims)}</div>{alerts}',
                label=f'Referral memo · {referral.get("specialty", "")} · Nemotron 3 Ultra')

    rows, ids = [], []
    for r in iter_resources(bundle):
        rid = r.get("id", "")
        ids.append(rid)
        value = resource_value(r)
        name = esc(resource_display(r)) + (f' <span style="color:var(--muted);font-weight:400">· {esc(value)}</span>' if value else "")
        tag = f' {pill("Arrived mid-run", "warn")}' if rid in added else ""
        meta = f'<span class="sf-mono">{esc(rid)}</span><br>{esc(r.get("resourceType"))} {esc((resource_date(r) or "")[:10])}'
        rows.append(f'<div class="sf-ev" data-ref="{css_attr(rid)}"><div class="name">{name}{tag}</div><div class="meta">{meta}</div></div>')
    evidence = card("".join(rows) + '<div class="sf-hint">Hover a citation or a record to trace one to the other.</div>',
                    label=f"FHIR evidence · {len(rows)} resources")

    # Bidirectional highlight: hovering a chip lights its record, hovering a record lights every chip citing it
    rules = "".join(
        f'.sf-linked:has([data-ref="{css_attr(i)}"]:hover) .sf-ev[data-ref="{css_attr(i)}"]{{background:var(--accent-bg);border-color:var(--accent);}}'
        f'.sf-linked:has([data-ref="{css_attr(i)}"]:hover) .sf-chip[data-ref="{css_attr(i)}"]{{background:var(--accent);color:#fff;}}'
        for i in ids if i)
    return f'<style>{rules}</style><div class="sf-linked">{memo}{evidence}</div>'

STATUS_STYLE = {
    "SATISFIED": ("ok", "✓", "Satisfied"),
    "MISSING": ("bad", "✕", "Missing"),
    "OUTDATED": ("warn", "!", "Outdated"),
    "UNVERIFIED": ("warn", "?", "Unverified"),
}

def checklist(res: Dict[str, Any]) -> str:
    added = {rid for log in res.get("reconciliation_log", []) for rid in log["diff"]["added"]}
    items = []
    for item in res["final_referral"].get("guideline_audit", []):
        tone, icon, label = STATUS_STYLE.get(item.get("status"), ("neutral", "·", item.get("status", "")))
        support = item.get("supporting_resource_id")
        chip = f'<span class="sf-chip">{esc(support)}</span>' if support else ""
        mid = f' {pill("Arrived mid-run", "warn")}' if support in added else ""
        basis = {"PAYER": f' {pill("Payer requirement", "payer")}',
                 "BOTH": f' {pill("Clinical and payer", "payer")}'}.get(item.get("basis"), "")
        items.append(
            f'<div class="sf-item"><div class="sf-icon {tone}">{icon}</div><div class="body">'
            f'<div class="name">{esc(item.get("criterion"))}{chip}{mid}{basis}</div><div class="note">{esc(item.get("clinical_note"))}</div></div>'
            f'<div>{pill(label, tone)}</div></div>')

    def source_rows(kind: str) -> str:
        rows = []
        for s in res.get("guideline_sources", []):
            if s.get("kind", "society") != kind:
                continue
            url = s.get("url") or ""
            domain = urlparse(url).netloc.replace("www.", "") if url else "offline"
            link = f'<a href="{esc(url)}" target="_blank">{esc(s.get("title") or url)}</a>' if url else esc(s.get("title"))
            rows.append(f'<div class="sf-src">{link}<span class="sf-mono" style="color:var(--faint)">{esc(domain)}</span></div>')
        return "".join(rows)

    society_rows = source_rows("society")
    payer_rows = source_rows("payer") or '<div class="sf-sub">No payer clinical policy was found for this referral.</div>'
    source_block = (f'<div class="sf-label" style="margin-top:16px">Clinical society guidelines · '
                    f'{"offline fallback" if res.get("guidelines_mocked") else "retrieved live by Tavily"}</div>{society_rows}'
                    f'<div class="sf-label" style="margin-top:16px">Payer clinical policies · retrieved live by Tavily</div>{payer_rows}')
    return card("".join(items) + source_block, label="Pre-referral workup checklist")

def orders_panel(res: Dict[str, Any], commit: Optional[Dict[str, Any]]) -> str:
    gov = res.get("governance_result", {})
    action = gov.get("action")
    tone = "ok" if action == "VERIFIED" else "warn"
    banner = (f'<div class="sf-gov {tone}"><b style="white-space:nowrap">{esc(action)}</b>'
              f'<span>{esc(gov.get("message"))}</span></div>')

    placed = {sr["code"]["text"]: sr["id"] for sr in (commit or {}).get("service_requests", [])}
    rows = []
    for order in res.get("planned_orders", []):
        if order["status"] == "cancelled":
            rows.append(
                f'<div class="sf-item"><div class="sf-icon neutral">–</div><div class="body">'
                f'<div class="name struck">{esc(order["display"])}</div>'
                f'<div class="note">Satisfied by <span class="sf-chip">{esc(order.get("cancelled_by"))}</span>, which arrived mid-run. Duplicate order prevented.</div></div>'
                f'<div>{pill("Cancelled", "neutral")}</div></div>')
        else:
            state = pill(f"Placed · {placed[order['display']]}", "ok") if order["display"] in placed else pill("Ready for sign-off", "info")
            rows.append(
                f'<div class="sf-item"><div class="sf-icon info">+</div><div class="body">'
                f'<div class="name">{esc(order["display"])}</div>'
                f'<div class="note">Closes: {esc("; ".join(order.get("addresses_criteria") or [order["addresses_criterion"]]))}</div></div>'
                f'<div>{state}</div></div>')
    if not rows:
        rows.append('<div class="sf-sub">No orders needed. The workup is complete.</div>')

    timeline = ""
    for log in res.get("reconciliation_log", []):
        diff = log["diff"]
        changed = ", ".join(diff["added"] + diff["modified"] + diff["removed"])
        cancelled = [d for d in log["decisions"] if d["decision"] == "CANCEL"]
        rejected = [d for d in log["decisions"] if not d.get("accepted", True)]
        kept = len(log["decisions"]) - len(cancelled)
        lines = [
            f'<div>Plan built on record <span class="sf-mono">{esc(log["from_hash"][:12])}</span></div>',
            f'<div class="w">Record changed mid-run: {esc(changed)} → <span class="sf-mono">{esc(log["to_hash"][:12])}</span></div>',
            f'<div class="w">Ultra re-planned over the delta only: {len(cancelled)} cancelled, {kept} kept</div>',
        ]
        lines += [f'<div class="w">Governor rejected an unsupported cancel of {esc(d["display"])}</div>' for d in rejected]
        lines.append('<div class="g">Governor re-verified the live record</div>')
        timeline += f'<div class="sf-label" style="margin-top:16px">Drift reconciliation</div><div class="sf-tl">{"".join(lines)}</div>'

    commit_html = ""
    if commit and not commit.get("committed"):
        commit_html = f'<div class="sf-gov warn" style="margin-top:12px">{esc(commit["message"])}</div>'
    return card(banner + "".join(rows) + timeline + commit_html, label="Orders and governance")

def metrics(telemetry, wall_sec: float) -> str:
    def rate(model_id: str) -> str:
        speeds = [s["tokens_per_sec"] for s in telemetry.step_logs if s["model"] == model_id and s["tokens_per_sec"]]
        return f"{sum(speeds) / len(speeds):.0f} tok/s" if speeds else "n/a"
    cells = [
        ("Run cost", f"${telemetry.total_cost:.4f}", "Per-model Token Factory pricing"),
        ("Saved vs Ultra-only", f"{telemetry.savings_pct:.0f}%", f"Same tokens at Ultra rates: ${telemetry.ultra_only_cost:.4f}"),
        ("Wall time", f"{wall_sec:.1f}s", f"Lightning {rate(MODEL_FAST)} · Ultra {rate(MODEL_REASONING)}"),
        ("Tokens", f"{telemetry.total_tokens:,}", f"{telemetry.prompt_tokens:,} prompt · {telemetry.completion_tokens:,} completion"),
    ]
    inner = "".join(f'<div class="sf-metric"><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div><div class="s">{esc(s)}</div></div>'
                    for k, v, s in cells)
    return f'<div class="sf-label" style="margin-top:6px">Nebius Token Factory telemetry</div><div class="sf-metrics">{inner}</div>'

def footer() -> str:
    return '<div class="sf-foot">Synthetic patient data. Decision support for clinicians, not medical advice.</div>'
