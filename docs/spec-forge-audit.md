# spec-forge audit

Audit target: `/Users/matiasrios/Documents/GitHub/spec-forge`

## Useful pieces to absorb

### 1. Intake structure

`spec-forge` already captured a strong greenfield interview shape around:

- project name
- one-liner
- target user
- problem
- MVP boundary
- primary flow
- entities
- frontend surface
- backend needs
- auth needs
- integrations
- success definition
- first cycle goal
- final checkpoint
- notes

These fields were absorbed into `config/intake/greenfield-questionnaire.yaml`.

### 2. Template-driven handoff

`spec-forge` is good at producing:

- a spec
- architecture notes
- checkpoints
- handoff docs
- a minimal scaffold

That pattern was absorbed conceptually into:

- `Mission Spec`
- `Execution Graph`
- `template catalog`
- `kickoff_artifacts`

### 3. Greenfield-first mindset

The repo treated greenfield setup as a first-class flow rather than an afterthought. That principle was kept.

## What not to carry over as-is

- The architecture cannot depend on `spec-forge` as a central runtime component.
- The output cannot assume one fixed stack forever.
- The system must be multi-repo and mission-centric, while `spec-forge` was mostly generating one handoff-ready repo.
- The new hub needs persistent operational state and a graph, not just generated files.

## Concrete absorption in this repo

- Questionnaire fields were lifted into versioned config.
- Template selection became config-driven instead of hard-coded into one generator.
- Handoff docs were generalized into mission artifacts.
- Greenfield repo mapping became part of planner/bootstrap logic.

## Deferred follow-up

- Extract stack-specific scaffold generators into reusable template packs.
- Add handoff doc rendering beyond plain text artifacts.
- Expand template selection from keyword matching to rule-based scoring.

