"""The claims blueprint: its policy, its atoms, Claims Hub, and the room."""

import base64
import hashlib
import re
from urllib.parse import parse_qs, urlparse

import fakeredis
import pytest
from fastapi.testclient import TestClient

from claims import claims_hub
from claims.team import POLICY, PROVIDER, TEAM, install_atoms

REDIRECT = "http://127.0.0.1:18080/auth/callback"


# ── The organisation's rules ────────────────────────────────────────────────

def test_the_policy_holds_scopes_approvals_and_grounding(monkeypatch):
    from jarviscore.control import policy as policy_module

    monkeypatch.setenv("JARVISCORE_CONTROL_POLICY", str(POLICY))
    monkeypatch.setenv("JARVISCORE_CONTROL_MODE", "strict")
    monkeypatch.setattr(policy_module, "_cached", None)
    policy = policy_module.current_policy()

    assert policy.mode == "strict"
    assert not policy.scopes.problems
    assert policy.scopes.grants["acme/carol"]["claims.approve"] == {"amount": "10000"}
    assert "claims.approve" not in policy.scopes.grants["acme/erin"]
    assert [rule.name for rule in policy.approvals] == ["payments-maker-checker"]
    assert [rule.name for rule in policy.grounding] == ["pay-the-claimant-on-record"]


def test_the_atoms_meet_the_contract_and_call_claims_hub_where_it_runs(tmp_path):
    from jarviscore.execution.atom_contract import read_contract
    from jarviscore.execution.code_registry import create_function_registry

    registry = create_function_registry(str(tmp_path), seed=False)
    names = install_atoms(registry, "https://claims.acme.example")

    assert names == [f"{PROVIDER}_{n}" for n in
                     ("approve_claim", "get_claim", "get_claimant", "list_claims", "pay_claim")]
    for name in names:
        code = registry.get_function_code(name)
        assert read_contract(code, system=PROVIDER, expected_name=name).ok, name
        assert '"https://claims.acme.example"' in code and "127.0.0.1" not in code
        assert registry.get_function_metadata(name)["registry_stage"] == "verified"


# ── Claims Hub ──────────────────────────────────────────────────────────────

@pytest.fixture
def hub():
    claims_hub.reset()
    claims_hub._sessions.clear()
    claims_hub._tokens.clear()
    claims_hub._refresh.clear()
    claims_hub._grants.clear()
    return TestClient(claims_hub.app)


def connect(hub, who):
    """Sign in as ``who`` and allow, as a person does in their browser; returns their token."""
    hub.cookies.clear()  # each person in their own browser
    verifier = "v" * 50
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    query = (f"client_id={claims_hub.CLIENT_ID}&redirect_uri={REDIRECT}&response_type=code"
             f"&scope=claims:read claims:write&state=s1&code_challenge={challenge}"
             "&code_challenge_method=S256")
    assert "Sign in" in hub.get(f"/oauth/authorize?{query}").text
    signed = hub.post("/oauth/sign-in", data={"email": f"{who}@acme.example",
                                              "password": claims_hub.PASSWORD, "query": query},
                      follow_redirects=False)
    consent = hub.get(signed.headers["location"]).text
    assert "Allow JarvisCore Agents to act for you?" in consent
    fields = dict(re.findall(r'name="?([a-z_]+)"? value="([^"]*)"', consent))
    landed = hub.post("/oauth/decide", data={**fields, "decision": "allow"}, follow_redirects=False)
    code = parse_qs(urlparse(landed.headers["location"]).query)["code"][0]
    token = hub.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
        "code_verifier": verifier, "client_id": claims_hub.CLIENT_ID,
        "client_secret": claims_hub.CLIENT_SECRET}).json()
    return {"Authorization": f"Bearer {token['access_token']}"}


def test_each_person_signs_in_and_consents_and_the_api_knows_who_they_are(hub):
    dave = connect(hub, "dave")
    assert hub.get("/api/me", headers=dave).json()["name"] == "Dave Mensah"
    assert hub.get("/api/claims").status_code == 401
    assert hub.get("/ops/state").json()["connections"][0]["user"] == "Dave Mensah"


def test_a_code_is_bound_to_its_verifier(hub):
    challenge = base64.urlsafe_b64encode(hashlib.sha256(b"right").digest()).decode().rstrip("=")
    query = (f"client_id={claims_hub.CLIENT_ID}&redirect_uri={REDIRECT}&response_type=code&state=s"
             f"&code_challenge={challenge}&code_challenge_method=S256")
    signed = hub.post("/oauth/sign-in", data={"email": "erin@acme.example",
                                              "password": claims_hub.PASSWORD, "query": query},
                      follow_redirects=False)
    consent = hub.get(signed.headers["location"]).text
    fields = dict(re.findall(r'name="?([a-z_]+)"? value="([^"]*)"', consent))
    landed = hub.post("/oauth/decide", data={**fields, "decision": "allow"}, follow_redirects=False)
    code = parse_qs(urlparse(landed.headers["location"]).query)["code"][0]
    exchanged = hub.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
        "code_verifier": "wrong", "client_id": claims_hub.CLIENT_ID,
        "client_secret": claims_hub.CLIENT_SECRET})
    assert (exchanged.status_code, exchanged.json()["error"]) == (400, "invalid_grant")


def test_every_call_is_recorded_with_whose_account_made_it(hub):
    carol, dave = connect(hub, "carol"), connect(hub, "dave")

    approved = hub.post("/api/claims/CLM-1041/approve", json={"amount": "4000.00"}, headers=carol)
    assert approved.status_code == 200
    paid = hub.post("/api/payments", headers=dave, json={
        "claim_id": "CLM-1043", "amount": "2850.00", "iban": "GB33BUKB20201555555555"})

    assert paid.status_code == 201
    activity = hub.get("/ops/state").json()["activity"]
    writes = [(a["user"], a["action"], a["claim"]) for a in activity if a["write"]]
    assert writes == [("Carol Reyes", "approved", "CLM-1041"), ("Dave Mensah", "paid", "CLM-1043")]
    claim = hub.get("/api/claims/CLM-1043", headers=dave).json()
    assert (claim["status"], claim["payment_status"]) == ("paid", "paid")
    assert claim["paid_by"] == "Dave Mensah"


def test_claims_hub_keeps_its_own_business_rules(hub):
    dave = connect(hub, "dave")
    def post(path, body):
        return hub.post(path, json=body, headers=dave).status_code

    assert post("/api/claims/CLM-1039/approve", {"amount": "1150.00"}) == 409, "not vetted"
    assert post("/api/claims/CLM-1041/approve", {"amount": "1.00"}) == 422, "not its amount"
    assert post("/api/payments", {"claim_id": "CLM-1041", "amount": "4000.00",
                                  "iban": "GB29NWBK60161331926819"}) == 409, "not approved"


# ── The room ────────────────────────────────────────────────────────────────

async def test_the_room_opens_with_the_team_and_shares_claims_hub(tmp_path, monkeypatch):
    from jarviscore import Mesh
    from jarviscore.storage.local import LocalBlobStorage
    from jarviscore.storage.redis_store import RedisContextStore

    from claims.team import build_mesh, open_room

    redis = RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: redis)
    monkeypatch.setattr(Mesh, "_init_blob_storage",
                        lambda self, settings: LocalBlobStorage(str(tmp_path)))
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    monkeypatch.setenv("LOG_DIRECTORY", str(tmp_path / "logs"))
    mesh = build_mesh()
    mesh.config["p2p_enabled"] = False
    await mesh.start()
    try:
        room = await open_room(mesh)
        again = await open_room(mesh)

        assert room.members() == {p.id: role for p, role in TEAM.values()}
        assert room.settings()["shared_connectors"] == [PROVIDER]
        events = [e["type"] for e in again.events()]
        assert events.count("room.connectors") == 1, "opening it again changes nothing"
        claims = next(a for a in mesh.agents if a.role == "claims")
        assert claims.code_registry.has_function(f"{PROVIDER}_pay_claim"), "its atoms are installed"
    finally:
        await mesh.stop()
