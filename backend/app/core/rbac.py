from enum import Enum
import logging
from typing import Dict, List, Set
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


class Role(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"
    AGENT = "agent"


class Permission(str, Enum):
    # Read permissions
    READ_PROJECT = "read:project"
    READ_STATE = "read:state"
    READ_EVIDENCE = "read:evidence"
    READ_MEETING = "read:meeting"
    READ_CONFLICT = "read:conflict"
    READ_AGENT_RUN = "read:agent_run"
    READ_AUDIT = "read:audit"

    # Write / execution permissions
    PROPOSE_STATE_CHANGE = "propose:state_change"
    RUN_AGENTS = "run:agents"
    SYNC_CONNECTORS = "sync:connectors"

    # Administrative permissions (Restricted)
    APPROVE_STATE_CHANGE = "approve:state_change"
    RESOLVE_CONFLICT = "resolve:conflict"
    MANAGE_CONNECTORS = "manage:connectors"
    MANAGE_ROLES = "manage:roles"


# Strict Role-to-Permissions Mapping
ROLE_PERMISSIONS: Dict[Role, Set[Permission]] = {
    Role.VIEWER: {
        Permission.READ_PROJECT,
        Permission.READ_STATE,
        Permission.READ_EVIDENCE,
        Permission.READ_MEETING,
        Permission.READ_CONFLICT,
        Permission.READ_AGENT_RUN,
    },
    Role.MEMBER: {
        Permission.READ_PROJECT,
        Permission.READ_STATE,
        Permission.READ_EVIDENCE,
        Permission.READ_MEETING,
        Permission.READ_CONFLICT,
        Permission.READ_AGENT_RUN,
        Permission.PROPOSE_STATE_CHANGE,
        Permission.RUN_AGENTS,
        Permission.SYNC_CONNECTORS,
    },
    Role.ADMIN: {
        Permission.READ_PROJECT,
        Permission.READ_STATE,
        Permission.READ_EVIDENCE,
        Permission.READ_MEETING,
        Permission.READ_CONFLICT,
        Permission.READ_AGENT_RUN,
        Permission.READ_AUDIT,
        Permission.PROPOSE_STATE_CHANGE,
        Permission.RUN_AGENTS,
        Permission.SYNC_CONNECTORS,
        Permission.APPROVE_STATE_CHANGE,
        Permission.RESOLVE_CONFLICT,
        Permission.MANAGE_CONNECTORS,
    },
    Role.OWNER: {
        # Owners hold all permissions
        perm for perm in Permission
    },
    Role.AGENT: {
        # AI agents have machine execution rights, but CANNOT self-approve state or resolve conflicts!
        Permission.READ_PROJECT,
        Permission.READ_STATE,
        Permission.READ_EVIDENCE,
        Permission.READ_MEETING,
        Permission.READ_CONFLICT,
        Permission.PROPOSE_STATE_CHANGE,
        Permission.RUN_AGENTS,
    },
}


def check_permission(role: str, permission: Permission) -> bool:
    """
    Check if a given role string possesses the required permission.
    """
    try:
        role_enum = Role(role.lower())
    except ValueError:
        logger.warning(f"Unknown role '{role}' attempted permission check for '{permission}'.")
        return False
    return permission in ROLE_PERMISSIONS.get(role_enum, set())


def enforce_permission(role: str, permission: Permission) -> None:
    """
    Raise HTTP 403 Forbidden if the role does not have the specified permission.
    """
    if not check_permission(role, permission):
        logger.warning(f"Access denied: role '{role}' lacks permission '{permission.value}'.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: role '{role}' lacks permission '{permission.value}'.",
        )


def verify_tenant_access(requested_tenant_id: str, resource_tenant_id: str) -> None:
    """
    Strict Tenant Isolation Check.
    Raises HTTP 403 Forbidden if a tenant attempts to access or mutate another tenant's data.
    """
    if requested_tenant_id != resource_tenant_id:
        logger.error(
            f"SECURITY ALERT: Cross-tenant access attempt detected! "
            f"Requester tenant '{requested_tenant_id}' tried to access resource of tenant '{resource_tenant_id}'."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Cross-tenant access violation. Access denied.",
        )
