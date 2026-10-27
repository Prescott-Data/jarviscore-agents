CLAIMS_HUB = "http://127.0.0.1:18085"

ATOM_POLICY = {
    "effect": "write",
    "approval": "never",
    "idempotency_fields": ["claim_id"],
    "consequence": "Approves the insurance claim for settlement at the amount given.",
}


async def claims_hub_approve_claim(claim_id: str, amount: str) -> dict:
    """Approve one vetted insurance claim in Claims Hub for its full amount, as a decimal
    string such as "1250.00". API: POST /api/claims/{claim_id}/approve"""
    response = await nexus_call("POST", f"{CLAIMS_HUB}/api/claims/{claim_id}/approve",
                                json={"amount": amount})
    if not response["ok"]:
        return {"success": False, "error": response["body"]}
    return {"success": True, "approval": response["json"]}
