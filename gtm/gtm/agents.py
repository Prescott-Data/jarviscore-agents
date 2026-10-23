"""The desk's two agents. Both are plain JarvisCore AutoAgents."""

from __future__ import annotations

from jarviscore import AutoAgent

from gtm.contracts import Assessment, GTMBrief
from gtm.prompts import ACCOUNT_EXPERT_PROMPT, GTM_AGENT_PROMPT

# The connected systems the GTM agent may reach through Nexus. Public research
# needs none: the Kernel's researcher searches the web without a connection.
GTM_SYSTEMS = ["gmail", "google_calendar", "google_drive", "hubspot", "slack"]


class GTMAgent(AutoAgent):
    """One go-to-market agent: the request decides the work, not a sales process."""

    role = "gtm_agent"
    description = (
        "Researches, qualifies, prepares and keeps CRM truth for whatever revenue "
        "work the request requires."
    )
    capabilities = ["gtm", "action_briefing"]
    capability_descriptions = {
        "gtm": "Complete a go-to-market request with sourced evidence.",
        "action_briefing": "Tell the person the decision, its reason and what remains open.",
    }
    capability_contracts = {
        "gtm": {"effects": ["read", "propose", "write", "notify"], "systems": GTM_SYSTEMS},
        "action_briefing": {"effects": ["final_response"], "systems": []},
    }
    # It reads and drafts in the person's connected systems.
    requires_auth = True
    # A generalist: the Kernel routes each step to research, code or communication.
    default_kernel_role = None
    output_schema = GTMBrief
    system_prompt = GTM_AGENT_PROMPT


class AccountExpert(AutoAgent):
    """Judges whether each computed change at an account matters to the desk."""

    role = "account_expert"
    description = "Judges which of an account's changes deserve a person's attention."
    capabilities = ["significance_assessment"]
    # It judges evidence it is handed: no search, no code, no provider calls.
    default_kernel_role = "communicator"
    requires_auth = False
    output_schema = Assessment
    system_prompt = ACCOUNT_EXPERT_PROMPT
