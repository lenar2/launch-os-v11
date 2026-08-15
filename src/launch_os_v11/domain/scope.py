from dataclasses import dataclass

from launch_os_v11.domain.exceptions import TenantScopeViolation


@dataclass(frozen=True)
class TenantScope:
    organization_id: str
    business_id: str

    def assert_matches(self, *, organization_id: str, business_id: str) -> None:
        if organization_id != self.organization_id or business_id != self.business_id:
            msg = (
                "object scope does not match repository scope: "
                f"expected organization={self.organization_id} business={self.business_id}, "
                f"got organization={organization_id} business={business_id}"
            )
            raise TenantScopeViolation(msg)
