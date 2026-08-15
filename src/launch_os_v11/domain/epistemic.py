from launch_os_v11.domain.enums import EpistemicStatus, VerificationBasis
from launch_os_v11.domain.exceptions import InvalidEpistemicTransition


def transition_epistemic_status(
    current: EpistemicStatus,
    target: EpistemicStatus,
    *,
    basis: VerificationBasis,
    evidence_ids: tuple[str, ...] = (),
) -> EpistemicStatus:
    if current == target:
        return target

    if target == EpistemicStatus.FACT:
        if basis == VerificationBasis.MODEL_CONFIDENCE:
            msg = "model confidence cannot promote any epistemic object to FACT"
            raise InvalidEpistemicTransition(msg)
        if not evidence_ids:
            msg = "FACT promotion requires durable evidence references"
            raise InvalidEpistemicTransition(msg)
        allowed_fact_sources = {
            EpistemicStatus.OBSERVATION,
            EpistemicStatus.DERIVED_FACT,
            EpistemicStatus.ASSUMPTION,
        }
        if current not in allowed_fact_sources:
            msg = f"{current} cannot transition directly to FACT"
            raise InvalidEpistemicTransition(msg)

    allowed: set[tuple[EpistemicStatus, EpistemicStatus]] = {
        (EpistemicStatus.UNKNOWN, EpistemicStatus.OBSERVATION),
        (EpistemicStatus.UNKNOWN, EpistemicStatus.ASSUMPTION),
        (EpistemicStatus.UNKNOWN, EpistemicStatus.HYPOTHESIS),
        (EpistemicStatus.OBSERVATION, EpistemicStatus.FACT),
        (EpistemicStatus.OBSERVATION, EpistemicStatus.CONFLICT),
        (EpistemicStatus.ASSUMPTION, EpistemicStatus.FACT),
        (EpistemicStatus.ASSUMPTION, EpistemicStatus.REJECTED),
        (EpistemicStatus.HYPOTHESIS, EpistemicStatus.REJECTED),
        (EpistemicStatus.HYPOTHESIS, EpistemicStatus.INVALIDATED),
        (EpistemicStatus.FACT, EpistemicStatus.INVALIDATED),
        (EpistemicStatus.DERIVED_FACT, EpistemicStatus.FACT),
        (EpistemicStatus.DERIVED_FACT, EpistemicStatus.INVALIDATED),
        (EpistemicStatus.CONFLICT, EpistemicStatus.REJECTED),
        (EpistemicStatus.CONFLICT, EpistemicStatus.INVALIDATED),
    }
    if (current, target) not in allowed:
        msg = f"invalid epistemic transition: {current} -> {target}"
        raise InvalidEpistemicTransition(msg)
    return target
