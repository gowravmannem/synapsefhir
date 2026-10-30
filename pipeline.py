import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TypedDict, Dict, Any, List
from langgraph.graph import StateGraph, END

from config import (MODEL_FAST, MODEL_REASONING, SOCIETY_DOMAINS, PAYER_DOMAINS, SOCIETY_MAX_RESULTS,
                    PAYER_MAX_RESULTS, PAYER_EXCLUDE_DOMAINS, MAX_RECONCILIATIONS)
from ehr_store import MockEHRStore
from fhir_utils import iter_resources, resource_index
from governance import TrajectoryGovernor, take_snapshot
from llm import call_structured
from schemas import FastTriageResult, FinalReferralPackage, ReconciliationResult
from telemetry import ExecutionTelemetry
from settings import get_setting
from validation import validate_referral

TAVILY_API_KEY = get_setting("TAVILY_API_KEY")

# Offline summaries used only when Tavily is unavailable, picked by the specialty triage inferred
FALLBACK_GUIDELINES = {
    "nephro": ("Offline KDIGO summary",
               "KDIGO Guidelines: Refer to Nephrology if eGFR < 30 mL/min/1.73m2, or rapid decline. "
               "Mandatory baseline tests: Complete Metabolic Panel within 3 months, Urine Albumin-to-Creatinine "
               "Ratio (uACR), and Renal Ultrasound imaging."),
    "cardio": ("Offline ACC/AHA summary",
               "ACC/AHA chest pain and hypertension guidance: obtain a resting 12-lead ECG in patients presenting with "
               "chest pain. Baseline workup before cardiology evaluation: 12-lead ECG, lipid panel, basic metabolic panel "
               "(potassium, creatinine); consider echocardiography when hypertension is uncontrolled or LVH is suspected."),
    "endo": ("Offline ADA Standards of Care summary",
             "ADA Standards of Care: measure HbA1c at least twice yearly, and quarterly when not at goal. Baseline workup "
             "before endocrinology referral: recent HbA1c, fasting glucose, lipid panel, renal function (eGFR) and urine "
             "albumin-to-creatinine ratio."),
}

def fallback_guideline(specialty: str):
    key = next((k for k in FALLBACK_GUIDELINES if k in (specialty or "").lower()), None)
    if key:
        return FALLBACK_GUIDELINES[key]
    return ("Offline generic summary",
            "No offline guideline is stored for this specialty. Audit only the baseline labs and imaging a specialist "
            "would routinely expect for the referral indication, and say so in each clinical_note.")

class PipelineState(TypedDict, total=False):
    store: MockEHRStore
    telemetry: ExecutionTelemetry
    raw_bundle: Dict[str, Any]
    snapshot: Dict[str, Any]
    triage_result: Dict[str, Any]
    guidelines_text: str
    payer_policy_text: str
    guideline_sources: List[Dict[str, str]]
    guidelines_mocked: bool
    final_referral: Dict[str, Any]
    planned_orders: List[Dict[str, Any]]
    citation_report: Dict[str, Any]
    governance_result: Dict[str, Any]
    reconciliation_log: List[Dict[str, Any]]
    reconcile_count: int

# NODE 0: Ingestion & Deterministic Hashing
def node_ingest(state: PipelineState) -> Dict[str, Any]:
    started = time.perf_counter()
    bundle = state["store"].read_bundle()
    snapshot = take_snapshot(bundle)
    state["telemetry"].record_step("Ingest & Hash", "deterministic", None, time.perf_counter() - started,
                                   f"{len(snapshot['resources'])} resources, SHA-256 {snapshot['hash'][:12]}")
    return {"raw_bundle": bundle, "snapshot": snapshot, "reconcile_count": 0, "reconciliation_log": []}

# NODE 1: Fast Entity Extraction & Triage (Nemotron 3.5 Lightning, reasoning off)
def node_fast_triage(state: PipelineState) -> Dict[str, Any]:
    prompt = f"""You are a high-throughput clinical parser.
Analyze this FHIR R4 JSON bundle:
1. Identify the patient ID and the target specialist discipline (e.g., Nephrology, Cardiology). If the bundle contains a referral ServiceRequest, use the specialty it requests and its reason as the referral indication. Otherwise, route to the specialty that manages the primary active problem that is uncontrolled or progressing despite current treatment, not to a secondary risk factor.
2. Formulate a specific search query for the society guideline's referral criteria and the diagnostic workup (labs and imaging) that should be completed before referral to that specialty. Build it from the specialty and the referral indication only; do not guess at specific tests, name medications, or add ages, values or conditions the record doesn't show. Keep it under 15 words.
3. Formulate a second query, 'payer_search_query', for insurer clinical policy or medical-necessity criteria covering this referral and its diagnostic workup (as published in payer coverage policies). Same rules: specialty and referral indication only, under 15 words.
4. Extract relevant active conditions, labs, imaging, and medications. Use each resource's bare "id" value exactly as written.

Output one JSON object that fills in this schema (do not repeat the schema itself):
{json.dumps(FastTriageResult.model_json_schema())}

FHIR BUNDLE:
{json.dumps(state["raw_bundle"])}
"""
    triage = call_structured(model=MODEL_FAST, prompt=prompt, schema=FastTriageResult, telemetry=state["telemetry"],
                             step="Fast Clinical Triage", details="Extracted clinical entities and queries",
                             reasoning=False)
    return {"triage_result": triage.model_dump()}

def _tavily_search(query: str, domains: List[str], max_results: int, exclude: List[str] = ()) -> List[Dict[str, Any]]:
    from tavily import TavilyClient
    response = TavilyClient(api_key=TAVILY_API_KEY).search(
        query=query, search_depth="advanced", include_domains=domains, exclude_domains=list(exclude),
        max_results=max_results)
    return response.get("results", [])

def _format_results(results: List[Dict[str, Any]]) -> str:
    return "\n\n".join(f"[{r.get('title')}] ({r.get('url')}): {r.get('content')}" for r in results)

# NODE 2: Dynamic Guideline Retrieval (Tavily Search API): society guidelines and payer policies, searched in parallel
def node_fetch_guidelines(state: PipelineState) -> Dict[str, Any]:
    telemetry = state["telemetry"]
    triage = state["triage_result"]
    specialty = triage.get("suspected_specialty", "")
    society_query = triage.get("guideline_search_query") or f"{specialty} referral criteria and pre-referral diagnostic workup guideline"
    payer_query = triage.get("payer_search_query") or f"{specialty} referral {triage.get('primary_referral_reason', '')} medical necessity coverage policy"
    started = time.perf_counter()

    society, payer, reason = [], [], ""
    if TAVILY_API_KEY:
        with ThreadPoolExecutor(max_workers=2) as pool:
            society_job = pool.submit(_tavily_search, society_query, SOCIETY_DOMAINS, SOCIETY_MAX_RESULTS)
            payer_job = pool.submit(_tavily_search, payer_query, PAYER_DOMAINS, PAYER_MAX_RESULTS, PAYER_EXCLUDE_DOMAINS)
            try:
                society = society_job.result()
                reason = "" if society else "Tavily returned no society guidelines"
            except Exception as e:
                reason = f"Tavily error: {e}"
            try:
                payer = payer_job.result()
            except Exception:
                payer = []  # Payer policy is supplementary; its failure never blocks the referral
    else:
        reason = "TAVILY_API_KEY not set"

    payer_text = _format_results(payer) if payer else "No payer clinical policy was retrieved for this referral."
    payer_sources = [{"title": r.get("title", ""), "url": r.get("url", ""), "kind": "payer"} for r in payer]

    if society:
        telemetry.record_step("Tavily Guideline Retrieval", "tavily-search-api", None, time.perf_counter() - started,
                              f"Society: {society_query} ({len(society)}) | Payer: {payer_query} ({len(payer)})")
        return {"guidelines_text": _format_results(society),
                "payer_policy_text": payer_text,
                "guideline_sources": [{"title": r.get("title", ""), "url": r.get("url", ""), "kind": "society"} for r in society] + payer_sources,
                "guidelines_mocked": False}

    # Offline fallback guideline, clearly flagged so the UI never passes it off as live retrieval.
    # There is no offline payer policy: payer requirements are only ever taken from retrieved documents.
    telemetry.record_step("Guideline Retrieval (offline fallback)", "fallback", None,
                          time.perf_counter() - started, f"{reason} | payer sources: {len(payer)}")
    title, text = fallback_guideline(specialty)
    return {"guidelines_text": text,
            "payer_policy_text": payer_text,
            "guideline_sources": [{"title": f"{title} (fallback)", "url": "", "kind": "society"}] + payer_sources,
            "guidelines_mocked": True}

# NODE 3: Deep Clinical Synthesis & Gap Analysis (Nemotron Ultra)
def node_deep_synthesis(state: PipelineState) -> Dict[str, Any]:
    triage = state["triage_result"]
    prompt = f"""You are a clinical referral optimization agent.
Evaluate the patient's record against the specialist clinical guidelines.

EXTRACTED FHIR ENTITIES (from triage):
{json.dumps(triage['pertinent_entities'], indent=2)}

COMPLETE RESOURCE INDEX (id | type | name | value | date) - the only ids you may cite:
{resource_index(state["raw_bundle"])}

SPECIALIST GUIDELINES (clinical societies):
{state["guidelines_text"]}

PAYER CLINICAL POLICIES (insurers):
{state.get("payer_policy_text") or "No payer clinical policy was retrieved for this referral."}

STRICT INSTRUCTIONS:
1. Every claim in 'patient_summary' MUST cite one or more ids from the RESOURCE INDEX in citation_ids (bare id, e.g. "obs-egfr-201"). Never invent ids.
2. In 'guideline_audit', list only the diagnostic labs and imaging the specialist needs before intake for THIS patient's referral indication (not lifestyle, diet, or counseling items). Retrieved guidelines may cover other populations: skip requirements for conditions the record does not show. Retrieved documents may include clinical trials: never treat a study's eligibility or inclusion criteria as a requirement. Mark an item SATISFIED only if the cited resource's value actually meets the criterion. Assess each as SATISFIED, MISSING, or OUTDATED. Check the full RESOURCE INDEX, not just the triage entities. SATISFIED and OUTDATED items must cite the supporting id. Set 'basis' to CLINICAL when the requirement comes from the society guidelines, PAYER when only a retrieved payer policy requires it (e.g. documentation needed for coverage), or BOTH. Never mark PAYER or BOTH unless the PAYER CLINICAL POLICIES text above actually states the requirement.
3. For every MISSING or OUTDATED item, add one diagnostic order to 'generated_service_requests' whose 'addresses_criterion' repeats that item's 'criterion' text exactly.
4. List critical contraindications, drug-lab conflicts, or documentation inconsistencies in 'contraindications_and_alerts'.

Output STRICT JSON matching schema:
{json.dumps(FinalReferralPackage.model_json_schema())}
"""
    package = call_structured(model=MODEL_REASONING, prompt=prompt, schema=FinalReferralPackage, telemetry=state["telemetry"],
                              step="Deep Synthesis & Audit", details="Referral memo, gap audit and draft orders",
                              temperature=0.1)
    referral = package.model_dump()
    # One order per distinct test: a lipid panel that closes three checklist lines is placed once, not three times
    merged: Dict[str, Dict[str, Any]] = {}
    for o in referral.pop("generated_service_requests"):
        key = " ".join(o["display"].lower().split())
        if key in merged:
            merged[key]["addresses_criteria"].append(o["addresses_criterion"])
        else:
            merged[key] = {**o, "addresses_criteria": [o["addresses_criterion"]]}
    orders = [{"order_id": f"sr-draft-{i}", "status": "proposed", **o} for i, o in enumerate(merged.values(), start=1)]
    return {"final_referral": referral, "planned_orders": orders}

# NODE 4: Deterministic Citation Validation
def node_validate_citations(state: PipelineState) -> Dict[str, Any]:
    started = time.perf_counter()
    valid_ids = set(state["snapshot"]["resources"])
    payer_found = any(s.get("kind") == "payer" for s in state.get("guideline_sources", []))
    referral, report = validate_referral(state["final_referral"], valid_ids, payer_policy_found=payer_found)
    state["telemetry"].record_step("Citation Validation", "deterministic", None, time.perf_counter() - started,
                                   f"{report['citations_valid']}/{report['citations_total']} citations resolve; "
                                   f"rejected: {report['rejected_ids'] or 'none'}")
    return {"final_referral": referral, "citation_report": report}

# NODE 5: Trajectory Hash Governance
def node_governance(state: PipelineState) -> Dict[str, Any]:
    started = time.perf_counter()
    check = TrajectoryGovernor.check(state["snapshot"], state["store"].read_bundle())
    reconciled = state.get("reconcile_count", 0)
    active = [o for o in state["planned_orders"] if o["status"] == "proposed"]

    if check["drift_detected"] and reconciled < MAX_RECONCILIATIONS:
        changed = check["diff"]["added"] + check["diff"]["modified"] + check["diff"]["removed"]
        result = {**check, "action": "DRIFT_DETECTED",
                  "message": f"Record changed mid-run ({', '.join(changed)}). Re-planning against the live record."}
    elif check["drift_detected"]:
        result = {**check, "action": "HOLD_FOR_REVIEW",
                  "message": f"Record kept changing after {reconciled} reconciliation(s). Holding all orders for human review."}
    else:
        cancelled = [o for o in state["planned_orders"] if o["status"] == "cancelled"]
        message = f"Live record matches the verified plan (SHA-256 {check['live_hash'][:12]}). {len(active)} order(s) ready for sign-off."
        if cancelled:
            message += f" {len(cancelled)} redundant order(s) cancelled after drift."
        result = {**check, "action": "VERIFIED", "message": message}

    state["telemetry"].record_step("Trajectory Governance", "TrajectoryGovernor", None,
                                   time.perf_counter() - started, f"{result['action']}: {result['message']}")
    return {"governance_result": result}

# NODE 6: Drift Reconciliation (Nemotron Ultra reasons only over the delta)
def node_reconcile(state: PipelineState) -> Dict[str, Any]:
    live_bundle = state["store"].read_bundle()
    live_snapshot = take_snapshot(live_bundle)
    diff = TrajectoryGovernor.check(state["snapshot"], live_bundle)["diff"]
    changed_ids = diff["added"] + diff["modified"]
    changed_resources = [r for r in iter_resources(live_bundle) if r.get("id") in changed_ids]
    active = [{k: o[k] for k in ("order_id", "display", "addresses_criterion")}
              for o in state["planned_orders"] if o["status"] == "proposed"]

    prompt = f"""You are the reconciliation step of a clinical referral agent.
While you were preparing the orders below, the patient's record changed.

PROPOSED ORDERS (not yet placed):
{json.dumps(active, indent=2)}

NEW OR CHANGED FHIR RESOURCES:
{json.dumps(changed_resources, indent=2)}

REMOVED RESOURCE IDS: {diff["removed"] or "none"}

For EVERY proposed order, decide:
- CANCEL if a new or changed resource already provides that result. Set evidence_resource_id to that resource's id.
- KEEP otherwise.
Add any new safety concern raised by the changes to new_alerts.

Output STRICT JSON matching schema:
{json.dumps(ReconciliationResult.model_json_schema())}
"""
    result = call_structured(model=MODEL_REASONING, prompt=prompt, schema=ReconciliationResult, telemetry=state["telemetry"],
                             step="Drift Reconciliation", details=f"Re-planned against {len(changed_ids)} changed resource(s)")
    applied = TrajectoryGovernor.apply_reconciliation(
        state["planned_orders"], state["final_referral"].get("guideline_audit", []),
        [d.model_dump() for d in result.decisions], changed_ids)

    referral = dict(state["final_referral"])
    referral["guideline_audit"] = applied["audit"]
    referral["contraindications_and_alerts"] = list(referral.get("contraindications_and_alerts", [])) + result.new_alerts

    log_entry = {
        "from_hash": state["snapshot"]["hash"],
        "to_hash": live_snapshot["hash"],
        "diff": diff,
        "decisions": applied["applied"],
    }
    return {
        "raw_bundle": live_bundle,
        "snapshot": live_snapshot,
        "final_referral": referral,
        "planned_orders": applied["orders"],
        "reconcile_count": state.get("reconcile_count", 0) + 1,
        "reconciliation_log": state.get("reconciliation_log", []) + [log_entry],
    }

def route_after_governance(state: PipelineState) -> str:
    return "reconcile" if state["governance_result"]["action"] == "DRIFT_DETECTED" else END

# Build LangGraph State Machine
def build_pipeline():
    workflow = StateGraph(PipelineState)
    workflow.add_node("ingest", node_ingest)
    workflow.add_node("fast_triage", node_fast_triage)
    workflow.add_node("fetch_guidelines", node_fetch_guidelines)
    workflow.add_node("deep_synthesis", node_deep_synthesis)
    workflow.add_node("validate_citations", node_validate_citations)
    workflow.add_node("governance", node_governance)
    workflow.add_node("reconcile", node_reconcile)

    workflow.set_entry_point("ingest")
    workflow.add_edge("ingest", "fast_triage")
    workflow.add_edge("fast_triage", "fetch_guidelines")
    workflow.add_edge("fetch_guidelines", "deep_synthesis")
    workflow.add_edge("deep_synthesis", "validate_citations")
    workflow.add_edge("validate_citations", "governance")
    workflow.add_conditional_edges("governance", route_after_governance, {"reconcile": "reconcile", END: END})
    # After reconciling, re-validate citations against the new snapshot and re-check the record
    workflow.add_edge("reconcile", "validate_citations")

    return workflow.compile()
