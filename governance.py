import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from ehr_store import MockEHRStore
from fhir_utils import iter_resources, normalize_ref

def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode("utf-8")).hexdigest()

def take_snapshot(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Whole-bundle SHA-256 plus a per-resource hash, so drift can be traced to the exact resources that changed."""
    resources = {r.get("id"): {"type": r.get("resourceType"), "hash": _hash(r)} for r in iter_resources(bundle)}
    return {"hash": _hash(bundle.get("entry", [])), "resources": resources}

def diff_snapshots(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, List[str]]:
    old_r, new_r = old["resources"], new["resources"]
    return {
        "added": sorted(set(new_r) - set(old_r)),
        "removed": sorted(set(old_r) - set(new_r)),
        "modified": sorted(rid for rid in set(old_r) & set(new_r) if old_r[rid]["hash"] != new_r[rid]["hash"]),
    }

class TrajectoryGovernor:
    """Deterministic state verification around every point where the agent acts on the record."""

    @staticmethod
    def check(baseline: Dict[str, Any], live_bundle: Dict[str, Any]) -> Dict[str, Any]:
        live = take_snapshot(live_bundle)
        diff = diff_snapshots(baseline, live)
        return {
            "drift_detected": live["hash"] != baseline["hash"],
            "baseline_hash": baseline["hash"],
            "live_hash": live["hash"],
            "diff": diff,
        }

    @staticmethod
    def apply_reconciliation(orders: List[Dict[str, Any]], audit: List[Dict[str, Any]], decisions: List[Dict[str, Any]],
                             changed_ids: List[str]) -> Dict[str, Any]:
        """Apply the model's KEEP/CANCEL decisions, accepting a CANCEL only when it cites a resource that actually changed."""
        orders, audit = copy.deepcopy(orders), copy.deepcopy(audit)
        by_id = {d["order_id"]: d for d in decisions}
        applied = []
        for order in orders:
            if order["status"] != "proposed":
                continue
            decision = by_id.get(order["order_id"])
            if not decision:
                applied.append({"order_id": order["order_id"], "display": order["display"], "decision": "KEEP",
                                "accepted": True, "rationale": "No decision returned; kept by default."})
                continue
            evidence = normalize_ref(decision.get("evidence_resource_id"))
            if decision["decision"] == "CANCEL" and evidence in changed_ids:
                order["status"] = "cancelled"
                order["cancelled_by"] = evidence
                order["cancel_reason"] = decision["rationale"]
                closes = {c.strip().lower() for c in order.get("addresses_criteria") or [order["addresses_criterion"]]}
                for item in audit:
                    if item.get("criterion", "").strip().lower() in closes:
                        item["status"] = "SATISFIED"
                        item["supporting_resource_id"] = evidence
                        item["clinical_note"] = f"Satisfied by {evidence}, which arrived while the referral was being prepared."
                applied.append({"order_id": order["order_id"], "display": order["display"], "decision": "CANCEL",
                                "evidence": evidence, "accepted": True, "rationale": decision["rationale"]})
            elif decision["decision"] == "CANCEL":
                applied.append({"order_id": order["order_id"], "display": order["display"], "decision": "KEEP",
                                "evidence": evidence, "accepted": False,
                                "rationale": f"Cancel rejected: evidence '{evidence}' isn't one of the changed resources {changed_ids}."})
            else:
                applied.append({"order_id": order["order_id"], "display": order["display"], "decision": "KEEP",
                                "accepted": True, "rationale": decision["rationale"]})
        return {"orders": orders, "audit": audit, "applied": applied}

    @staticmethod
    def commit_orders(store: MockEHRStore, expected_hash: str, orders: List[Dict[str, Any]],
                      patient_id: Optional[str]) -> Dict[str, Any]:
        """Final gate: re-verify the live record, then write the approved orders as FHIR ServiceRequests."""
        live_hash = take_snapshot(store.read_bundle())["hash"]
        if live_hash != expected_hash:
            return {"committed": False, "live_hash": live_hash,
                    "message": "The record changed after the plan was verified. Re-run the agent before committing."}
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        written = []
        for order in orders:
            if order["status"] != "proposed":
                continue
            resource = {
                "resourceType": "ServiceRequest",
                "id": order["order_id"].replace("draft-", ""),
                "status": "active",
                "intent": "order",
                "code": {"text": order["display"]},
                "subject": {"reference": f"Patient/{patient_id}"} if patient_id else None,
                "authoredOn": now,
                "reasonCode": [{"text": order["rationale"]}],
                "note": [{"text": f"Closes guideline gap: {c}"} for c in order.get("addresses_criteria") or [order["addresses_criterion"]]],
            }
            resource = {k: v for k, v in resource.items() if v is not None}
            store.write_resource(resource, source="SynapseFHIR")
            written.append(resource)
        return {"committed": True, "service_requests": written,
                "message": f"{len(written)} ServiceRequest(s) written to the record."}
