"""Every RM may act on every CSP in Eko's workspace (No. 234)

24 Nov 2026, the owner: "remove the filter that an RM sees only their own
KOs — any RM can send a link to any CSP or KO, edit their details or photo,
send the link or send documents."

This is the Feature access choice "which CSPs" for the built-in RM role
(No. 206), set to "all" for Eko's workspace (slug sbi-kiosk-csp) and written
to the settings history like a change made on the screen, so the Super Admin
sees it there and can set it back to "own" on Setup → Feature access. Other
workspaces keep their own choice (default: own).

Data only; downgrade puts "own" back.

Revision ID: a9c1e3f5b7d0
Revises: f8b0c2d4e6a9
"""
import sqlalchemy as sa
from alembic import op

revision = "a9c1e3f5b7d0"
down_revision = "f8b0c2d4e6a9"
branch_labels = None
depends_on = None

EKO = "sbi-kiosk-csp"
BY = "No. 234 (owner's request, 24 Nov 2026)"


def _set(scope: str, old: str) -> None:
    bind = op.get_bind()
    ws = bind.execute(sa.text("SELECT id FROM workspaces WHERE slug = :s"),
                      {"s": EKO}).scalar()
    if ws is None:
        return
    bind.execute(sa.text("""
        INSERT INTO access_roles (workspace_id, key, name, base_role,
                                  record_scope, created_by)
        VALUES (:w, 'rm', 'RM', 'rm', :scope, :by)
        ON CONFLICT (workspace_id, key)
        DO UPDATE SET record_scope = :scope, updated_at = now()
    """), {"w": ws, "scope": scope, "by": BY})
    bind.execute(sa.text("""
        INSERT INTO workspace_setting_changes
            (workspace_id, key, old_value, new_value, changed_by, via, note)
        VALUES (:w, 'role:rm', CAST(:old AS JSONB), CAST(:new AS JSONB),
                :by, 'screen', :note)
    """), {"w": ws, "by": BY,
           "old": '{"name": "RM", "record_scope": "%s"}' % old,
           "new": '{"name": "RM", "record_scope": "%s"}' % scope,
           "note": "Every RM may act on every CSP (No. 234)"})


def upgrade() -> None:
    _set("all", "own")


def downgrade() -> None:
    _set("own", "all")
