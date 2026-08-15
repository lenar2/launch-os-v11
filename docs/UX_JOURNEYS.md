# Launch OS v11.0E UX and Information Architecture

Status: complete enough for v11.1 vertical slice
Date: 2026-08-15

## UX Principle

Launch OS is a web application, not a chat transcript.

The product should feel like:

"I have an AI operating organization working inside my business."

not:

"I have a very long GPT answer."

## Core IA

Primary navigation:

- Command Center
- Launches
- Social
- Content Studio
- Audience / CRM
- Products
- Campaigns
- Analytics / Experiments
- Decisions
- Approvals
- Automations
- Integrations
- Team
- Settings

Telegram companion surface:

- notifications
- approvals
- urgent alerts
- quick commands
- simple status

## Default Decision Projection

The primary output projection is `UserDecisionView`:

- Decision
- 1-3 reasons
- What happens now
- Ready assets/actions
- Metric/target/current state
- Next checkpoint
- Approval needed?

Deep analysis remains available through progressive disclosure.

## Journey 1: Create Account and Business

User outcome: owner has a Launch OS account, organization, and first business workspace.

Screens:

- Sign up / login
- Create organization
- Create business
- Initial workspace confirmation

Core commands:

- `CreateUser`
- `CreateOrganization`
- `CreateBusiness`
- `CreateBusinessMembership`

Core queries:

- `GetCurrentUser`
- `GetOrganizations`
- `GetBusinessWorkspace`

Acceptance:

- user belongs to exactly one initial organization
- business timezone is captured
- no sample business data is treated as real evidence

## Journey 2: Onboard Goals and Constraints

User outcome: the Business Twin has usable goals, offers, constraints, brand rules, and autonomy baseline.

Screens:

- Business profile
- Goals
- Products/offers
- Brand constraints
- Ethical constraints
- Autonomy and approval policy

Core commands:

- `UpdateBusinessProfile`
- `SetBusinessGoal`
- `CreateProduct`
- `CreateOffer`
- `SetBrandConstraint`
- `SetEthicalConstraint`
- `SetPermissionPolicy`

Core queries:

- `GetBusinessProfile`
- `GetGoals`
- `GetProductsAndOffers`
- `GetPermissionPolicy`

Acceptance:

- no personal-worth fields exist
- constraints are visible to agents/controllers through scoped context
- write actions default to approval-required until explicitly changed

## Journey 3: Connect P0 Systems

User outcome: owner sees what Launch OS can and cannot observe or do.

P0 integrations:

- Telegram
- Instagram
- GetCourse
- current payment systems used by the business

Screens:

- Integrations overview
- Connector detail
- Capability/readiness map
- Sync health
- Coverage gaps

Core commands:

- `StartConnectorAuth`
- `CompleteConnectorAuth`
- `RefreshConnectorAuth`
- `StartInitialBackfill`
- `RunConnectorReconciliation`
- `DisconnectConnector`

Core queries:

- `GetConnectorReadinessMap`
- `GetConnectorCapabilities`
- `GetSyncHealth`
- `GetCoverageGaps`

Acceptance:

- stale connector data is visible as stale
- unavailable metrics are labeled unavailable
- "no sales occurred" is never inferred from a stale payment connector

## Journey 4: Create First Launch

User outcome: launch workspace exists with goal, offer, audience, channel, deadline, and constraints.

Screens:

- Launch list
- Create launch
- Launch Room
- Strategy inputs

Core commands:

- `CreateLaunch`
- `AttachOfferToLaunch`
- `SetLaunchGoal`
- `SetLaunchAudience`
- `SetLaunchChannel`
- `CreateBusinessSnapshot`

Core queries:

- `GetLaunch`
- `GetLaunchRoom`
- `GetBusinessSnapshot`

Acceptance:

- Launch creation creates or references an immutable BusinessSnapshot
- missing critical information is represented as InformationNeed
- low-risk reversible launches can proceed with explicit assumptions

## Journey 5: Receive First Team Decision

User outcome: owner receives a concise decision with provenance and next action.

Screens:

- Command Center
- Launch Room decision panel
- Decision detail
- Alternatives
- Controller reviews

Core commands:

- `RunLaunchDecisionWorkflow`
- `CreateDecision`
- `SupersedeDecision`

Core queries:

- `GetUserDecisionView`
- `GetDecisionDetail`
- `GetDecisionProvenance`
- `GetControllerReviews`

Acceptance:

- selected_action exists
- alternatives are captured
- evidence and assumptions are separated
- constitutional and manipulation gates run

## Journey 6: Inspect and Approve Strategy

User outcome: owner can approve, revise, or block the proposed strategy/action.

Screens:

- Approval queue
- Approval detail
- Policy/autonomy context

Core commands:

- `ApproveActionProposal`
- `RejectActionProposal`
- `RequestRevision`
- `ChangeAutonomyLevel`

Core queries:

- `GetApprovalQueue`
- `GetApprovalDetail`
- `GetActionPolicyDecision`

Acceptance:

- required approval cannot be bypassed by agent output
- revision creates a new version/object
- approval is audited

## Journey 7: Open and Edit Asset

User outcome: owner can inspect, edit, and approve production assets.

Screens:

- Content Studio
- Asset detail
- Asset version history
- Rights/provenance panel
- Brand/truth/quality review

Core commands:

- `CreateCreativeBrief`
- `CreateAsset`
- `CreateAssetVersion`
- `SubmitAssetForReview`
- `ApproveAssetVersion`

Core queries:

- `GetCreativeBrief`
- `GetAsset`
- `GetAssetVersions`
- `GetAssetRightsProvenance`

Acceptance:

- edits create new versions
- approved version is explicit
- rights/provenance is visible
- unsupported claims are blocked or revised

## Journey 8: Approve and Publish

User outcome: approved Telegram publication is executed through the Execution Engine.

Screens:

- Approval detail
- Publication preview
- Execution status
- Audit trail

Core commands:

- `CreateActionProposal`
- `ReviewActionProposal`
- `ApproveExecution`
- `ExecuteAction`

Core queries:

- `GetExecutionStatus`
- `GetActionAuditTrail`
- `GetPublication`

Acceptance:

- no direct agent-to-Telegram write path exists
- execution is idempotent
- Telegram message ID is stored as external reference
- failures are visible and retryable under policy

## Journey 9: Observe Metrics and Checkpoint

User outcome: owner sees observed result, interpretation class, and next checkpoint.

Screens:

- Launch Room metrics
- Experiment detail
- Checkpoint detail
- Learning trace

Core commands:

- `IngestConnectorEvent`
- `CalculateMetricVersion`
- `RunCheckpointInterpretation`
- `CreateLearning`

Core queries:

- `GetExperiment`
- `GetMetricSeries`
- `GetCheckpointInterpretation`
- `GetLearningTrace`

Acceptance:

- late events apply to event_time
- metric versions are visible
- attribution class is explicit
- thresholds are not changed after observing outcomes

## Journey 10: Next Decision Supersedes Previous Decision

User outcome: owner sees why the next decision replaced the previous one.

Screens:

- Decision timeline
- Supersession detail
- Learning context

Core commands:

- `SupersedeDecision`
- `CreateDecisionFromLearning`

Core queries:

- `GetDecisionTimeline`
- `GetSupersessionReason`

Acceptance:

- previous decision remains immutable
- new decision references learning/evidence
- causal claims respect the causality boundary

## Journey 11: Manage Social OS Between Launches

User outcome: ongoing content loop can observe, plan, create, approve, publish, measure, and learn.

Screens:

- Social calendar
- Content memory
- Content analytics
- Opportunity queue

Core commands:

- `CreateContentOpportunity`
- `CreateContentPlan`
- `SchedulePublication`
- `RecordPublicationMetrics`

Core queries:

- `GetContentMemory`
- `GetSocialCalendar`
- `GetContentPerformance`

Acceptance:

- one weak post does not force strategy change
- Stability Controller enforces observation windows
- content metadata includes topic, hook, angle, CTA, format, stage, and downstream outcomes where available

## Journey 12: Adjust Autonomy and Pause Writes

User outcome: owner can change autonomy and stop write actions immediately.

Screens:

- Automations
- Permission policy
- Emergency controls

Core commands:

- `SetAutonomyLevel`
- `PauseAutomation`
- `PauseExecution`
- `RevokeAllWriteCapabilities`

Core queries:

- `GetAutomationStatus`
- `GetPermissionPolicy`

Acceptance:

- pause controls are global and immediate
- paused state blocks execution even after approval
- audit records who paused/resumed

## Journey 13: Inspect Provenance and History

User outcome: owner can understand why an action happened.

Screens:

- Decision detail
- Evidence drawer
- Controller reviews
- Audit timeline

Core queries:

- `GetDecisionProvenance`
- `GetEvidenceUsed`
- `GetAgentTraceSummary`
- `GetAuditTimeline`

Acceptance:

- evidence, assumptions, hypotheses, and unknowns are distinct
- untrusted data is labeled
- detailed traces do not expose secrets
