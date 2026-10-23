"""The Personal Intelligence agent: one general JarvisCore AutoAgent."""

from jarviscore import AutoAgent

# Connected apps this agent may read from and act on, plus the browser for
# sites without an API. Each name is a JarvisCore atom bundle
# (`jarviscore atom list`); Nexus supplies credentials once the person connects.
PERSONAL_SYSTEMS = [
    "browser",
    "dropbox",
    "gmail",
    "google_calendar",
    "google_drive",
    "google_maps",
    "google_people",
    "google_sheets",
    "msgraph",
    "notion",
    "slack",
    "telegram",
    "todoist",
    "twilio",
    "whatsapp_business",
    "zoom",
]

SYSTEM_PROMPT = """You are a person's Personal Intelligence agent. You take a goal in
their own words (research a decision, plan something, handle an errand, keep track
of what matters) and do the work until it is done or a real obstacle stops it.

- Start from the outcome they asked for and the constraints they gave. Check
  current facts with the web, the browser and their connected apps before relying
  on what you remember.
- Remember what will matter next time: preferences, corrections, commitments and
  decisions they confirm. Never keep credentials or payment details.
- Ask the person only for a fact, choice or approval you cannot get yourself.
  Signing in grants access, not consent: sending, booking, buying, paying and
  deleting wait for their approval.
- Report plainly what you found and did, with sources and receipts, and what is
  still open. Never present a plan or a draft as something that happened."""


class PersonalIntelligenceAgent(AutoAgent):
    role = "personal_intelligence_agent"
    description = "Researches, plans and acts on a person's goals through the web and their apps."
    capabilities = ["personal_intelligence", "personal_briefing"]
    capability_descriptions = {
        "personal_intelligence": (
            "Complete one part of the person's goal with current evidence, their "
            "connected apps and the authority granted for each effect."
        ),
        "personal_briefing": "Tell the person what was found and done, and what remains open.",
    }
    capability_contracts = {
        "personal_intelligence": {
            "effects": ["read", "propose", "write", "notify", "destructive"],
            "systems": PERSONAL_SYSTEMS,
        },
        "personal_briefing": {"effects": ["final_response"], "systems": []},
    }
    # Calls the person's connected apps through Nexus.
    requires_auth = True
    # No default_kernel_role: this is a generalist, so the Kernel routes each step
    # to the researcher, browser, coder or communicator it needs.
    system_prompt = SYSTEM_PROMPT
