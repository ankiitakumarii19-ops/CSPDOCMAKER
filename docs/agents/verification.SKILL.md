# Verification Agent — SKILL.md

> **The question it owns**
> *Does what a CSP submitted agree with what was already on file?*

A CSP who opens their link can correct what is on file as well as fill what is blank. Most of the time that is exactly right. Sometimes it contradicts the source sheet, and somebody has to decide which is true — that is a person's job, not an agent's.

## At a glance

| | |
|---|---|
| Key | `verification` |
| Schedule | Every 30 minutes |
| On by default | yes |
| Implementation | `backend/app/services/agents.py` — `@performs("verification")` |
| Registered in | `backend/app/services/agent_registry.py` |

## What it does

- Compares each submitted value against the stored one
- Lists fields the CSP changed rather than confirmed
- Flags a change that contradicts the source sheet as a conflict
- Notices links sent and never answered, and links that expired
- Routes a conflict to the RM who owns that CSP

## What it may do on its own

- Record what changed
- Mark a request answered, expired or in conflict

## What it must ask a person about

- Accepting a contradicting value over the one on file

## What it reads and writes

**Reads:** `data_requests`, `csp_records`

**Writes:** `data_requests (status)`, `agent_findings`

## Things to be careful about

- A contradiction is routed to the RM who owns that CSP, and the agent proposes rather than applies. Accepting a CSP's version over the bank's record is a decision with consequences.
- It also notices links that were sent and never answered, and links that have expired — the difference between 'they have not replied' and 'they can no longer reply'.

## How it runs

It is a plain function taking a database session. It does not call any
other agent and no other agent calls it — they coordinate through the
database, not through each other. The runner records every pass in
`agent_runs`: when, who triggered it, what it concluded and how long it
took. A Super Admin can read that history on the Agents screen.

Scheduled runs happen once inside each active workspace, because an agent
reads workspace-scoped tables and would otherwise see nothing.

A disabled agent is not skipped silently — the run record says it was
switched off, which is the difference between "it found nothing" and "it
never looked".
