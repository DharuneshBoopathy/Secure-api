"""Organization membership: create/list orgs, join requests, owner
approval/rejection, role changes, rename, and ownership transfer.

Distinct from app.deps.get_org_context / require_org_role, which resolve
"which org does *this* resource request act on" via the X-Org-Id header.
These routes instead take org_id from the URL path — you're managing a
specific, named organization, not asking which one applies to a traffic
query — so authorization here is a direct membership lookup rather than
the header-based dependency.
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Organization, OrgMembership, User
from app.routers.auth import limiter
from app.schemas import (
    OrgCreateIn,
    OrgMembershipOut,
    OrgMembershipRoleIn,
    OrgOut,
    OrgRenameIn,
    OrgTransferOwnershipIn,
)
from app.security import OrgRole, is_platform_admin, is_super_admin, utc_now
from app.services.audit_service import log_audit_event

router = APIRouter(prefix="/orgs", tags=["orgs"])

_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str, db: Session) -> str:
    base = _SLUG_STRIP_RE.sub("-", name.lower()).strip("-") or "org"
    slug = base
    n = 1
    while db.query(Organization).filter(Organization.slug == slug).one_or_none() is not None:
        n += 1
        slug = f"{base}-{n}"
    return slug


def _get_membership(db: Session, user_id: int, org_id: int) -> OrgMembership | None:
    return (
        db.query(OrgMembership)
        .filter(OrgMembership.user_id == user_id, OrgMembership.org_id == org_id)
        .one_or_none()
    )


def _require_owner(db: Session, current_user: User, org_id: int) -> None:
    """Platform admins may manage any org (support access); everyone else
    needs an active owner membership in this specific org."""
    if is_platform_admin(current_user.role):
        return
    m = _get_membership(db, current_user.id, org_id)
    if m is None or m.status != "active" or OrgRole(m.role) < OrgRole.OWNER:
        raise HTTPException(status_code=403, detail="Requires org owner role")


def _require_member(db: Session, current_user: User, org_id: int) -> OrgMembership | None:
    """Read access to an org: any active member, or a platform admin.

    Weaker than _require_owner on purpose — seeing who else is in your own
    organization is not an administrative act, and gating it at owner meant an
    org's own editors and viewers got a 403 on their own roster. Returns the
    caller's membership, or None for a platform admin acting cross-org.
    """
    m = _get_membership(db, current_user.id, org_id)
    if m is not None and m.status == "active":
        return m
    if is_platform_admin(current_user.role):
        return None
    raise HTTPException(status_code=403, detail="Requires active membership in this organization")


def _get_org_or_404(db: Session, org_id: int) -> Organization:
    org = db.query(Organization).filter(Organization.id == org_id).one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.post("", status_code=201)
@limiter.limit("10/minute")
def create_org(
    request: Request,
    body: OrgCreateIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrgOut:
    """Create a new organization. The caller becomes its owner."""
    org = Organization(name=body.name, slug=_slugify(body.name, db), owner_user_id=current_user.id)
    db.add(org)
    db.flush()
    db.add(OrgMembership(user_id=current_user.id, org_id=org.id, role="owner", status="active", decided_at=utc_now()))
    db.commit()
    db.refresh(org)
    log_audit_event(
        db,
        event_type="org_created",
        actor=current_user.username,
        target=f"org/{org.id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        details={"name": org.name},
    )
    return OrgOut(
        id=org.id, name=org.name, slug=org.slug, owner_user_id=org.owner_user_id,
        created_at=org.created_at, my_role="owner",
    )


@router.get("")
def list_my_orgs(
    scope: str = Query(default="mine", pattern=r"^(mine|all)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[OrgOut]:
    """Organizations the caller has active membership in.

    ``scope=all`` instead returns every organization on the platform, with
    member and pending-request counts — the super admin's cross-tenant view.
    Ordinary members have no way to enumerate orgs they don't belong to.
    """
    if scope == "all":
        return _list_all_orgs(db, current_user)

    rows = (
        db.query(Organization, OrgMembership)
        .join(OrgMembership, OrgMembership.org_id == Organization.id)
        .filter(OrgMembership.user_id == current_user.id, OrgMembership.status == "active")
        .order_by(Organization.created_at)
        .all()
    )
    return [
        OrgOut(
            id=org.id, name=org.name, slug=org.slug, owner_user_id=org.owner_user_id,
            created_at=org.created_at, my_role=membership.role,
        )
        for org, membership in rows
    ]


def _list_all_orgs(db: Session, current_user: User) -> list[OrgOut]:
    """Every org plus its counts, for the super admin only.

    The counts come from two grouped queries rather than a per-org lookup, so
    this stays at a fixed number of round trips however many orgs exist.
    """
    if not is_super_admin(current_user.role):
        raise HTTPException(status_code=403, detail="Requires the super admin role")

    orgs = db.query(Organization).order_by(Organization.created_at).all()

    counts: dict[int, dict[str, int]] = {}
    for org_id, status, total in (
        db.query(OrgMembership.org_id, OrgMembership.status, func.count(OrgMembership.id))
        .group_by(OrgMembership.org_id, OrgMembership.status)
        .all()
    ):
        counts.setdefault(org_id, {})[status] = total

    owner_ids = {o.owner_user_id for o in orgs}
    owner_names = (
        {u.id: u.username for u in db.query(User).filter(User.id.in_(owner_ids)).all()}
        if owner_ids
        else {}
    )
    my_roles = {
        m.org_id: m.role
        for m in db.query(OrgMembership)
        .filter(OrgMembership.user_id == current_user.id, OrgMembership.status == "active")
        .all()
    }

    return [
        OrgOut(
            id=org.id,
            name=org.name,
            slug=org.slug,
            owner_user_id=org.owner_user_id,
            created_at=org.created_at,
            my_role=my_roles.get(org.id),
            # The owner row can be missing if the account was hard-deleted;
            # the org itself is still real and must still be listed.
            owner_username=owner_names.get(org.owner_user_id),
            member_count=counts.get(org.id, {}).get("active", 0),
            pending_count=counts.get(org.id, {}).get("pending", 0),
        )
        for org in orgs
    ]


@router.post("/{org_id}/join-requests", status_code=201)
@limiter.limit("10/minute")
def request_to_join(
    request: Request,
    org_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrgMembershipOut:
    """Request to join an organization. Grants no access until an owner
    approves — see POST /{org_id}/members/{user_id}/approve."""
    _get_org_or_404(db, org_id)
    existing = _get_membership(db, current_user.id, org_id)
    if existing is not None:
        if existing.status == "active":
            raise HTTPException(status_code=409, detail="Already a member")
        if existing.status == "pending":
            raise HTTPException(status_code=409, detail="Join request already pending")
        # A previously revoked membership can request again.
        existing.status = "pending"
        existing.role = "viewer"
        existing.decided_at = None
        db.commit()
        db.refresh(existing)
        row = existing
    else:
        row = OrgMembership(user_id=current_user.id, org_id=org_id, role="viewer", status="pending")
        db.add(row)
        db.commit()
        db.refresh(row)
    log_audit_event(
        db,
        event_type="org_join_requested",
        actor=current_user.username,
        target=f"org/{org_id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    return OrgMembershipOut(
        id=row.id, user_id=row.user_id, username=current_user.username, org_id=row.org_id,
        role=row.role, status=row.status, created_at=row.created_at, decided_at=row.decided_at,
    )


@router.get("/{org_id}/members")
def list_members(
    org_id: int,
    status_filter: str | None = Query(default=None, alias="status", pattern=r"^(pending|active|revoked)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[OrgMembershipOut]:
    """List members of an organization (any active member, or a platform admin).

    Approving, rejecting, re-roling and removing members all remain
    owner-only — this is the read half.
    """
    _get_org_or_404(db, org_id)
    _require_member(db, current_user, org_id)
    q = (
        db.query(OrgMembership, User)
        .join(User, User.id == OrgMembership.user_id)
        .filter(OrgMembership.org_id == org_id)
    )
    if status_filter:
        q = q.filter(OrgMembership.status == status_filter)
    rows = q.order_by(OrgMembership.created_at).all()
    return [
        OrgMembershipOut(
            id=m.id, user_id=m.user_id, username=u.username, org_id=m.org_id,
            role=m.role, status=m.status, created_at=m.created_at, decided_at=m.decided_at,
        )
        for m, u in rows
    ]


@router.post("/{org_id}/members/{user_id}/approve")
def approve_member(
    request: Request,
    org_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrgMembershipOut:
    """Approve a pending join request (owner or platform admin only)."""
    _require_owner(db, current_user, org_id)
    m = _get_membership(db, user_id, org_id)
    if m is None or m.status != "pending":
        raise HTTPException(status_code=404, detail="No pending join request for this user")
    m.status = "active"
    m.decided_at = utc_now()
    db.commit()
    db.refresh(m)
    target_user = db.query(User).filter(User.id == user_id).one()
    log_audit_event(
        db,
        event_type="org_member_approved",
        actor=current_user.username,
        target=f"org/{org_id}/user/{user_id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    return OrgMembershipOut(
        id=m.id, user_id=m.user_id, username=target_user.username, org_id=m.org_id,
        role=m.role, status=m.status, created_at=m.created_at, decided_at=m.decided_at,
    )


@router.post("/{org_id}/members/{user_id}/reject")
def reject_member(
    request: Request,
    org_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Reject a pending join request (owner or platform admin only)."""
    _require_owner(db, current_user, org_id)
    m = _get_membership(db, user_id, org_id)
    if m is None or m.status != "pending":
        raise HTTPException(status_code=404, detail="No pending join request for this user")
    m.status = "revoked"
    m.decided_at = utc_now()
    db.commit()
    log_audit_event(
        db,
        event_type="org_member_rejected",
        actor=current_user.username,
        target=f"org/{org_id}/user/{user_id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    return {"rejected": True}


@router.patch("/{org_id}/members/{user_id}")
def update_member(
    request: Request,
    org_id: int,
    user_id: int,
    body: OrgMembershipRoleIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrgMembershipOut:
    """Change an active member's role (owner or platform admin only)."""
    _require_owner(db, current_user, org_id)
    m = _get_membership(db, user_id, org_id)
    if m is None or m.status != "active":
        raise HTTPException(status_code=404, detail="No active membership for this user")
    m.role = body.role
    db.commit()
    db.refresh(m)
    target_user = db.query(User).filter(User.id == user_id).one()
    log_audit_event(
        db,
        event_type="org_member_role_changed",
        actor=current_user.username,
        target=f"org/{org_id}/user/{user_id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        details={"new_role": body.role},
    )
    return OrgMembershipOut(
        id=m.id, user_id=m.user_id, username=target_user.username, org_id=m.org_id,
        role=m.role, status=m.status, created_at=m.created_at, decided_at=m.decided_at,
    )


@router.delete("/{org_id}/members/{user_id}", status_code=204)
def remove_member(
    request: Request,
    org_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Remove an active member (owner or platform admin only). The
    membership row is kept with status="revoked" for audit history."""
    _require_owner(db, current_user, org_id)
    org = _get_org_or_404(db, org_id)
    if org.owner_user_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot remove the organization owner — transfer ownership first")
    m = _get_membership(db, user_id, org_id)
    if m is None or m.status != "active":
        raise HTTPException(status_code=404, detail="No active membership for this user")
    m.status = "revoked"
    m.decided_at = utc_now()
    db.commit()
    log_audit_event(
        db,
        event_type="org_member_removed",
        actor=current_user.username,
        target=f"org/{org_id}/user/{user_id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )


@router.patch("/{org_id}")
def rename_org(
    request: Request,
    org_id: int,
    body: OrgRenameIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrgOut:
    _require_owner(db, current_user, org_id)
    org = _get_org_or_404(db, org_id)
    org.name = body.name
    db.commit()
    db.refresh(org)
    log_audit_event(
        db,
        event_type="org_renamed",
        actor=current_user.username,
        target=f"org/{org_id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        details={"new_name": body.name},
    )
    m = _get_membership(db, current_user.id, org_id)
    return OrgOut(
        id=org.id, name=org.name, slug=org.slug, owner_user_id=org.owner_user_id,
        created_at=org.created_at, my_role=m.role if m else "owner",
    )


@router.post("/{org_id}/transfer-ownership")
def transfer_ownership(
    request: Request,
    org_id: int,
    body: OrgTransferOwnershipIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrgOut:
    """Transfer ownership to another active member. The prior owner is
    demoted to editor, not removed."""
    _require_owner(db, current_user, org_id)
    org = _get_org_or_404(db, org_id)
    new_owner_membership = _get_membership(db, body.new_owner_user_id, org_id)
    if new_owner_membership is None or new_owner_membership.status != "active":
        raise HTTPException(status_code=404, detail="Target user has no active membership in this organization")

    prior_owner_id = org.owner_user_id
    prior_owner_membership = _get_membership(db, prior_owner_id, org_id)
    if prior_owner_membership is not None:
        prior_owner_membership.role = "editor"

    new_owner_membership.role = "owner"
    org.owner_user_id = body.new_owner_user_id
    db.commit()
    db.refresh(org)
    log_audit_event(
        db,
        event_type="org_ownership_transferred",
        actor=current_user.username,
        target=f"org/{org_id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        details={"new_owner_user_id": body.new_owner_user_id, "prior_owner_user_id": prior_owner_id},
    )
    return OrgOut(
        id=org.id, name=org.name, slug=org.slug, owner_user_id=org.owner_user_id,
        created_at=org.created_at, my_role="owner",
    )
