import os

NEBIUS_BASE_URL = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")

# Available models on Nebius Token Factory
MODEL_FAST = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"   # High-throughput extraction
MODEL_REASONING = "nvidia/Nemotron-3-Ultra-550b-a55b"  # Frontier MoE reasoning

# Token Factory list prices, USD per 1M tokens (see nebius_model_info.txt)
MODEL_PRICING = {
    MODEL_FAST: {"input": 0.06, "output": 0.24},
    MODEL_REASONING: {"input": 1.00, "output": 1.00},
}

# Searched separately, so payer policies never get crowded out of the results by society guidelines
SOCIETY_DOMAINS = [
    # --- Clinical Specialty Societies (Standard of Care) ---
    "kdigo.org", "kidney.org",                                      # Nephrology
    "acc.org", "heart.org", "ahajournals.org", "jacc.org",          # Cardiology
    "diabetes.org", "diabetesjournals.org", "endocrine.org",        # Endocrinology
    "aan.com",                                                      # Neurology
    "ncbi.nlm.nih.gov",                                             # Peer-reviewed validation
]

PAYER_DOMAINS = [
    # --- Payer Clinical Policy & Utilization Guidelines ---
    "aetna.com",           # Aetna Clinical Policy Bulletins (CPBs)
    "uhcprovider.com",     # UnitedHealthcare Provider Clinical Guidelines
    "cigna.com",           # Cigna Medical Coverage Policies
    "anthem.com",          # Anthem Clinical UM Guidelines
    "cms.gov",             # Medicare NCD / LCD Coverage Manuals
]

# Subdomains inside the payer allowlist that never hold coverage policy (qcor.cms.gov = facility inspection reports)
PAYER_EXCLUDE_DOMAINS = ["qcor.cms.gov"]

SOCIETY_MAX_RESULTS = 4
PAYER_MAX_RESULTS = 3

# How many times the governor may loop back to reconcile drift before holding for human review
MAX_RECONCILIATIONS = 2
