CLAIMS_HUB = "http://127.0.0.1:18085"


async def claims_hub_get_claimant(claimant_id: str) -> dict:
    """Look up one claimant's record in Claims Hub: name, policy, and the bank account (IBAN)
    on file for paying them. API: GET /api/claimants/{claimant_id}"""
    response = await nexus_call("GET", f"{CLAIMS_HUB}/api/claimants/{claimant_id}")
    if not response["ok"]:
        return {"success": False, "error": response["body"]}
    return {"success": True, "claimant": response["json"]}
