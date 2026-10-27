CLAIMS_HUB = "http://127.0.0.1:18085"


async def claims_hub_list_claims(status: str = "") -> dict:
    """List insurance claims in Claims Hub, optionally only those with one status
    (open, vetted, approved or paid). Returns each claim's id, claimant, kind, amount, status and
    payment status.
    API: GET /api/claims?status=..."""
    response = await nexus_call("GET", f"{CLAIMS_HUB}/api/claims",
                                params={"status": status} if status else None)
    if not response["ok"]:
        return {"success": False, "error": response["body"]}
    return {"success": True, "claims": response["json"]["claims"]}
