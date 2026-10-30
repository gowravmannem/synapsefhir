# Demo patients. Labels stay neutral on purpose: the specialty comes from triage (Nemotron 3.5 Lightning), not chosen here.
# Each drift event is a result filed into the chart by another system while the agent is mid-run.
PATIENTS = {
    "pat-james-01 · 58M": {
        "bundle": "sample_bundle.json",
        "drift_event": {
            "source": "Quest outside lab interface",
            "delay_sec": 3.0,
            "resource": {
                "resourceType": "Observation",
                "id": "obs-uacr-990",
                "status": "final",
                "code": {"text": "Urine Albumin-to-Creatinine Ratio (uACR)"},
                "valueQuantity": {"value": 310, "unit": "mg/g"},
                "effectiveDateTime": "2026-10-20T21:00:00Z",
            },
        },
    },
    "pat-maria-02 · 64F": {
        "bundle": "sample_cardio.json",
        "drift_event": {
            "source": "Clinic ECG cart upload",
            "delay_sec": 3.0,
            "resource": {
                "resourceType": "DiagnosticReport",
                "id": "diag-ecg-990",
                "status": "final",
                "code": {
                    "coding": [{"system": "http://loinc.org", "code": "11524-6", "display": "EKG study"}],
                    "text": "12-lead Electrocardiogram (ECG)",
                },
                "effectiveDateTime": "2026-10-22T15:30:00Z",
                "conclusion": "Sinus rhythm, 78 bpm. Left ventricular hypertrophy by voltage criteria with "
                              "repolarization abnormality. No acute ST-segment changes.",
            },
        },
    },
    "pat-david-03 · 52M": {
        "bundle": "sample_endo.json",
        "drift_event": {
            "source": "LabCorp outside lab interface",
            "delay_sec": 3.0,
            "resource": {
                "resourceType": "Observation",
                "id": "obs-hba1c-990",
                "status": "final",
                "code": {
                    "coding": [{"system": "http://loinc.org", "code": "4548-4", "display": "Hemoglobin A1c"}],
                    "text": "Hemoglobin A1c (HbA1c)",
                },
                "valueQuantity": {"value": 9.6, "unit": "%"},
                "effectiveDateTime": "2026-10-21T09:15:00Z",
            },
        },
    },
}
