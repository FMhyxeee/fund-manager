"""add decision feedback and reconciliation link tables"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260412_0003"
down_revision = "20260412_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("decision_run_id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("fund_id", sa.Integer(), nullable=True),
        sa.Column("action_index", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column(
            "feedback_status",
            sa.Enum(
                "executed",
                "skipped",
                "deferred",
                name="decision_feedback_status_enum",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("feedback_date", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["decision_run_id"],
            ["decision_run.id"],
            name=op.f("fk_decision_feedback__decision_run_id__decision_run"),
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolio.id"],
            name=op.f("fk_decision_feedback__portfolio_id__portfolio"),
        ),
        sa.ForeignKeyConstraint(
            ["fund_id"],
            ["fund_master.id"],
            name=op.f("fk_decision_feedback__fund_id__fund_master"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decision_feedback")),
    )
    op.create_index(
        op.f("ix_decision_feedback__decision_run_id__action_index"),
        "decision_feedback",
        ["decision_run_id", "action_index"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decision_feedback__portfolio_id__feedback_date"),
        "decision_feedback",
        ["portfolio_id", "feedback_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decision_feedback__fund_id__feedback_date"),
        "decision_feedback",
        ["fund_id", "feedback_date"],
        unique=False,
    )

    op.create_table(
        "decision_transaction_link",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("feedback_id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("match_source", sa.String(length=32), nullable=True),
        sa.Column("match_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["feedback_id"],
            ["decision_feedback.id"],
            name=op.f("fk_decision_transaction_link__feedback_id__decision_feedback"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transaction.id"],
            name=op.f("fk_decision_transaction_link__transaction_id__transaction"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decision_transaction_link")),
        sa.UniqueConstraint(
            "transaction_id",
            name=op.f("uq_decision_transaction_link__transaction_id"),
        ),
    )
    op.create_index(
        op.f("ix_decision_transaction_link__feedback_id"),
        "decision_transaction_link",
        ["feedback_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_decision_transaction_link__feedback_id"),
        table_name="decision_transaction_link",
    )
    op.drop_table("decision_transaction_link")

    op.drop_index(
        op.f("ix_decision_feedback__fund_id__feedback_date"),
        table_name="decision_feedback",
    )
    op.drop_index(
        op.f("ix_decision_feedback__portfolio_id__feedback_date"),
        table_name="decision_feedback",
    )
    op.drop_index(
        op.f("ix_decision_feedback__decision_run_id__action_index"),
        table_name="decision_feedback",
    )
    op.drop_table("decision_feedback")
