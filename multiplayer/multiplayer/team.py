"""The campaign room: three people, a strategist, a writer and the agent they talk to.

Everything multiplayer comes from JarvisCore: the room, its proposals and
permissions, the RoomAgent that understands the team, and RoomConversation,
which delivers it to wherever the team talks (the Desk, Slack, your product).
This file only says who the team is and what the agents do.
"""

import os

from jarviscore import Mesh
from jarviscore.profiles import AutoAgent
from jarviscore.room import Person, Room, RoomAgent

TENANT = "acme"
ROOM = "holiday-campaign"
BRIEF_FILE = "campaign-brief.md"

#: The team. Ava owns the room; Bob and Dana edit it.
TEAM = {
    "ava": (Person(TENANT, "ava", "Ava Chen"), "owner"),
    "bob": (Person(TENANT, "bob", "Bob Iyer"), "editor"),
    "dana": (Person(TENANT, "dana", "Dana Whitfield"), "editor"),
}

BRIEF = """# Northwind Platinum: holiday campaign brief

A limited-time offer on the Northwind Platinum card while people plan their holidays.

- Offer: 3x points on flights and hotels booked Nov 15 to Jan 5
- Card perks to lean on: airport lounge access, travel insurance, no foreign transaction fees
- Audience: cardholders and prospects planning holiday travel
- Channels available: email, Instagram, LinkedIn, the app
- Compliance: every claim must match the offer terms
"""


class Strategist(AutoAgent):
    """Works out who the work is for and where to reach them."""

    role = "strategist"
    capabilities = ["research", "strategy"]
    description = ("Researches audiences and markets: ideal customer profiles, segments, "
                   "positioning and channel fit, written up in the room's files.")
    system_prompt = (
        "You research audiences and markets for a team: ideal customer profiles, segments, "
        "positioning and which channels fit them. Ground every claim in the room's files or "
        "your research, say why, and write the result as a short, scannable document."
    )


class Writer(AutoAgent):
    """Writes and edits the team's documents in the room's files."""

    role = "writer"
    capabilities = ["writing", "editing"]
    description = ("Writes and edits the team's documents: announcements, campaign ideas, "
                   "email sequences, social posts and plans.")
    system_prompt = (
        "You write and edit a team's working documents: announcements, campaign ideas, "
        "email sequences, social posts and plans. Read the room's files for context and "
        "build on the research in them. Write the deliverable itself, for the people who "
        "will read it: never copy your instructions or the request into the document. "
        "Keep it short and concrete."
    )


class CampaignDesk(RoomAgent):
    """The agent the team talks to."""

    system_prompt = (
        "You are the team's desk. Be brief: the team is busy. Pass requests to the "
        "agents in the person's own words, and answer questions about the work yourself."
    )
    ask_options = {"timeout": 900}


def build_mesh() -> Mesh:
    """The mesh the Desk starts: the room agent, a strategist and a writer, on Redis."""
    mesh = Mesh(config={
        "redis_url": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        "p2p_enabled": False,
        "distributed_poll_interval": 0.5,
    })
    mesh.add(CampaignDesk)
    mesh.add(Strategist)
    mesh.add(Writer)
    return mesh


async def open_room(mesh: Mesh) -> Room:
    """The campaign room, created with the brief on first use, open to the whole team."""
    room = Room.for_mesh(mesh, ROOM, tenant=TENANT)
    owner = TEAM["ava"][0]
    await room.ensure({BRIEF_FILE: BRIEF}, by=owner)
    for person, role in TEAM.values():
        if role != "owner":
            room.set_role(person, role, by=owner)
    return room
