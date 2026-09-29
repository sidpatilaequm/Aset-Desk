"""Roles and what each can do. The server enforces these on every request."""

ROLES = ["Admin", "IT Manager", "IT Asset Manager", "Finance", "IT Support", "Employee"]

PERMS: dict[str, set[str]] = {
    "Admin": {"assets.viewAll", "assets.create", "assets.edit", "assets.import", "assets.delete", "depr.edit", "report.view",
              "tickets.viewAll", "tickets.manage", "tickets.raise", "people.manage", "settings.manage", "exits.viewAll",
              "sales.view", "payroll.view"},
    "IT Manager": {"assets.viewAll", "report.view", "tickets.viewAll", "tickets.raise", "exits.viewAll", "exits.itApprove"},
    "IT Asset Manager": {"assets.viewAll", "assets.create", "assets.edit", "assets.assign", "assets.import", "report.view",
                         "tickets.viewAll", "tickets.raise", "exits.viewAll", "returns.receive", "sales.create", "people.add"},
    "Finance": {"assets.viewAll", "depr.edit", "report.view", "tickets.raise", "exits.viewAll", "exits.financeApprove",
                "sales.create", "sales.approve", "payroll.view"},
    "IT Support": {"assets.viewAll", "tickets.viewAll", "tickets.manage", "tickets.raise"},
    "Employee": {"tickets.raise"},
}
OWNER_EXTRA = {"people.manage", "settings.manage"}  # bootstrap admins can never lock themselves out

AGENT_ROLES = {"IT Support", "Admin"}


def norm_role(r: str | None) -> str | None:
    return "IT Asset Manager" if r == "Asset Manager" else r
