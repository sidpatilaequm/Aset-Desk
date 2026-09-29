from dataclasses import dataclass, field
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .models import User, Setting
from .perms import PERMS, OWNER_EXTRA, ROLES, norm_role

DEFAULT_CONFIG = {
    "microsoft": {"enabled": True, "domain": "", "tenantId": "", "defaultRole": "Employee", "groupRoles": ""},
    "google": {"enabled": True, "domain": "", "defaultRole": "Employee"},
    "currency": "INR", "fyStartMonth": 4, "defaultMethod": "SL",
}


def get_config(db: Session) -> dict:
    row = db.get(Setting, "directory")
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_CONFIG.items()}
    if row and isinstance(row.value, dict):
        for k, v in row.value.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k] = {**cfg[k], **v}
            else:
                cfg[k] = v
    return cfg


def is_bootstrap_admin(user: User) -> bool:
    return user.email.lower() in settings.admin_emails


def role_of(user: User, cfg: dict) -> str:
    r = norm_role(user.role)
    if r in ROLES:
        return r
    if is_bootstrap_admin(user):
        return "Admin"
    prov = cfg.get(user.provider or "", {}) if isinstance(cfg.get(user.provider or ""), dict) else {}
    d = norm_role(prov.get("defaultRole"))
    return d if d in ROLES else "Employee"


@dataclass
class CurrentUser:
    user: User
    role: str
    perms: set = field(default_factory=set)
    is_owner: bool = False

    @property
    def id(self) -> str:
        return self.user.id

    def can(self, p: str) -> bool:
        return p in self.perms

    def require(self, *ps: str):
        if not any(p in self.perms for p in ps):
            raise HTTPException(403, "Your role can't do this.")


def current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    uid = request.session.get("uid")
    user = db.get(User, uid) if uid else None
    if not user:
        raise HTTPException(401, "Sign in to continue.")
    cfg = get_config(db)
    role = role_of(user, cfg)
    owner = is_bootstrap_admin(user)
    perms = set(PERMS.get(role, set())) | (OWNER_EXTRA if owner else set())
    return CurrentUser(user=user, role=role, perms=perms, is_owner=owner)
