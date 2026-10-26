from typing import Any, Dict, List, Optional

def iter_resources(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [e["resource"] for e in bundle.get("entry", []) if "resource" in e]

def normalize_ref(ref: Optional[str]) -> Optional[str]:
    """'Observation/obs-egfr-201', '[obs-egfr-201]' and 'obs-egfr-201' all become 'obs-egfr-201'."""
    if not ref:
        return None
    return str(ref).strip().strip("[]`'\" ").split("/")[-1] or None

def resource_display(resource: Dict[str, Any]) -> str:
    for key in ("code", "medicationCodeableConcept"):
        concept = resource.get(key) or {}
        if concept.get("text"):
            return concept["text"]
        codings = concept.get("coding") or []
        if codings and codings[0].get("display"):
            return codings[0]["display"]
    if resource.get("resourceType") == "Patient":
        return f"{resource.get('gender', '')} born {resource.get('birthDate', '?')}".strip().capitalize()
    return resource.get("resourceType", "Resource")

def resource_value(resource: Dict[str, Any]) -> Optional[str]:
    quantity = resource.get("valueQuantity")
    if quantity:
        return f"{quantity.get('value')} {quantity.get('unit', '')}".strip()
    if resource.get("conclusion"):
        return resource["conclusion"]
    return None

def resource_date(resource: Dict[str, Any]) -> Optional[str]:
    for key in ("effectiveDateTime", "recordedDate", "authoredOn", "issued", "birthDate"):
        if resource.get(key):
            return resource[key]
    return None

def resource_index(bundle: Dict[str, Any]) -> str:
    """Compact one-line-per-resource listing, so the reasoning model sees every id even if triage filtered it out."""
    lines = []
    for r in iter_resources(bundle):
        parts = [r.get("id", "?"), r.get("resourceType", "?"), resource_display(r)]
        value, date = resource_value(r), resource_date(r)
        if value:
            parts.append(value)
        if date:
            parts.append(date)
        lines.append(" | ".join(parts))
    return "\n".join(lines)
