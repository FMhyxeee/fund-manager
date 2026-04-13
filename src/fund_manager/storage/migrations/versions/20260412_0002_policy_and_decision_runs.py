"""add policy and decision run tables"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260412_0002"
down_revision = "20260331_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_policy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("policy_name", sa.String(length=128), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("rebalance_threshold_ratio", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column(
            "max_single_position_weight_ratio",
            sa.Numeric(precision=12, scale=6),
            nullable=True,
        ),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolio.id"],
            name=op.f("fk_portfolio_policy__portfolio_id__portfolio"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolio_policy")),
    )
    op.create_index(
        op.f("ix_portfolio_policy__portfolio_id__effective_from"),
        "portfolio_policy",
        ["portfolio_id", "effective_from"],
        unique=False,
    )
    op.create_index(
        op.f("ix_portfolio_policy__run_id"),
        "portfolio_policy",
        ["run_id"],
        unique=False,
    )

    op.create_table(
        "portfolio_policy_target",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("policy_id", sa.Integer(), nullable=False),
        sa.Column("fund_id", sa.Integer(), nullable=False),
        sa.Column("target_weight_ratio", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("min_weight_ratio", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("max_weight_ratio", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("add_allowed", sa.Boolean(), nullable=False),
        sa.Column("trim_allowed", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["fund_id"],
            ["fund_master.id"],
            name=op.f("fk_portfolio_policy_target__fund_id__fund_master"),
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["portfolio_policy.id"],
            name=op.f("fk_portfolio_policy_target__policy_id__portfolio_policy"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolio_policy_target")),
        sa.UniqueConstraint(
            "policy_id",
            "fund_id",
            name=op.f("uq_portfolio_policy_target__policy_id__fund_id"),
        ),
    )
    op.create_index(
        op.f("ix_portfolio_policy_target__policy_id__fund_id"),
        "portfolio_policy_target",
        ["policy_id", "fund_id"],
        unique=False,
    )

    op.create_table(
        "decision_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("policy_id", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("workflow_name", sa.String(length=64), nullable=True),
        sa.Column("decision_date", sa.Date(), nullable=False),
        sa.Column("trigger_source", sa.String(length=32), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("final_decision", sa.String(length=64), nullable=False),
        sa.Column("confidence_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("actions_json", sa.JSON(), nullable=True),
        sa.Column("decision_summary_json", sa.JSON(), nullable=True),
        sa.Column("created_by_agent", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["portfolio_policy.id"],
            name=op.f("fk_decision_run__policy_id__portfolio_policy"),
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolio.id"],
            name=op.f("fk_decision_run__portfolio_id__portfolio"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decision_run")),
    )
    op.create_index(
        op.f("ix_decision_run__portfolio_id__decision_date"),
        "decision_run",
        ["portfolio_id", "decision_date"],
        unique=False,
    )
    op.create_index(op.f("ix_decision_run__run_id"), "decision_run", ["run_id"], unique=False)
    op.create_index(
        op.f("ix_decision_run__workflow_name__decision_date"),
        "decision_run",
        ["workflow_name", "decision_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_decision_run__workflow_name__decision_date"), table_name="decision_run")
    op.drop_index(op.f("ix_decision_run__run_id"), table_name="decision_run")
    op.drop_index(op.f("ix_decision_run__portfolio_id__decision_date"), table_name="decision_run")
    op.drop_table("decision_run")

    op.drop_index(
        op.f("ix_portfolio_policy_target__policy_id__fund_id"),
        table_name="portfolio_policy_target",
    )
    op.drop_table("portfolio_policy_target")

    op.drop_index(op.f("ix_portfolio_policy__run_id"), table_name="portfolio_policy")
    op.drop_index(
        op.f("ix_portfolio_policy__portfolio_id__effective_from"),
        table_name="portfolio_policy",
    )
    op.drop_table("portfolio_policy")
