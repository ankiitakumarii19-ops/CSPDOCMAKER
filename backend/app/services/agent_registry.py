"""
CSP DocMaker — the six agents, and what each is responsible for

Each agent owns one question and answers it on a schedule or on demand. It
writes a run record every time, and anything it wants changed it proposes
rather than does.

What an agent is NOT, in this system: a wrapper around a language model
that decides whether a document is valid. The brief is explicit and I agree
with it — document validation, placeholder checks, photo dimensions and
required-field checks stay deterministic, because being right matters more
than being clever and a wrong answer prints onto someone's ID card.

What the agents add is the layer above that: noticing, routing, proposing
and reporting. Work that previously happened silently inside a cron job, or
not at all.

Each entry below declares:

  owns        the one question this agent answers
  does        what it actually performs
  may         what it is allowed to change by itself
  proposes    what it must ask a Super Admin about
  trigger     scheduled, on demand, or both
"""

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

SCHEDULED = "scheduled"
ON_DEMAND = "on_demand"
BOTH = "both"


@dataclass(frozen=True)
class Agent:
    key: str
    name: str
    owns: str
    does: List[str]
    may: List[str]
    proposes: List[str]
    trigger: str = BOTH
    # Minutes between automatic runs; None for on-demand only.
    every_minutes: Optional[int] = None
    enabled_by_default: bool = True


_REGISTRY: Dict[str, Agent] = {}


def register(agent: Agent) -> Agent:
    if agent.key in _REGISTRY:
        raise ValueError(f"An agent called {agent.key!r} already exists.")
    _REGISTRY[agent.key] = agent
    return agent


def get(key: str) -> Agent:
    agent = _REGISTRY.get(key)
    if agent is None:
        raise KeyError(
            f"No agent called {key!r}. Known agents: "
            f"{', '.join(sorted(_REGISTRY))}"
        )
    return agent


def exists(key: str) -> bool:
    return key in _REGISTRY


def all_agents() -> List[Agent]:
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def keys() -> List[str]:
    return sorted(_REGISTRY)


def describe() -> List[dict]:
    """The catalogue, for a screen or for someone asking what runs here."""
    return [
        {
            "key": a.key, "name": a.name, "owns": a.owns, "does": a.does,
            "may": a.may, "proposes": a.proposes, "trigger": a.trigger,
            "every_minutes": a.every_minutes,
        }
        for a in all_agents()
    ]


# =========================================================================
# The six
# =========================================================================

SETUP = register(Agent(
    key="setup",
    name="Setup Agent",
    owns="Is this workspace configured well enough to issue documents?",
    does=[
        "Reads each data source and reports whether it can be reached",
        "Compares the source's columns against the configured fields",
        "Reads every template and lists placeholders nothing fills",
        "Checks each document has a photo marker if it needs one",
        "Names what is still missing before the workspace can go live",
    ],
    may=[
        "Read configuration and report on it",
        "Record findings",
    ],
    proposes=[
        "Mapping a source column to a field",
        "Mapping a template placeholder to a field",
        "Activating a template once everything it needs is mapped",
    ],
    trigger=ON_DEMAND,
))

DATA = register(Agent(
    key="data",
    name="Data Agent",
    owns="Is every record complete, and if not, who should be asked?",
    does=[
        "Finds records with blank required fields",
        "Fills what the territory directory can answer, so nobody is asked",
        "Splits the rest into what the CSP owns and what their RM owns",
        "Raises an alert for the RM, and marks the CSP as needing asking",
        "Reports records nobody owns, which every RM can see",
    ],
    may=[
        "Fill a field from the directory when exactly one answer matches",
        "Raise and clear RM alerts",
    ],
    proposes=[
        "Resolving a territory that matches more than one person",
        "A district spelling that nearly matches a known one",
    ],
    trigger=BOTH,
    every_minutes=15,
))

VERIFICATION = register(Agent(
    key="verification",
    name="Verification Agent",
    owns="Does what a CSP submitted agree with what was already on file?",
    does=[
        "Compares each submitted value against the stored one",
        "Lists fields the CSP changed rather than confirmed",
        "Flags a change that contradicts the source sheet as a conflict",
        "Notices links sent and never answered, and links that expired",
        "Routes a conflict to the RM who owns that CSP",
    ],
    may=[
        "Record what changed",
        "Mark a request answered, expired or in conflict",
    ],
    proposes=[
        "Accepting a contradicting value over the one on file",
    ],
    trigger=BOTH,
    every_minutes=30,
))

DOCUMENT = register(Agent(
    key="document",
    name="Document Agent",
    owns="Which documents are ready to be produced, and from which template?",
    does=[
        "Finds records with everything their documents need",
        "Picks the active template for each configured document",
        "Hands the work to the existing deterministic pipeline",
        "Reports anything the pipeline refused, and why",
    ],
    may=[
        "Trigger generation for a record that is complete",
    ],
    proposes=[
        "Nothing. Validation, placeholders, photo size and PDF conversion "
        "stay deterministic and are never overridden by an agent",
    ],
    trigger=BOTH,
    every_minutes=3,
))

COMMUNICATION = register(Agent(
    key="communication",
    name="Communication Agent",
    owns="Who needs to hear something, and has it reached them?",
    does=[
        "Finds CSPs who should be asked for their details",
        "Chooses the workspace's configured channel and wording",
        "Sends, and records what happened to each message",
        "Retries a failure according to the workspace's own rules",
        "Falls back to email when a CSP has no usable mobile number",
    ],
    may=[
        "Send a message a workspace has configured and enabled",
        "Retry a failed send",
    ],
    proposes=[
        "Messaging a large group for the first time",
        "Sending through a channel that has never succeeded",
    ],
    trigger=BOTH,
    every_minutes=60,
    # Deliberately off until a workspace has configured a channel and a
    # Super Admin has turned it on. An agent that starts messaging real
    # people the moment it is deployed is not a feature.
    enabled_by_default=False,
))

MONITORING = register(Agent(
    key="monitoring",
    name="Monitoring Agent",
    owns="Is anything stuck, failing, or quietly not running?",
    does=[
        "Checks each data source synced when it should have",
        "Finds processing jobs that stopped part-way",
        "Counts failed sends and failed generations",
        "Watches the task queue for a backlog that is not clearing",
        "Notices an agent that has failed several times in a row",
    ],
    may=[
        "Record findings and raise their severity",
    ],
    proposes=[
        "Disabling an agent that keeps failing",
    ],
    trigger=BOTH,
    every_minutes=10,
))
