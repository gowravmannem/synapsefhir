import copy
import threading
import time
from typing import Any, Dict, List

class MockEHRStore:
    """In-memory stand-in for a live FHIR server that other systems can write to while the agent is running."""
    def __init__(self, bundle: Dict[str, Any]):
        self._bundle = copy.deepcopy(bundle)
        self._lock = threading.Lock()
        self.events: List[Dict[str, Any]] = []

    def read_bundle(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._bundle)

    def write_resource(self, resource: Dict[str, Any], source: str):
        with self._lock:
            entries = self._bundle.setdefault("entry", [])
            for entry in entries:
                existing = entry.get("resource", {})
                if existing.get("id") == resource.get("id") and existing.get("resourceType") == resource.get("resourceType"):
                    entry["resource"] = copy.deepcopy(resource)
                    break
            else:
                entries.append({"resource": copy.deepcopy(resource)})
            self.events.append({
                "time": time.time(),
                "source": source,
                "resource": f"{resource.get('resourceType')}/{resource.get('id')}",
            })

    def schedule_external_write(self, resource: Dict[str, Any], delay_sec: float, source: str = "External EHR") -> threading.Timer:
        """Simulate another system (e.g. radiology) filing a result into the chart after delay_sec."""
        timer = threading.Timer(delay_sec, self.write_resource, args=(resource, source))
        timer.daemon = True
        timer.start()
        return timer
