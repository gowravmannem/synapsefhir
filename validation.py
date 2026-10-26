import copy
import re
from typing import Any, Dict, Set, Tuple
from fhir_utils import normalize_ref

def validate_referral(referral: Dict[str, Any], valid_ids: Set[str],
                      payer_policy_found: bool = True) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Deterministically check every citation in the referral against the resource ids actually in the bundle.

    Invalid ids are stripped and recorded; nothing the model asserts is trusted without a matching resource.
    """
    referral = copy.deepcopy(referral)
    rejected = []
    citations_total = citations_valid = 0
    counts = {"VERIFIED": 0, "PARTIAL": 0, "UNSUPPORTED": 0}

    for claim in referral.get("patient_summary", []):
        cited = [normalize_ref(c) for c in claim.get("rejected_citations", []) + claim.get("citation_ids", [])]
        cited = list(dict.fromkeys(c for c in cited if c))
        good = [c for c in cited if c in valid_ids]
        bad = [c for c in cited if c not in valid_ids]
        citations_total += len(cited)
        citations_valid += len(good)
        rejected.extend(bad)
        claim["citation_ids"] = good
        claim["rejected_citations"] = bad
        claim["verification"] = "VERIFIED" if good and not bad else "PARTIAL" if good else "UNSUPPORTED"
        counts[claim["verification"]] += 1

    audit_unverified = 0
    payer_basis_rejected = 0
    for item in referral.get("guideline_audit", []):
        # A payer requirement needs a retrieved payer policy behind it
        if not payer_policy_found and item.get("basis") in ("PAYER", "BOTH"):
            item["basis"] = "CLINICAL"
            payer_basis_rejected += 1
        # The model sometimes lists several ids in one field ("obs-sbp-421, obs-dbp-422"); every one must resolve
        raw = item.get("supporting_resource_id") or ""
        support_ids = [i for i in (normalize_ref(part) for part in re.split(r"[,;\s]+", str(raw))) if i]
        support = ", ".join(support_ids) or None
        item["supporting_resource_id"] = support
        item["evidence_verified"] = bool(support_ids) and all(i in valid_ids for i in support_ids)
        # A SATISFIED claim without real evidence is downgraded: it must not suppress a needed order silently
        if item.get("status") == "SATISFIED" and not item["evidence_verified"]:
            item["status"] = "UNVERIFIED"
            item["clinical_note"] = f"{item.get('clinical_note', '')} [Cited evidence '{support}' not found in record.]".strip()
            audit_unverified += 1
            rejected.extend(i for i in support_ids if i not in valid_ids)

    report = {
        "claims_total": sum(counts.values()),
        "claims_verified": counts["VERIFIED"],
        "claims_partial": counts["PARTIAL"],
        "claims_unsupported": counts["UNSUPPORTED"],
        "citations_total": citations_total,
        "citations_valid": citations_valid,
        "audit_unverified": audit_unverified,
        "payer_basis_rejected": payer_basis_rejected,
        "rejected_ids": sorted(set(rejected)),
        "all_verified": counts["PARTIAL"] == 0 and counts["UNSUPPORTED"] == 0 and audit_unverified == 0,
    }
    return referral, report
