from launch_os_v11.domain.exceptions import ApprovalBindingError, TenantScopeViolation
from launch_os_v11.persistence.models import ActionModel, ApprovalModel


def validate_approval_for_action(approval: ApprovalModel, action: ActionModel) -> None:
    if (
        approval.organization_id != action.organization_id
        or approval.business_id != action.business_id
    ):
        msg = "approval and action belong to different tenant/business scopes"
        raise TenantScopeViolation(msg)

    if (
        approval.action_id != action.id
        or approval.action_type != action.action_type
        or approval.object_type != action.target_object_type
        or approval.object_id != action.target_object_id
        or approval.object_version != action.target_object_version
        or approval.object_version_id != action.target_object_version_id
    ):
        msg = "approval is stale or bound to a different object/version/action"
        raise ApprovalBindingError(msg)
