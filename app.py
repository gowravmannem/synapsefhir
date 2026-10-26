import json
import time
import pandas as pd
import streamlit as st
from ehr_store import MockEHRStore
from governance import TrajectoryGovernor
from llm import PipelineError
from pipeline import build_pipeline
from scenarios import PATIENTS
from telemetry import ExecutionTelemetry
import ui

st.set_page_config(layout="wide", page_title="SynapseFHIR", initial_sidebar_state="collapsed")

def html(markup: str):
    st.markdown(markup, unsafe_allow_html=True)

SCENARIOS = {
    "Standard referral": False,
    "Record changes mid-run": True,
}

@st.cache_data
def load_bundle(path: str):
    with open(path, "r") as f:
        return json.load(f)

def step_note(node: str, update: dict):
    """Short outcome text and drift flag for one completed node."""
    if node == "fetch_guidelines":
        sources = update.get("guideline_sources", [])
        payer = sum(s.get("kind") == "payer" for s in sources)
        society = "offline fallback" if update.get("guidelines_mocked") else f"{len(sources) - payer} society"
        return f"{society} + {payer} payer", False
    if node == "validate_citations":
        r = update.get("citation_report", {})
        return f'{r.get("citations_valid", 0)}/{r.get("citations_total", 0)} cited', False
    if node == "governance":
        action = update.get("governance_result", {}).get("action", "")
        return {"DRIFT_DETECTED": "drift detected", "VERIFIED": "verified", "HOLD_FOR_REVIEW": "held"}.get(action, action), action != "VERIFIED"
    if node == "reconcile":
        cancelled = sum(o["status"] == "cancelled" for o in update.get("planned_orders", []))
        return f"{cancelled} cancelled", False
    return None, False

NEXT_NODE = {"ingest": "fast_triage", "fast_triage": "fetch_guidelines", "fetch_guidelines": "deep_synthesis",
             "deep_synthesis": "validate_citations", "validate_citations": "governance", "reconcile": "validate_citations"}

def run_agent(patient_key: str, simulate_drift: bool):
    case = PATIENTS[patient_key]
    store = MockEHRStore(load_bundle(case["bundle"]))
    telemetry = ExecutionTelemetry()
    started_wall, started = time.time(), time.perf_counter()
    if simulate_drift:
        event = case["drift_event"]
        store.schedule_external_write(event["resource"], event["delay_sec"], event["source"])

    timings, final_state, running, last = [], None, "ingest", started
    # Same slot order as the landing view, so Streamlit swaps elements in place instead of leaving stale ones faded
    html(ui.patient_header(store.read_bundle()))
    progress, feed = st.empty(), st.empty()
    progress.markdown(ui.stepper(timings, running, store.events, started_wall), unsafe_allow_html=True)
    feed.markdown(ui.activity_feed(telemetry.step_logs), unsafe_allow_html=True)
    for mode, chunk in build_pipeline().stream({"store": store, "telemetry": telemetry}, stream_mode=["updates", "values"]):
        if mode == "values":
            final_state = chunk
            continue
        for node, update in chunk.items():
            if node.startswith("__"):
                continue
            now = time.perf_counter()
            note, drift = step_note(node, update or {})
            timings.append({"node": node, "sec": now - last, "note": note, "drift": drift})
            last = now
            running = "reconcile" if node == "governance" and drift and note == "drift detected" else NEXT_NODE.get(node)
        progress.markdown(ui.stepper(timings, running, store.events, started_wall), unsafe_allow_html=True)
        feed.markdown(ui.activity_feed(telemetry.step_logs), unsafe_allow_html=True)
    html(ui.footer())

    st.session_state["run"] = {
        "patient": patient_key,
        "state": final_state,
        "store": store,
        "timings": timings,
        "started_wall": started_wall,
        "wall_sec": time.perf_counter() - started,
        "commit": None,
    }

# Global styles and header
html(ui.CSS)
head_left, head_patient, head_mid, head_right = st.columns([1.55, 0.95, 2.0, 0.75], vertical_alignment="center")
with head_left:
    html(ui.brand())
with head_patient:
    patient_key = st.selectbox("Patient", list(PATIENTS), label_visibility="collapsed")
with head_mid:
    scenario = st.segmented_control("Scenario", list(SCENARIOS), default="Standard referral", label_visibility="collapsed")
with head_right:
    run_clicked = st.button("Run agent", type="primary", use_container_width=True)

st.write("")

# Results belong to one patient; switching patients returns to that patient's landing view
if st.session_state.get("run", {}).get("patient") not in (None, patient_key):
    st.session_state.pop("run")

if run_clicked:
    st.session_state.pop("run", None)
    try:
        run_agent(patient_key, SCENARIOS.get(scenario or "Standard referral", False))
    except PipelineError as e:
        st.error(str(e))
    except Exception as e:
        st.error(f"The agent couldn't finish this run. {type(e).__name__}: {e}")
    else:
        st.rerun()

run = st.session_state.get("run")
if not run:
    if not run_clicked:
        html(ui.patient_header(load_bundle(PATIENTS[patient_key]["bundle"])))
        html(ui.stepper([], None, [], 0))
        html(ui.card(
            '<div class="sf-sub" style="color:var(--ink);font-size:14px;line-height:1.6">'
            "SynapseFHIR reads the patient's FHIR record, works out which specialty the referral needs, retrieves that "
            "specialty's referral guideline with Tavily, "
            "and has Nemotron Ultra draft a referral memo in which every statement is checked against a real record. "
            "It then orders only the missing workup, and re-verifies the live chart before anything is committed.</div>"
            '<div class="sf-sub" style="margin-top:10px">Choose <b>Record changes mid-run</b> to watch a new result (a lab or an ECG) '
            "arrive while the agent is working, and see the agent cancel the order that would have duplicated it.</div>",
            label="How it works"))
    html(ui.footer())
    st.stop()

res = run["state"]
html(ui.patient_header(res["raw_bundle"], res))
html(ui.stepper(run["timings"], None, run["store"].events, run["started_wall"]))
html(ui.memo_and_evidence(res))

left, right = st.columns([1, 1], gap="medium")
with left:
    html(ui.checklist(res))
with right:
    html(ui.orders_panel(res, run["commit"]))
    proposed = [o for o in res.get("planned_orders", []) if o["status"] == "proposed"]
    committed = bool(run["commit"] and run["commit"].get("committed"))
    if res["governance_result"].get("action") == "VERIFIED" and proposed and not committed:
        if st.button(f"Approve and place {len(proposed)} order(s)", type="primary", use_container_width=True):
            run["commit"] = TrajectoryGovernor.commit_orders(
                run["store"], res["snapshot"]["hash"], res["planned_orders"], res["triage_result"].get("patient_id"))
            st.rerun()
    elif committed:
        st.caption(f"{run['commit']['message']} The governor re-verified the record hash before writing.")

html(ui.metrics(res["telemetry"], run["wall_sec"]))
st.write("")
with st.expander("Step-by-step telemetry log"):
    log = pd.DataFrame(res["telemetry"].step_logs)
    log["cost_usd"] = log["cost_usd"].map(lambda c: f"${c:.6f}")
    st.dataframe(log[["step", "model", "prompt_tokens", "completion_tokens", "latency_sec", "tokens_per_sec", "cost_usd", "details"]],
                 use_container_width=True, hide_index=True)
html(ui.footer())
