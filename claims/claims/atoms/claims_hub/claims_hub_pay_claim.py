CLAIMS_HUB = "http://127.0.0.1:18085"

ATOM_POLICY = {
    "effect": "write",
    "approval": "never",
    "idempotency_fields": ["claim_id"],
    "consequence": "Pays out the approved insurance claim to the bank account given.",
}


async def claims_hub_pay_claim(claim_id: str, amount: str, iban: str) -> dict:
    """Pay out one approved insurance claim from Claims Hub: its full amount as a decimal string
    such as "1250.00", to the claimant's bank account (IBAN). API: POST /api/payments"""
    response = await nexus_call("POST", f"{CLAIMS_HUB}/api/payments",
                                json={"claim_id": claim_id, "amount": amount, "iban": iban})
    if not response["ok"]:
        return {"success": False, "error": response["body"]}
    return {"success": True, "payment": response["json"]}
