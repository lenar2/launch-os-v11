# Launch OS v11.1 Implementation Spec

Status: pre-code contract for first vertical slice
Date: 2026-08-15

## Objective

v11.1 succeeds only when one real closed loop is implemented:

`CreateLaunch -> BusinessSnapshot -> specialist contributions -> Chief Producer Decision -> controller review -> experiment/checkpoint definition -> CreativeBrief -> one real Asset -> Brand/Truth/Quality review -> Approval -> Telegram publication -> observed external result -> metric update -> Learning Controller -> next Decision`

Do not expand to more broad modules until this loop closes.

## Scope

Implement the minimum durable architecture for:

- platform tenant/user boundary
- Business, Goal, Product, Offer, Channel
- Evidence, Claim, Hypothesis, InformationNeed
- Decision, Alternative, ControllerReview
- Experiment and Checkpoint
- CreativeBrief, Asset, AssetVersion
- ActionProposal, Approval, Execution
- BusinessEvent, MetricVersion, Learning
- BusinessSnapshot
- Permission Engine
- Outbox, jobs, audit
- Orchestrator skeleton
- first specialist/controller contracts
- Telegram publication loop

## Non-Scope

Do not implement in v11.1:

- broad Instagram analytics beyond readiness placeholders
- GetCourse full sync
- payment provider sync without named provider
- multi-agent marketplace
- autonomous ad spend
- full Creative Studio
- CRM retention automation
- policy autopilot
- microservices

## Recommended First Workflow

1. Owner creates business, offer, and Telegram channel connection.
2. Owner creates launch with goal, audience, offer, channel, and checkpoint window.
3. System creates immutable BusinessSnapshot.
4. Business/Product Analyst and Telegram Strategist produce structured contributions.
5. Chief Growth Producer creates Decision with selected action.
6. Controllers review evidence, constitutional language, manipulation risk, brand fit, execution risk, and decision quality.
7. Experiment Lead defines checkpoint interpretation rules.
8. CreativeBrief is generated.
9. Copy asset is generated as AssetVersion 1.
10. Brand/Truth/Quality controllers review the asset.
11. ActionProposal is created for Telegram publication.
12. Permission Engine requires owner approval.
13. Owner approves.
14. Execution Engine publishes to Telegram.
15. Telegram connector records external message ID.
16. Observation job ingests Telegram message/update data available to the bot.
17. MetricVersion is calculated.
18. Learning Controller interprets result according to the pre-set checkpoint rules.
19. Next Decision supersedes the prior Decision.

## Minimal Entities

Platform:

- User
- Organization
- BusinessMembership
- Role
- PermissionPolicy
- UsageRecord

Business:

- Business
- BusinessGoal
- BusinessConstraint
- Product
- Offer
- ChannelAccount
- ConnectorReadiness

Evidence:

- EvidenceItem
- Claim
- Hypothesis
- InformationNeed
- Conflict

Decision:

- Decision
- DecisionAlternative
- ControllerReview
- BusinessSnapshot

Experiment:

- Experiment
- Checkpoint
- InterpretationRule

Production:

- CreativeBrief
- Asset
- AssetVersion
- AssetReview
- AssetRightsProvenance

Execution:

- ActionProposal
- Approval
- Execution
- ExternalReference
- AuditEvent

Learning:

- BusinessEvent
- MetricVersion
- Learning
- DecisionSupersession

## API Commands

Initial commands:

- `CreateBusiness`
- `SetBusinessGoal`
- `CreateProduct`
- `CreateOffer`
- `ConnectTelegramChannel`
- `CreateLaunch`
- `CreateBusinessSnapshot`
- `RunLaunchDecisionWorkflow`
- `CreateCreativeBrief`
- `CreateAssetVersion`
- `SubmitAssetForReview`
- `CreateActionProposal`
- `ApproveActionProposal`
- `ExecuteApprovedAction`
- `IngestConnectorEvent`
- `CalculateMetricVersion`
- `RunCheckpointInterpretation`
- `CreateLearning`
- `SupersedeDecision`
- `PauseExecution`
- `RevokeAllWriteCapabilities`

## API Queries

Initial queries:

- `GetCommandCenter`
- `GetLaunchRoom`
- `GetUserDecisionView`
- `GetDecisionDetail`
- `GetControllerReviews`
- `GetApprovalQueue`
- `GetApprovalDetail`
- `GetAsset`
- `GetAssetVersions`
- `GetConnectorReadinessMap`
- `GetExecutionStatus`
- `GetMetricSeries`
- `GetCheckpointInterpretation`
- `GetDecisionTimeline`
- `GetAuditTimeline`

## Permission Policy Defaults

Default v11.1 policy:

- external writes require explicit owner approval
- public Telegram publication is approval-required
- edits to draft assets do not require approval
- global pause blocks all execution
- missing connector health blocks execution
- security/privacy/constitutional hard violations block execution

## Controller Matrix

Decision creation:

- Evidence Controller
- Economics Controller
- Constitutional Controller
- Manipulation Controller
- Decision Quality Controller
- Anti-Analysis-Paralysis Controller

Asset review:

- Evidence Controller
- Brand Controller
- Constitutional Controller
- Manipulation Controller
- Legal/Claims Controller
- Production Quality Controller
- Asset Rights/Provenance check

Execution:

- Security Controller
- Privacy Controller
- Platform Controller
- Execution Controller
- Cost Controller

Learning:

- Attribution Controller
- Learning Controller
- Stability Controller

## Data Rules

- Every connector event is idempotent.
- Every external write has an idempotency key.
- Late events apply to event_time.
- Derived metrics are versioned.
- Decisions reference immutable BusinessSnapshots.
- Connector readiness distinguishes missing data from unavailable/stale data.
- LLM outputs cannot create facts without evidence status.

## UI Requirement

The first screen after setup is operational, not a landing page.

v11.1 screens:

- Command Center
- Launch Room
- Decision detail
- Content Studio asset detail
- Approval queue/detail
- Integrations readiness
- Execution/audit status
- Metrics/checkpoint view
- Settings for pause and permissions

## Definition of Done

v11.1 is done when:

- a launch can be created
- a BusinessSnapshot is persisted
- structured specialist contributions are produced
- a valid Decision with selected_action is produced
- required controllers run and can block
- checkpoint/experiment rules are fixed before execution
- one Telegram-ready asset is created and versioned
- approval is required and audited
- Telegram publication executes only through Execution Engine
- external message ID is stored
- at least one external observation is ingested
- metric version is calculated
- learning is created
- next decision supersedes the previous decision
- security and vertical-slice acceptance tests pass
