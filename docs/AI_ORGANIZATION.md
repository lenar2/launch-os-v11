# Launch OS v11 AI Organization

Status: canonical pre-code AI architecture
Date: 2026-08-15

## Authority Separation

Orchestrator and Chief Growth Producer are separate authorities.

Orchestrator is system logic:

- routing
- workflow state
- agent activation
- controller matrix
- jobs
- permissions
- retries
- state transitions

Chief Growth Producer is an intellectual business role:

- selects the current working business decision
- weighs specialist contributions
- chooses a selected action among alternatives
- defines the expected effect and checkpoint

They must never be the same authority.

## Agents Are Capabilities

Roles are capabilities, not always-running LLM instances.

An agent is:

- contract
- scoped context
- model policy
- tools
- schemas
- validators
- evals
- trace capture

Agents return structured domain objects, not free-form opinions.

## Universal Agent Contract

Every agent defines:

- mission
- allowed inputs
- required context
- optional context
- output schema
- authority boundaries
- read tools
- prohibited actions
- required controllers
- escalation policy
- abstention policy
- model capability class
- eval suite

## Specialist Capabilities

Strategy:

- Business and Product Analyst
- Audience Intelligence
- Offer and Positioning Strategist
- Revenue and Funnel Strategist
- CRM and Retention Strategist
- Launch Strategist
- Experiment Lead

Channels:

- Instagram Strategist
- Telegram Strategist
- YouTube Strategist
- Email Strategist
- Landing/CRO Strategist
- Performance Strategist

Content and production:

- Content Director
- Copy Chief
- channel writers
- Reel/YouTube Script capabilities
- Creative Director
- Graphic/Social/Carousel/Thumbnail/Landing/Presentation/Motion Design
- Video editing/subtitles/clip selection

Intelligence:

- deterministic-first Data Analyst
- external Research capability

## Controllers

Controllers are independent gates, not extra brainstormers.

Required controllers:

- Evidence Controller
- Attribution Controller
- Economics Controller
- Strategy Red Team
- Brand Controller
- Constitutional Controller
- Manipulation Controller
- Legal/Claims Controller
- Privacy Controller
- Security Controller
- Platform Controller
- Execution Controller
- Decision Quality Controller
- Production Quality Controller
- Anti-Analysis-Paralysis Controller
- Stability Controller
- UX Compression Controller
- Learning Controller
- Cost Controller

Controller verdicts:

- `PASS`
- `PASS_WITH_CONDITIONS`
- `REVISE`
- `BLOCK`

Absolute blocks:

- security violation
- privacy violation
- illegal action
- missing mandatory permission
- constitutional hard violation
- direct agent-to-production-write path
- credential exposure

Conditional blocks may invalidate a claim or asset without blocking the entire campaign.

## AI Runtime

Runtime components:

- Orchestrator
- Agent Registry
- Controller Registry
- Context Builder
- Model Router
- Tool Gateway
- Structured Output Validator
- Cost Tracker
- Trace Recorder
- Evals hooks

Complex tasks run asynchronously. The UI receives progress and final domain objects rather than holding long HTTP requests.

## Model Routing

Agents request capabilities, not hard-coded model names:

- deep reasoning
- standard reasoning
- fast structured classification
- creative copy
- vision
- image generation
- speech-to-text
- embeddings

A ModelAdapter maps capabilities to actual providers and models.

## Tool Gateway

Read operations may be exposed to agents through scoped internal tools.

Write operations cannot be executed directly by an agent.

Write request path:

`tool intent -> ActionProposal -> policy/controllers -> Execution Engine`

Agents never receive credentials.

## Structured Output

Agent and controller outputs must validate against schemas.

Invalid structured output:

- fails closed for write-capable paths
- may be retried for non-write paths
- is recorded in trace/eval data
- cannot silently degrade into an essay

## UX Projection

The default user-facing projection is `UserDecisionView`, not an AI essay.

Fields:

- decision
- 1-3 reasons
- what happens now
- ready assets/actions
- metric/target/current state
- next checkpoint
- approval needed?

Detailed reasoning, alternatives, traces, and controller reviews remain available through progressive disclosure.
