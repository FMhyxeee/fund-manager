"""simplify schema to ledger and watchlist core"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260418_0004"
down_revision = "20260412_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("decision_transaction_link")
    op.drop_table("decision_feedback")
    op.drop_table("decision_run")
    op.drop_table("portfolio_policy_target")
    op.drop_table("portfolio_policy")
    op.drop_table("review_report")
    op.drop_table("strategy_proposal")
    op.drop_table("agent_debate_log")
    op.drop_table("system_event_log")
    op.drop_table("portfolio_snapshot")

    op.create_table(
        "watchlist_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fund_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("style_tags_json", sa.JSON(), nullable=True),
        sa.Column("risk_level", sa.String(length=64), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source_name", sa.String(length=64), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["fund_id"],
            ["fund_master.id"],
            name=op.f("fk_watchlist_item__fund_id__fund_master"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watchlist_item")),
        sa.UniqueConstraint("fund_id", name=op.f("uq_watchlist_item__fund_id")),
    )
    op.create_index(
        op.f("ix_watchlist_item__removed_at"),
        "watchlist_item",
        ["removed_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_watchlist_item__category"),
        "watchlist_item",
        ["category"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_watchlist_item__category"), table_name="watchlist_item")
    op.drop_index(op.f("ix_watchlist_item__removed_at"), table_name="watchlist_item")
    op.drop_table("watchlist_item")
