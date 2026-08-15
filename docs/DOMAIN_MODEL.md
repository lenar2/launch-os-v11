# Launch OS v11 Domain Model

Status: canonical pre-code model
Date: 2026-08-15

## Business Twin

The Business Twin is the source of business state. The LLM is not the source of truth.

Core bounded contexts:

- Business, goals, constraints
- Product, product versions, offers
- Person, identity graph, customer lifecycle
- Audience, segments, insights
- Commerce, orders, payments, subscriptions
- Channels, integrations, capabilities
- Content, briefs, assets, publications, metrics
- Campaigns, launches, funnels
- Evidence, claims, hypotheses, information gaps, conflicts
- Decisions, alternatives, controller reviews
- Experiments, checkpoints, interpretation rules
- Work, tasks, approvals, actions, executions
- Brand Brain and Product Brain
- Learning, decision history, audit

Every important fact or metric retains:

- source
- timestamp or period
- provenance
- epistemic status
- confidence where relevant
- derivation if calculated
- freshness
- business scope

## Epistemic Statuses

Canonical statuses:

- `OBSERVATION`
- `FACT`
- `DERIVED_FACT`
- `HYPOTHESIS`
- `ASSUMPTION`
- `UNKNOWN`
- `CONFLICT`
- `REJECTED`
- `INVALIDATED`

A model confidence score does not promote a hypothesis into a fact.

## Temporal Truth

Historical questions must be answered from event/state history, not current status.

Rules:

- Current subscription status cannot reconstruct exact active count on a past date without history.
- Late-arriving data must apply to `event_time`, not ingestion time.
- The local business timezone is part of metric truth.
- A Decision keeps the immutable BusinessSnapshot used at decision time, even if later facts correct history.

## Data Reconciliation

External events are idempotent and keyed by:

- provider
- provider account
- external object ID
- event identity
- event time where available

API snapshots may correct prior webhook or event state.

Derived metrics expose:

- calculation version
- calculated_at
- source window
- included/excluded event rules
- invalidated_by where relevant

Corrections create new metric versions or invalidate previous derived observations. They do not silently rewrite historical reasoning.

Connector reconciliation jobs periodically compare local normalized state against source-of-truth systems.

## Identity Graph

Cross-system identity resolution is explicit.

Possible identities:

- Instagram account
- Telegram user
- email
- phone
- GetCourse user
- payment customer ID
- CRM contact
- YouTube identity

Identity links carry:

- evidence
- confidence
- source
- created_at
- reviewed_by when human-reviewed

Canonical link statuses:

- verified same person
- strong/probable match
- possible
- conflict
- rejected

Rules:

- Similar names are not sufficient.
- Payments are not automatically unique customers.
- Cross-platform totals are not summed as people unless identity rules allow it.
- Attribution and identity are separate problems.

## Decision

A valid Decision is an object, not a paragraph.

Required fields:

- goal/problem
- selected action
- evidence used
- alternatives considered
- why alternatives were not selected
- hypotheses/assumptions
- known unknowns
- expected effect
- confidence
- reversibility
- risk class
- experiment/checkpoint where appropriate
- success/weak/failure interpretation rules
- required assets/actions
- next checkpoint

If there is no `selected_action`, it is not a Decision.

New Decisions supersede previous Decisions. History is never overwritten.

## Causality Boundary

Attribution alone is not causality.

Canonical evidence classes for explaining movement:

- `DIRECT_DETERMINISTIC_ATTRIBUTION`
- `EXPERIMENTAL_CAUSAL_EVIDENCE`
- `STRONG_OBSERVATIONAL_EVIDENCE`
- `CORRELATION`
- `UNKNOWN`

Allowed statements:

- "This campaign is directly attributed to 12 payments."
- "This experiment supports the hypothesis that X increased conversion."
- "Sales rose after the post, but causal attribution is not established."

The OS must not convert temporal sequence into causation.

## Experiment

Meaningful uncertain strategies should become experiments when testable.

Each experiment defines before execution:

- hypothesis
- baseline
- segment
- treatment
- metric
- window
- attribution method
- success threshold
- weak-signal threshold
- failure threshold
- next action for each result class

Thresholds cannot be silently changed after observing outcomes.

Anti-paralysis rule: if the decision is low-cost and easily reversible, missing useful information must not block action. Only critical information can automatically force a user question.

## Creative Production

Canonical pipeline:

`Decision -> Content/Creative Strategy -> CreativeBrief -> Production -> Brand/Truth/Quality Control -> Approval -> Publication -> Metrics`

Separations:

- Strategy is not Brief.
- Brief is not Asset.
- Asset is not Publication.
- AssetVersion is not approved version.
- User edits create a new version rather than overwriting history.

## Asset Rights and Provenance

Assets retain rights/provenance metadata when applicable:

- source/origin
- uploaded by whom
- generated vs user-provided vs licensed reference
- model/tool used for generation
- related source assets
- permission/usage scope when known
- testimonial/customer-content consent reference
- publication restrictions
- expiration if licensed/time-limited

The OS must not silently reuse customer photos, testimonials, or third-party creative references as production assets without permission context.
