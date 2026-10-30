"""Offline end-to-end tests: a fake Token Factory client drives the real LangGraph pipeline. No API keys or spend."""
import json, os, sys
from types import SimpleNamespace
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)
os.environ["TAVILY_API_KEY"] = ""  # force offline fallback

import llm, pipeline
pipeline.TAVILY_API_KEY = None
from config import MODEL_FAST, MODEL_REASONING
from ehr_store import MockEHRStore
from telemetry import ExecutionTelemetry
from governance import TrajectoryGovernor

ULTRASOUND = {"resourceType": "DiagnosticReport", "id": "diag-ultrasound-999", "status": "final",
              "code": {"text": "Renal Ultrasound"}, "effectiveDateTime": "2026-10-20T21:00:00Z"}

TRIAGE = {"patient_id": "pat-james-01", "suspected_specialty": "Nephrology", "primary_referral_reason": "eGFR 28",
          "pertinent_entities": [{"resource_id": "Observation/obs-egfr-201", "resource_type": "Observation", "clinical_name": "eGFR"}],
          "guideline_search_query": "KDIGO nephrology referral"}
SYNTH = {"specialty": "Nephrology", "urgency_level": "Urgent",
         "patient_summary": [
             {"claim_text": "eGFR 28", "citation_ids": ["Observation/obs-egfr-201"]},
             {"claim_text": "On lisinopril with K 5.3", "citation_ids": ["med-lisinopril-101", "obs-potassium-202"]},
             {"claim_text": "Hallucinated echo", "citation_ids": ["obs-echo-777"]}],
         "guideline_audit": [
             {"criterion": "Recent eGFR", "status": "satisfied", "supporting_resource_id": "obs-egfr-201", "clinical_note": "ok"},
             {"criterion": "Urine ACR", "status": "MISSING", "clinical_note": "none"},
             {"criterion": "Renal ultrasound", "status": "MISSING", "clinical_note": "none"}],
         "contraindications_and_alerts": ["ACEi with hyperkalemia"],
         "generated_service_requests": [
             {"display": "Urine ACR", "addresses_criterion": "Urine ACR", "rationale": "baseline"},
             {"display": "Renal ultrasound", "addresses_criterion": "Renal ultrasound", "rationale": "baseline"}]}
RECON = {"decisions": [{"order_id": "sr-draft-1", "decision": "CANCEL", "evidence_resource_id": "obs-egfr-201", "rationale": "wrong evidence"},
                       {"order_id": "sr-draft-2", "decision": "cancel", "evidence_resource_id": "DiagnosticReport/diag-ultrasound-999", "rationale": "done externally"}],
         "new_alerts": []}

class FakeCompletions:
    def __init__(self, store, drift):
        self.store, self.drift, self.calls = store, drift, []
    def create(self, model, messages, **kw):
        prompt = messages[0]["content"]
        self.calls.append(model)
        if model == MODEL_FAST:
            content = "<think>hmm</think>```json\n" + json.dumps(TRIAGE) + "\n```"
            if len(messages) == 1 and self.calls.count(MODEL_FAST) == 1:
                content = "not json at all"  # force one retry
        elif "reconciliation step" in prompt:
            content = json.dumps(RECON)
        else:
            if self.drift:
                self.store.write_resource(ULTRASOUND, source="Radiology")  # lands mid-run
            content = json.dumps(SYNTH)
        usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=200)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=usage)

def run(drift):
    bundle = json.load(open("sample_bundle.json"))
    store = MockEHRStore(bundle)
    fake = FakeCompletions(store, drift)
    llm._client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    tel = ExecutionTelemetry()
    res = pipeline.build_pipeline().invoke({"store": store, "telemetry": tel})
    return res, store, tel

res, store, tel = run(drift=False)
g = res["governance_result"]
assert g["action"] == "VERIFIED", g
rep = res["citation_report"]
assert rep["citations_valid"] == 3 and rep["rejected_ids"] == ["obs-echo-777"] and rep["claims_unsupported"] == 1, rep
assert res["final_referral"]["patient_summary"][0]["citation_ids"] == ["obs-egfr-201"]
assert [o["status"] for o in res["planned_orders"]] == ["proposed", "proposed"]
assert any("rejected" in s["step"] for s in tel.step_logs), "expected retry log"
print("clean run OK | cost", round(tel.total_cost, 6), "ultra-only", round(tel.ultra_only_cost, 6), "savings %", round(tel.savings_pct, 1))
commit = TrajectoryGovernor.commit_orders(store, res["snapshot"]["hash"], res["planned_orders"], "pat-james-01")
assert commit["committed"] and len(commit["service_requests"]) == 2, commit

res, store, tel = run(drift=True)
g = res["governance_result"]
assert g["action"] == "VERIFIED", g
assert res["reconcile_count"] == 1
statuses = {o["display"]: o["status"] for o in res["planned_orders"]}
assert statuses == {"Urine ACR": "proposed", "Renal ultrasound": "cancelled"}, statuses
decisions = res["reconciliation_log"][0]["decisions"]
assert decisions[0]["accepted"] is False and decisions[0]["decision"] == "KEEP", decisions[0]
audit = {a["criterion"]: a for a in res["final_referral"]["guideline_audit"]}
assert audit["Renal ultrasound"]["status"] == "SATISFIED" and audit["Renal ultrasound"]["supporting_resource_id"] == "diag-ultrasound-999"
print("drift run OK |", g["message"])
print([s["step"] for s in tel.step_logs])

# commit gate rejects if the record changes after verification
store.write_resource({"resourceType": "Observation", "id": "obs-late", "status": "final"}, source="Lab")
assert not TrajectoryGovernor.commit_orders(store, res["snapshot"]["hash"], res["planned_orders"], "x")["committed"]
print("commit gate OK")

# Every demo patient is well formed, and its drift event is a genuinely new resource
from scenarios import PATIENTS
from governance import take_snapshot
for label, case in PATIENTS.items():
    bundle = json.load(open(case["bundle"]))
    ids = [r["resource"]["id"] for r in bundle["entry"]]
    assert len(ids) == len(set(ids)), f"{label}: duplicate resource ids"
    assert any(r["resource"]["resourceType"] == "Patient" for r in bundle["entry"]), f"{label}: no Patient"
    event_id = case["drift_event"]["resource"]["id"]
    assert event_id not in ids, f"{label}: drift event {event_id} already in bundle"
    store = MockEHRStore(bundle)
    before = take_snapshot(store.read_bundle())
    store.write_resource(case["drift_event"]["resource"], source="test")
    check = TrajectoryGovernor.check(before, store.read_bundle())
    assert check["drift_detected"] and check["diff"]["added"] == [event_id], (label, check["diff"])
print("sample patients OK |", ", ".join(PATIENTS))

# The offline fallback follows the specialty triage inferred, never defaulting to nephrology
assert pipeline.fallback_guideline("Cardiology")[0].startswith("Offline ACC/AHA")
assert pipeline.fallback_guideline("Endocrinology")[0].startswith("Offline ADA")
assert pipeline.fallback_guideline("Nephrology")[0].startswith("Offline KDIGO")
assert "No offline guideline" in pipeline.fallback_guideline("Dermatology")[1]
print("specialty fallbacks OK")

# Society and payer searches run separately; payer failure never blocks, and payer sources are tagged
import types
from config import PAYER_DOMAINS
from validation import validate_referral

class FakeTavily:
    fail = set()
    def __init__(self, api_key): pass
    def search(self, query, include_domains, max_results, **kw):
        kind = "payer" if include_domains == PAYER_DOMAINS else "society"
        if kind in FakeTavily.fail:
            raise RuntimeError(f"{kind} search down")
        host = "aetna.com" if kind == "payer" else "kdigo.org"
        return {"results": [{"title": f"{kind} doc {i}", "url": f"https://{host}/{i}", "content": f"{kind} text"} for i in range(max_results)]}

sys.modules["tavily"] = types.SimpleNamespace(TavilyClient=FakeTavily)
pipeline.TAVILY_API_KEY = "fake"
triage_state = {"telemetry": ExecutionTelemetry(), "triage_result": {"suspected_specialty": "Cardiology",
                "guideline_search_query": "society q", "payer_search_query": "payer q", "primary_referral_reason": "chest pain"}}

out = pipeline.node_fetch_guidelines(triage_state)
kinds = [s["kind"] for s in out["guideline_sources"]]
assert kinds.count("society") == 4 and kinds.count("payer") == 3, kinds
assert "payer text" in out["payer_policy_text"] and "payer text" not in out["guidelines_text"]

FakeTavily.fail = {"payer"}
out = pipeline.node_fetch_guidelines(triage_state)
assert not out["guidelines_mocked"] and all(s["kind"] == "society" for s in out["guideline_sources"])
assert out["payer_policy_text"].startswith("No payer clinical policy")

FakeTavily.fail = {"society"}
out = pipeline.node_fetch_guidelines(triage_state)
assert out["guidelines_mocked"] and out["guideline_sources"][0]["title"].startswith("Offline ACC/AHA")
assert sum(s["kind"] == "payer" for s in out["guideline_sources"]) == 3
FakeTavily.fail = set()
pipeline.TAVILY_API_KEY = None
print("payer search OK")

# A PAYER basis without any retrieved payer policy is downgraded to CLINICAL
audit_ref = {"patient_summary": [], "guideline_audit": [
    {"criterion": "ECG", "status": "MISSING", "basis": "PAYER", "clinical_note": "x"},
    {"criterion": "Echo", "status": "MISSING", "basis": "BOTH", "clinical_note": "x"}]}
checked, rep = validate_referral(audit_ref, set(), payer_policy_found=False)
assert [a["basis"] for a in checked["guideline_audit"]] == ["CLINICAL", "CLINICAL"] and rep["payer_basis_rejected"] == 2
checked, rep = validate_referral(audit_ref, set(), payer_policy_found=True)
assert [a["basis"] for a in checked["guideline_audit"]] == ["PAYER", "BOTH"]
print("payer basis guard OK")

# Several ids in one supporting field must all resolve; one bad id downgrades the item
multi = {"patient_summary": [], "guideline_audit": [
    {"criterion": "BP", "status": "SATISFIED", "supporting_resource_id": "obs-sbp-421, Observation/obs-dbp-422", "clinical_note": "x"},
    {"criterion": "BP2", "status": "SATISFIED", "supporting_resource_id": "obs-sbp-421; obs-fake-1", "clinical_note": "x"}]}
checked, rep = validate_referral(multi, {"obs-sbp-421", "obs-dbp-422"})
assert checked["guideline_audit"][0]["status"] == "SATISFIED" and checked["guideline_audit"][0]["supporting_resource_id"] == "obs-sbp-421, obs-dbp-422"
assert checked["guideline_audit"][1]["status"] == "UNVERIFIED" and rep["rejected_ids"] == ["obs-fake-1"], rep
print("multi-id evidence OK")

# Settings lookup: Streamlit secrets (Cloud) win over local config.toml, which wins over env; keys match any case
import settings
real_streamlit = sys.modules.get("streamlit")
try:
    settings._local_toml.cache_clear()
    settings.LOCAL_SECRETS_FILE, saved_path = settings.LOCAL_SECRETS_FILE.with_name("_test_settings.toml"), settings.LOCAL_SECRETS_FILE
    settings.LOCAL_SECRETS_FILE.write_text('nebius_api_key = "from-toml"\ntavily_api_key = "tavily-from-toml"\n')
    os.environ["NEBIUS_BASE_URL"] = "https://env.example/v1/"
    sys.modules["streamlit"] = types.SimpleNamespace(secrets={"NEBIUS_API_KEY": "from-cloud"})
    assert settings.get_setting("NEBIUS_API_KEY") == "from-cloud"
    assert settings.get_setting("tavily_api_key") == "tavily-from-toml"
    assert settings.get_setting("NEBIUS_BASE_URL") == "https://env.example/v1/"
    assert settings.get_setting("MISSING_KEY", "fallback") == "fallback"
finally:
    settings.LOCAL_SECRETS_FILE.unlink(missing_ok=True)
    settings.LOCAL_SECRETS_FILE = saved_path
    settings._local_toml.cache_clear()
    os.environ.pop("NEBIUS_BASE_URL", None)
    if real_streamlit is not None:
        sys.modules["streamlit"] = real_streamlit
    else:
        sys.modules.pop("streamlit", None)
print("settings lookup OK")

# Triage runs Lightning with reasoning off and schema-constrained output; a reasoning-only reply is retried
import llm
from config import MODEL_FAST as FAST_MODEL
from schemas import FastTriageResult as TriageSchema
calls = []
class FakeLightning:
    def create(self, **kw):
        calls.append(kw)
        if len(calls) == 1:  # first reply: budget spent on reasoning, no content
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None), finish_reason="length")],
                                   usage=SimpleNamespace(prompt_tokens=100, completion_tokens=8192))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(TRIAGE)), finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50))
llm._client = SimpleNamespace(chat=SimpleNamespace(completions=FakeLightning()))
tel = ExecutionTelemetry()
out = llm.call_structured(model=FAST_MODEL, prompt="x", schema=TriageSchema, telemetry=tel, step="Triage", details="d", reasoning=False)
assert out.suspected_specialty == "Nephrology" and len(calls) == 2
assert calls[0]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
assert calls[0]["response_format"]["type"] == "json_schema" and calls[0]["response_format"]["json_schema"]["strict"] is True
assert "whole output budget on reasoning" in tel.step_logs[0]["details"]
import inspect
assert "reasoning=False" in inspect.getsource(pipeline.node_fast_triage)
print("lightning triage request OK")
