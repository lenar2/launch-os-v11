# Social Connector Fabric

Status: implementation foundation
Verified: 2026-09-16
Parent Factory WorkItem: P009 #833

## Goal

Launch OS targets all meaningful social networks that expose a legitimate official API or
provider-supported integration surface. It must not pretend that every provider exposes the same
read, analytics, messaging, or write capabilities.

The runtime capability state is one of:

- AVAILABLE
- REQUIRES_REVIEW
- READ_ONLY
- WRITE_LIMITED
- USER_HANDOFF_REQUIRED
- UNAVAILABLE

Missing or unavailable data is never encoded as zero.

## Target networks

- Instagram
- Facebook
- Threads
- TikTok
- YouTube
- LinkedIn
- X
- Pinterest
- Telegram
- WhatsApp
- Reddit
- Bluesky
- Mastodon
- Google Business Profile
- Twitch

## Current verified provider evidence

### Telegram

Existing Launch OS implementation already supports:

- Bot API auth/readiness checks
- governed text publication
- message/channel-post observation through getUpdates polling
- typed provider message IDs

Current implementation does not yet expose provider analytics or webhook observation through the
Social Connector Fabric.

Source:

- https://core.telegram.org/bots/api

### TikTok

Official Content Posting API currently supports direct video/photo posting and upload-to-TikTok
handoff. Public direct posting requires an audited client and the required publish scope; unaudited
clients are restricted to private visibility.

Sources:

- https://developers.tiktok.com/docs/en/content-posting-api-get-started
- https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post

Launch OS implication:

- publish/video and publish/image start at REQUIRES_REVIEW until app audit/scopes are proven
- upload/draft may be modeled separately from direct publish

### LinkedIn

Community Management API supports approved page-management use cases including organization posts,
comments/reactions and page/share/video analytics. Access is program-controlled and versioned.

Sources:

- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/comments-api

Launch OS implication:

- capabilities are account/app-access dependent
- API version must be explicit connector state

### YouTube

YouTube Data API supports authenticated video upload. API projects that have not passed the
required audit may have uploads restricted to private visibility.

Source:

- https://developers.google.com/youtube/v3/docs/videos/insert

Launch OS implication:

- video upload/publish capability must include project-audit state
- analytics uses a separate provider surface and must be verified independently

### X

Current X API documentation exposes public and authenticated private/organic/promoted post metrics.
Some non-public metric classes have time-window constraints.

Source:

- https://docs.x.com/x-api/fundamentals/metrics

Launch OS implication:

- analytics capabilities must expose authentication and time-window coverage
- current posting/access/pricing entitlement must be reverified before enabling writes

### Pinterest

Pinterest API exposes account/pin organic analytics and Pin creation/update operations.

Sources:

- https://developer.pinterest.com/docs/content/analytics/
- https://github.com/pinterest/pinterest-python-generated-api-client/blob/main/docs/PinsApi.md

Launch OS implication:

- analytics lookback/coverage constraints are provider state, not missing=zero
- pin publishing can be a typed write capability after OAuth/scopes are proven

### Reddit

Reddit developer surfaces support post/comment creation under user-control constraints. Some
engagement actions are intentionally unavailable to apps, including voting in the user-actions
model.

Sources:

- https://developers.reddit.com/docs/capabilities/server/userActions
- https://developers.reddit.com/docs/api/public-api/classes/RedditClient

Launch OS implication:

- write capabilities are operation-specific
- unsupported engagement actions remain UNAVAILABLE, never simulated

### Bluesky / AT Protocol

AT Protocol supports authenticated record creation for Bluesky posts and public record/feed reads.

Sources:

- https://atproto.com/guides/writing-data
- https://bsky.network/docs/bluesky-api/

Launch OS implication:

- post/reply/quote capabilities can be modeled as typed record writes
- credential/session handling remains inside connector/secrets boundaries

## Provider re-verification required before connector implementation

The following networks remain product targets but require fresh provider-specific verification
before code enables a real account:

- Instagram
- Facebook
- Threads
- WhatsApp
- Mastodon
- Google Business Profile
- Twitch

Meta documentation and permission/app-review rules change frequently; prior Launch OS research
identified the official Instagram Platform entry point, but current connector implementation must
re-verify exact scopes and review requirements.

No provider is marked AVAILABLE merely because a competitor supports it.

## Connector contract

Every implementation must expose:

- account identity
- auth health
- granted scopes
- provider/app-review state
- historical backfill status
- incremental sync health
- freshness
- capability state per operation
- coverage gaps
- rate-limit state
- last provider error

Agents never receive provider credentials or a connector instance.

Canonical write path:

Agent -> ActionProposal -> Controllers -> Permission Policy -> Approval/Policy ->
Execution Engine -> typed SocialActionCommand -> Social Connector -> External system -> audit/event

## Foundation implementation

Implemented by the #833 first slice:

- SocialNetwork
- SocialCapability
- CapabilityState
- SocialDataAvailability
- SocialAccountReadiness
- SocialObservation / SocialObservationPage
- SocialActionCommand / SocialActionResult
- SocialConnector protocol
- SocialConnectorRegistry
- FakeSocialConnector
- TelegramSocialConnectorAdapter

The first slice intentionally does not activate new live provider accounts.