from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from launch_os_v11.ai_runtime.context import ContextReference
from launch_os_v11.ai_runtime.contracts import AgentContract, AgentRunStatus
from launch_os_v11.ai_runtime.errors import AIContractError
from launch_os_v11.ai_runtime.registry import AgentRegistry
from launch_os_v11.domain.ids import new_id
from launch_os_v11.domain.scope import TenantScope
from launch_os_v11.persistence.models import AgentDefinitionModel, AgentRunModel
from launch_os_v11.runtime.clock import Clock
from launch_os_v11.runtime.contracts import JOB_TYPE_AI_RUN_AGENT
from launch_os_v11.runtime.repositories import create_job
from launch_os_v11.runtime.transport import JobQueue

TERMINAL_AGENT_RUN_STATUSES = {
    AgentRunStatus.SUCCEEDED.value,
    AgentRunStatus.REFUSED.value,
    AgentRunStatus.INVALID_OUTPUT.value,
    AgentRunStatus.FAILED.value,
}


@dataclass(frozen=True)
class AgentRunCreationResult:
    agent_run: AgentRunModel
    job_id: str
    created: bool


class AgentRunService:
    def __init__(
        self,
        *,
        registry: AgentRegistry,
        queue: JobQueue,
        clock: Clock,
    ) -> None:
        self._registry = registry
        self._queue = queue
        self._clock = clock

    def create_agent_run(
        self,
        session: Session,
        *,
        scope: TenantScope,
        contract_key: str,
        contract_version: int,
        input_ref: str | None = None,
        context_refs: tuple[ContextReference, ...] = (),
        correlation_id: str | None = None,
        causation_id: str | None = None,
        job_type: str = JOB_TYPE_AI_RUN_AGENT,
        idempotency_key: str | None = None,
    ) -> AgentRunCreationResult:
        contract = self._registry.resolve(
            contract_key=contract_key,
            contract_version=contract_version,
        )
        definition = ensure_agent_definition(
            session,
            scope=scope,
            contract=contract,
        )
        if idempotency_key is not None:
            existing = session.scalar(
                select(AgentRunModel).where(
                    AgentRunModel.organization_id == scope.organization_id,
                    AgentRunModel.business_id == scope.business_id,
                    AgentRunModel.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.job_id is None:
                    raise AIContractError("idempotent AgentRun exists without a Job binding")
                return AgentRunCreationResult(
                    agent_run=existing,
                    job_id=existing.job_id,
                    created=False,
                )
        run_id = new_id()
        run = AgentRunModel(
            id=run_id,
            organization_id=scope.organization_id,
            business_id=scope.business_id,
            agent_definition_id=definition.id,
            payload_schema_version=1,
            agent_contract_key=contract.contract_key,
            agent_contract_version=contract.contract_version,
            agent_contract_fingerprint=contract.fingerprint,
            output_schema_name=contract.output_schema_name,
            output_schema_version=contract.output_schema_version,
            status=AgentRunStatus.QUEUED.value,
            input_ref=input_ref,
            output_ref=None,
            context_refs=[ref.model_dump(mode="json") for ref in context_refs],
            context_manifest={},
            context_hash=None,
            output_data=None,
            refusal_summary=None,
            error_class=None,
            error_summary=None,
            provider_name=None,
            provider_model=None,
            provider_response_id=None,
            token_usage={},
            latency_ms=None,
            safe_trace_metadata={},
            started_at=None,
            completed_at=None,
            correlation_id=correlation_id,
            causation_id=causation_id,
            idempotency_key=idempotency_key,
        )
        session.add(run)
        session.flush()
        job = create_job(
            session,
            scope=scope,
            job_type=job_type,
            payload={"agent_run_id": run.id, "payload_schema_version": 1},
            payload_schema_version=1,
            idempotency_key=f"agent_run:{run.id}",
            clock=self._clock,
            max_attempts=3,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        run.job_id = job.id
        session.flush()
        self._queue.enqueue(job.id)
        return AgentRunCreationResult(agent_run=run, job_id=job.id, created=True)


def ensure_agent_definition(
    session: Session,
    *,
    scope: TenantScope,
    contract: AgentContract,
) -> AgentDefinitionModel:
    existing = session.scalar(
        select(AgentDefinitionModel).where(
            AgentDefinitionModel.organization_id == scope.organization_id,
            AgentDefinitionModel.business_id == scope.business_id,
            AgentDefinitionModel.contract_key == contract.contract_key,
            AgentDefinitionModel.contract_version == contract.contract_version,
        )
    )
    if existing is not None:
        if existing.contract_fingerprint != contract.fingerprint:
            raise AIContractError(
                "durable AgentDefinition fingerprint does not match code contract"
            )
        return existing

    definition = AgentDefinitionModel(
        id=new_id(),
        organization_id=scope.organization_id,
        business_id=scope.business_id,
        name=contract.role_name,
        mission=contract.mission,
        output_schema=contract.output_model.model_json_schema(),
        enabled=True,
        contract_key=contract.contract_key,
        contract_version=contract.contract_version,
        role_name=contract.role_name,
        model_capability=contract.model_capability.value,
        allowed_context_types=list(contract.allowed_context_types),
        required_context_types=list(contract.required_context_types),
        authority_boundaries=[authority.value for authority in contract.authority_boundaries],
        prohibited_actions=list(contract.prohibited_actions),
        required_controller_types=list(contract.required_controller_types),
        abstention_policy=contract.abstention_policy,
        escalation_policy=contract.escalation_policy,
        instruction_version=contract.instruction_version,
        eval_suite_identifier=contract.eval_suite_identifier,
        contract_fingerprint=contract.fingerprint,
        output_schema_name=contract.output_schema_name,
        output_schema_version=contract.output_schema_version,
    )
    session.add(definition)
    session.flush()
    return definition


def assert_agent_definition_parity(
    definition: AgentDefinitionModel,
    contract: AgentContract,
) -> None:
    expected = {
        "contract_key": contract.contract_key,
        "contract_version": contract.contract_version,
        "role_name": contract.role_name,
        "mission": contract.mission,
        "model_capability": contract.model_capability.value,
        "output_schema_name": contract.output_schema_name,
        "output_schema_version": contract.output_schema_version,
        "contract_fingerprint": contract.fingerprint,
    }
    actual = {
        "contract_key": definition.contract_key,
        "contract_version": definition.contract_version,
        "role_name": definition.role_name,
        "mission": definition.mission,
        "model_capability": definition.model_capability,
        "output_schema_name": definition.output_schema_name,
        "output_schema_version": definition.output_schema_version,
        "contract_fingerprint": definition.contract_fingerprint,
    }
    if actual != expected:
        raise AIContractError("durable AgentDefinition does not match exact code contract")
    if not definition.enabled:
        raise AIContractError("AgentDefinition is disabled")


def agent_run_is_terminal(run: AgentRunModel) -> bool:
    return run.status in TERMINAL_AGENT_RUN_STATUSES
