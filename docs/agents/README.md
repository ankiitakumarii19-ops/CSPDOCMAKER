# The agents

Six workers, each owning one question and answering it on a schedule.

| Agent | The question it owns | Runs | On by default |
|---|---|---|---|
| [Setup](setup.SKILL.md) | Is this workspace configured well enough to issue documents? | on demand | yes |
| [Data](data.SKILL.md) | Is every record complete, and if not, who should be asked? | 15 min | yes |
| [Verification](verification.SKILL.md) | Does what a CSP submitted agree with what was already on file? | 30 min | yes |
| [Document](document.SKILL.md) | Which documents are ready to be produced, and from which template? | 3 min | yes |
| [Communication](communication.SKILL.md) | Who needs to hear something, and has it reached them? | 60 min | **no** |
| [Monitoring](monitoring.SKILL.md) | Is anything stuck, failing, or quietly not running? | 10 min | yes |

## They are not connected to each other

No agent imports, calls, or passes anything to another. `run_all()` loops
over them and runs each independently — *one failing does not stop the
others*.

They coordinate through the database instead. An agent reads the state of
the world, draws a conclusion, and writes it down; the next agent reads the
same world.

```
Data Agent          reads csp_records      → "this record is incomplete"
Communication Agent reads csp_records      → "this one needs asking"
                         + data_requests   → "...and has not been asked yet"
Verification Agent  reads data_requests    → "this answer contradicts the file"
Document Agent      reads processing_jobs  → "this is queued and unfinished"
Monitoring Agent    reads sync_runs
                         + agent_states    → "this is stuck, or not running"
```

The Data Agent does not *tell* the Communication Agent anything. It changes
a record, and the Communication Agent notices on its own next run — the
same way it would notice a change an RM made by hand.

**Why it was built that way.** One failure stays one failure. Order stops
mattering, which it would not if they declared intervals of 3, 10, 15, 30
and 60 minutes and depended on each other. And any one of them can be
switched off without breaking the rest.

**The single exception:** the Monitoring Agent reads `agent_states` to spot
an agent failing repeatedly and *proposes* disabling it. It cannot act; a
person accepts that on the Agents screen.

## What an agent may never do

No agent decides whether a document is **correct**. Validation, placeholder
replacement, photo sizing and PDF conversion are deterministic and are
never overridden. Agents decide *when* work happens and *who* is asked —
never whether the output is right.

Anything that changes configuration is a **proposal**, recorded as a
finding and shown as a decision. Accepting it is a deliberate act, because
an agent that could quietly remap a placeholder could quietly print the
wrong name on every certificate.

## How a run is recorded

Every pass writes to `agent_runs`: when, who triggered it (`schedule`, or
the email of whoever clicked Run now), the status, the summary and how long
it took. Findings attach to the run that produced them.

That history is visible to a **Super Admin** on the Agents screen. It
records who operated the workspace and what failed, which is closer to
access control than to the work itself — an Admin runs the agents and reads
their findings, but does not see the history.

## Writing a seventh agent

1. Register it in `agent_registry.py` — key, name, the question it owns,
   what it does, what it may do alone, what it must propose, its trigger
   and interval.
2. Implement it in `agents.py` with `@performs("your_key")`, taking a
   session and returning findings.
3. That is all. The beat schedule is **built from the registry**, so
   registering it schedules it. The screen is built from the registry, so
   registering it describes it.
4. Write its `SKILL.md` here.

Two things the runner will not forgive: an implementation whose key is not
in the registry raises at import (*"an agent nobody can describe should not
be running"*), and a registered agent with no implementation records a
skipped run saying so rather than silently doing nothing.
