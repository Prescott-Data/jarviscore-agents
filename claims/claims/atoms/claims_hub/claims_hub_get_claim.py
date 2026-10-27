CLAIMS_HUB = "http://127.0.0.1:18085"


async def claims_hub_get_claim(claim_id: str) -> dict:
    """Look up one insurance claim in Claims Hub: claimant and claimant_id, kind, amount,
    currency, status, payment status and the case notes. API: GET /api/claims/{claim_id}"""
    response = await nexus_call("GET", f"{CLAIMS_HUB}/api/claims/{claim_id}")
    if not response["ok"]:
        return {"success": False, "error": response["body"]}
    return {"success": True, "claim": response["json"]}
