from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from launch_os_v11.ai_runtime.context import ContextBuilder, ContextReference
from launch_os_v11.ai_runtime.contracts import (
    AgentRunStatus,
    ModelRequest,
    ModelResult,
    ModelResultKind,
    ProviderMetadata,
)
from launch_os_v11.ai_runtime.errors import AIContractError, AIInvalidOutputError
from launch_os_v11.ai_runtime.registry import AgentRegistry
from launch_os_v11.ai_runtime.router import ModelRouter
from launch_os_v11.ai_runtime.service import (
    agent_run_is_terminal,
    assert_agent_definition_parity,
)
from launch_os_v11.domain.exceptions import TenantScopeViolation
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence.models import AgentDefinitionModel, AgentRunModel, JobModel
from launch_os_v11.runtime.clock import Clock
from launch_os_v11.runtime.contracts import RuntimeJobContext
from launch_os_v11.runtime.errors import PermanentJobError
from launch_os_v11.runtime.security import assert_no_secrets, redacted_error_summary


class AgentRunJobHandler:
    def __init__(
        self,
        *,
        registry: AgentRegistry,
        context_builder: ContextBuilder,
        model_router: ModelRouter,
    ) -> None:
        self._registry = registry
        self._context_builder = context_builder
        self._model_router = model_router

    def handle(
        self,
        *,
        context: RuntimeJobContext,
        payload: Mapping[str, object],
        session: Session,
        clock: Clock,
    ) -> None:
        assert_no_secrets(payload)
        agent_run_id = _agent_run_id(payload)
        run = _load_run(session, agent_run_id)
        context.scope.assert_matches(
            organization_id=run.organization_id,
            business_id=run.business_id,
        )
        if run.job_id is not None and run.job_id != context.job_id:
            raise AIContractError("AgentRun is bound to a different Job")
        if agent_run_is_terminal(run):
            return

        definition = session.get(AgentDefinitionModel, run.agent_definition_id)
        if definition is None:
            raise AIContractError("AgentDefinition not found for AgentRun")
        contract = self._registry.resolve(
            contract_key=run.agent_contract_key,
            contract_version=run.agent_contract_version,
        )
        assert_agent_definition_parity(definition, contract)
        if run.agent_contract_fingerprint != contract.fingerprint:
            raise AIContractError("AgentRun contract fingerprint does not match AgentDefinition")

        run.status = AgentRunStatus.RUNNING.value
        run.started_at = clock.now()
        run.completed_at = None
        run.error_class = None
        run.error_summary = None
        run.refusal_summary = None
        session.flush()

        context_refs = _context_refs(run.context_refs)
        context_bundle = self._context_builder.build(
            session=session,
            scope=context.scope,
            contract=contract,
            requested_refs=context_refs,
        )
        run.context_manifest = context_bundle.manifest
        run.context_hash = context_bundle.context_hash

        resolved_route = self._model_router.resolve(contract.model_capability)
        model_request: ModelRequest[BaseModel] = ModelRequest(
            capability=contract.model_capability,
            system_instructions=contract.system_instructions,
            instruction_version=contract.instruction_version,
            structured_context=context_bundle.structured_context,
            context_manifest=context_bundle.manifest,
            context_hash=context_bundle.context_hash,
            output_type=contract.output_model,
            correlation_id=context.correlation_id,
            causation_id=context.causation_id,
            safe_generation_policy="strict_structured_output_no_tools_no_truth_promotion",
        )
        result = resolved_route.adapter.invoke(model_request)
        _persist_model_result(run=run, result=result, clock=clock)
        session.flush()

    def record_attempt_failure(
        self,
        *,
        session: Session,
        job: JobModel,
        error: BaseException,
        will_retry: bool,
        clock: Clock,
        retry_backoff: timedelta,
    ) -> None:
        del retry_backoff
        payload = job.payload
        if not isinstance(payload, dict):
            return
        agent_run_id = payload.get("agent_run_id")
        if not isinstance(agent_run_id, str):
            return
        run = session.get(AgentRunModel, agent_run_id)
        if run is None or agent_run_is_terminal(run):
            return
        job_scope = _job_scope(job)
        try:
            job_scope.assert_matches(
                organization_id=run.organization_id,
                business_id=run.business_id,
            )
        except TenantScopeViolation:
            return
        run.status = AgentRunStatus.RETRY_WAIT.value if will_retry else AgentRunStatus.FAILED.value
        run.error_class = error.__class__.__name__
        run.error_summary = redacted_error_summary(error)
        run.safe_trace_metadata = {
            "schema_name": "AgentRunFailureTrace",
            "schema_version": 1,
            "will_retry": will_retry,
            "job_id": job.id,
            "job_attempt_count": job.attempt_count,
        }
        run.completed_at = None if will_retry else clock.now()
        session.flush()


def _job_scope(job: JobModel) -> TenantScope:
    return TenantScope(
        organization_id=job.organization_id,
        business_id=job.business_id,
    )


def _agent_run_id(payload: Mapping[str, object]) -> str:
    schema_version = payload.get("payload_schema_version")
    if schema_version != 1:
        raise PermanentJobError("ai.run_agent payload_schema_version must be 1")
    agent_run_id = payload.get("agent_run_id")
    if not isinstance(agent_run_id, str):
        raise PermanentJobError("agent_run_id is required")
    return agent_run_id


def _load_run(session: Session, agent_run_id: str) -> AgentRunModel:
    run = session.get(AgentRunModel, agent_run_id)
    if run is None:
        raise PermanentJobError(f"AgentRun not found: {agent_run_id}")
    return run


def _context_refs(value: object) -> tuple[ContextReference, ...]:
    if not isinstance(value, list):
        raise AIContractError("AgentRun context_refs must be a list")
    refs: list[ContextReference] = []
    try:
        for item in value:
            refs.append(ContextReference.model_validate(item))
    except ValidationError as exc:
        raise AIContractError("AgentRun context_refs failed validation") from exc
    return tuple(refs)


def _persist_model_result(
    *,
    run: AgentRunModel,
    result: ModelResult[BaseModel],
    clock: Clock,
) -> None:
    _persist_provider_trace(run=run, metadata=result.metadata)
    if result.kind == ModelResultKind.PARSED:
        if result.parsed_output is None:
            raise AIInvalidOutputError("parsed result missing output object")
        output_data = result.parsed_output.model_dump(mode="json")
        assert_no_secrets(output_data)
        run.status = AgentRunStatus.SUCCEEDED.value
        run.output_data = output_data
        run.output_ref = None
        run.completed_at = clock.now()
        run.safe_trace_metadata = _safe_trace(
            outcome=AgentRunStatus.SUCCEEDED.value,
            metadata=result.metadata,
        )
        return
    if result.kind == ModelResultKind.REFUSAL:
        run.status = AgentRunStatus.REFUSED.value
        run.refusal_summary = _safe_text(result.refusal or "provider refusal")
        run.output_data = None
        run.completed_at = clock.now()
        run.safe_trace_metadata = _safe_trace(
            outcome=AgentRunStatus.REFUSED.value,
            metadata=result.metadata,
        )
        return
    if result.kind in {ModelResultKind.INCOMPLETE, ModelResultKind.INVALID_OUTPUT}:
        reason = result.incomplete_reason or result.invalid_output_reason or "invalid output"
        run.status = AgentRunStatus.INVALID_OUTPUT.value
        run.error_class = result.kind.value
        run.error_summary = _safe_text(reason)
        run.output_data = None
        run.completed_at = clock.now()
        run.safe_trace_metadata = _safe_trace(
            outcome=AgentRunStatus.INVALID_OUTPUT.value,
            metadata=result.metadata,
        )
        return
    raise AIInvalidOutputError(f"unsupported model result kind: {result.kind}")


def _persist_provider_trace(*, run: AgentRunModel, metadata: ProviderMetadata) -> None:
    run.provider_name = metadata.provider_name
    run.provider_model = metadata.model_name
    run.provider_response_id = metadata.response_id
    run.token_usage = dict(metadata.token_usage)
    run.latency_ms = metadata.latency_ms


def _safe_trace(*, outcome: str, metadata: ProviderMetadata) -> dict[str, object]:
    trace = metadata.safe_dict()
    trace["schema_name"] = "AgentRunProviderTrace"
    trace["schema_version"] = 1
    trace["outcome"] = outcome
    assert_no_secrets(trace)
    return trace


def _safe_text(value: str) -> str:
    return redacted_error_summary(RuntimeError(value)).removeprefix("RuntimeError: ")
