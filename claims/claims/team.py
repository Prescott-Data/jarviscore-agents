"""The claims desk: Acme Insurance's claims team and the agents they work with, in one room.

The agents work in Claims Hub, the team's claims system, with each person's own
Claims Hub account (connected once, through Nexus). Acme's own rules, in
``policy.yaml``, say who may approve and pay claims and up to how much; JarvisCore
holds every call the agents make to them, whatever Claims Hub itself would allow.
"""

from __future__ import annotations

import os
from pathlib import Path

from jarviscore import Mesh
from jarviscore.profiles import AutoAgent
from jarviscore.room import Person, Room, RoomAgent

TENANT = "acme"
ROOM = "claims-desk"
PROVIDER = "claims_hub"
HERE = Path(__file__).parent
ATOMS = HERE / "atoms" / PROVIDER
POLICY = HERE / "policy.yaml"

#: The team. Carol runs it and may approve claims up to £10,000; Dave handles and pays
#: them; Erin analyses them. Their scopes are in policy.yaml.
TEAM = {
    "carol": (Person(TENANT, "carol", "Carol Reyes"), "owner"),
    "dave": (Person(TENANT, "dave", "Dave Mensah"), "editor"),
    "erin": (Person(TENANT, "erin", "Erin Walsh"), "editor"),
}

QUEUE = """# Claims queue

Claims are worked in Claims Hub. Ask the desk to look up, approve or pay a claim.
"""


def claims_hub_url() -> str:
    return os.environ.get("CLAIMS_HUB_URL", "http://127.0.0.1:18085").rstrip("/")


def install_atoms(registry, base_url: str | None = None) -> list[str]:
    """Register Claims Hub's atoms in an agent's function registry, on Claims Hub's URL.

    They are offered to the agents like any shipped integration: each call goes
    through Nexus with the credential of the person the work is for, and through
    the control policy.
    """
    base = (base_url or claims_hub_url()).rstrip("/")
    names = []
    for path in sorted(ATOMS.glob(f"{PROVIDER}_*.py")):
        source = path.read_text().replace('"http://127.0.0.1:18085"', repr(base).replace("'", '"'))
        first_line = source.split('"""', 2)[1].strip().splitlines()[0]
        if registry.register_function(path.stem, source, metadata={
            "system": PROVIDER, "capabilities": ["claims"], "description": first_line,
            "type": "api", "tags": [PROVIDER, "insurance"], "strategy": "sandbox",
        }):
            registry.update_function_metadata(path.stem, {"registry_stage": "verified"})
            names.append(path.stem)
    return names


class ClaimsAgent(AutoAgent):
    """Looks up, approves and pays claims in Claims Hub, for the person who asked."""

    role = "claims"
    capabilities = ["claims"]
    capability_contracts = {
        "claims": {"effects": ["read", "write"], "systems": [PROVIDER]},
    }
    default_kernel_role = "coder"
    requires_auth = True
    description = ("Works in Claims Hub, the claims system: looks up claims and claimants, "
                   "approves claims and pays them out.")
    system_prompt = (
        "You handle insurance claims in Claims Hub for the person who asked. Read the claim "
        "and its claimant's record before you act on it. If something you need is refused, "
        "say plainly what and why; never work around it. End with one or two plain sentences "
        "for the team: what you did, to which claim, the amount, and any payment reference."
    )

    async def setup(self):
        await super().setup()
        install_atoms(self.code_registry)


class ClaimsDesk(RoomAgent):
    """The agent the claims team talks to."""

    system_prompt = (
        "You are the claims team's desk. Be brief and exact: name claims by id and amounts "
        "in pounds. Pass every request about claims to the agents in the person's own words, "
        "adding nothing; never look claims up or check anyone's authority yourself. When you "
        "pass one on, reply in a few words, such as \"On it.\""
    )
    ask_options = {"timeout": 900}


def build_mesh() -> Mesh:
    """The mesh the Desk starts: the room agent and the claims agent, on Redis and Nexus."""
    os.environ.setdefault("JARVISCORE_CONTROL_POLICY", str(POLICY))
    os.environ.setdefault("JARVISCORE_CONTROL_MODE", "strict")
    mesh = Mesh(config={
        "redis_url": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        "p2p_enabled": False,
        "distributed_poll_interval": 0.5,
    })
    mesh.add(ClaimsDesk)
    mesh.add(ClaimsAgent)
    return mesh


async def open_room(mesh: Mesh) -> Room:
    """The claims room, open to the whole team."""
    room = Room.for_mesh(mesh, ROOM, tenant=TENANT)
    owner = TEAM["carol"][0]
    await room.ensure({"queue.md": QUEUE}, by=owner)
    for person, role in TEAM.values():
        if role != "owner" and room.members().get(person.id) != role:
            room.set_role(person, role, by=owner)
    # Claims Hub is the team's own system: what the agents do there is everyone's to see.
    if room.settings().get("shared_connectors") != [PROVIDER]:
        room.set_shared_connectors([PROVIDER], by=owner)
    return room
