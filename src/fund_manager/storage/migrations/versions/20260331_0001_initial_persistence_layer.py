"""initial persistence layer"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260331_0001"
down_revision = None
branch_labels = None
depends_on = None


transaction_type_enum = sa.Enum(
    "buy",
    "sell",
    "dividend",
    "convert_in",
    "convert_out",
    "adjust",
    name="transaction_type_enum",
    native_enum=False,
    length=32,
)

report_period_type_enum = sa.Enum(
    "daily",
    "weekly",
    "monthly",
    name="report_period_type_enum",
    native_enum=False,
    length=16,
)


def upgrade() -> None:
    op.create_table(
        "fund_master",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fund_code", sa.String(length=32), nullable=False),
        sa.Column("fund_name", sa.String(length=255), nullable=False),
        sa.Column("fund_type", sa.String(length=64), nullable=True),
        sa.Column("base_currency_code", sa.String(length=3), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=True),
        sa.Column("manager_name", sa.String(length=255), nullable=True),
        sa.Column("risk_level", sa.String(length=64), nullable=True),
        sa.Column("benchmark_name", sa.String(length=255), nullable=True),
        sa.Column("fund_status", sa.String(length=32), nullable=True),
        sa.Column("source_name", sa.String(length=64), nullable=True),
        sa.Column("source_reference", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fund_master")),
        sa.UniqueConstraint("fund_code", name=op.f("uq_fund_master__fund_code")),
    )
    op.create_index(op.f("ix_fund_master__fund_name"), "fund_master", ["fund_name"], unique=False)
    op.create_index(
        op.f("ix_fund_master__fund_status"), "fund_master", ["fund_status"], unique=False
    )

    op.create_table(
        "portfolio",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_code", sa.String(length=64), nullable=False),
        sa.Column("portfolio_name", sa.String(length=255), nullable=False),
        sa.Column("base_currency_code", sa.String(length=3), nullable=False),
        sa.Column("investment_style", sa.String(length=128), nullable=True),
        sa.Column("target_description", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolio")),
        sa.UniqueConstraint("portfolio_code", name=op.f("uq_portfolio__portfolio_code")),
    )
    op.create_index(
        op.f("ix_portfolio__portfolio_name"), "portfolio", ["portfolio_name"], unique=False
    )

    op.create_table(
        "transaction",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("fund_id", sa.Integer(), nullable=False),
        sa.Column("external_reference", sa.String(length=128), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("trade_type", transaction_type_enum, nullable=False),
        sa.Column("units", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("gross_amount", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("fee_amount", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("nav_per_unit", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("source_name", sa.String(length=64), nullable=True),
        sa.Column("source_reference", sa.String(length=128), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["fund_id"], ["fund_master.id"], name=op.f("fk_transaction__fund_id__fund_master")
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"], ["portfolio.id"], name=op.f("fk_transaction__portfolio_id__portfolio")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transaction")),
    )
    op.create_index(
        op.f("ix_transaction__portfolio_id__trade_date"),
        "transaction",
        ["portfolio_id", "trade_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transaction__fund_id__trade_date"),
        "transaction",
        ["fund_id", "trade_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transaction__source_name__source_reference"),
        "transaction",
        ["source_name", "source_reference"],
        unique=False,
    )

    op.create_table(
        "position_lot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("fund_id", sa.Integer(), nullable=False),
        sa.Column("source_transaction_id", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("lot_key", sa.String(length=64), nullable=False),
        sa.Column("opened_on", sa.Date(), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("remaining_units", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("average_cost_per_unit", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("total_cost_amount", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("latest_nav_per_unit", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("latest_market_value_amount", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("portfolio_weight_ratio", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["fund_id"], ["fund_master.id"], name=op.f("fk_position_lot__fund_id__fund_master")
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolio.id"],
            name=op.f("fk_position_lot__portfolio_id__portfolio"),
        ),
        sa.ForeignKeyConstraint(
            ["source_transaction_id"],
            ["transaction.id"],
            name=op.f("fk_position_lot__source_transaction_id__transaction"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_position_lot")),
    )
    op.create_index(
        op.f("ix_position_lot__portfolio_id__as_of_date"),
        "position_lot",
        ["portfolio_id", "as_of_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_position_lot__fund_id__as_of_date"),
        "position_lot",
        ["fund_id", "as_of_date"],
        unique=False,
    )
    op.create_index(op.f("ix_position_lot__run_id"), "position_lot", ["run_id"], unique=False)
    op.create_index(
        op.f("ix_position_lot__portfolio_id__fund_id__lot_key"),
        "position_lot",
        ["portfolio_id", "fund_id", "lot_key"],
        unique=False,
    )

    op.create_table(
        "nav_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fund_id", sa.Integer(), nullable=False),
        sa.Column("nav_date", sa.Date(), nullable=False),
        sa.Column("unit_nav_amount", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("accumulated_nav_amount", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("daily_return_ratio", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("source_name", sa.String(length=64), nullable=True),
        sa.Column("source_reference", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["fund_id"], ["fund_master.id"], name=op.f("fk_nav_snapshot__fund_id__fund_master")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_nav_snapshot")),
    )
    op.create_index(
        op.f("ix_nav_snapshot__fund_id__nav_date"),
        "nav_snapshot",
        ["fund_id", "nav_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_nav_snapshot__source_name__nav_date"),
        "nav_snapshot",
        ["source_name", "nav_date"],
        unique=False,
    )

    op.create_table(
        "portfolio_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("workflow_name", sa.String(length=64), nullable=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("total_cost_amount", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("total_market_value_amount", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("total_cash_amount", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("unrealized_pnl_amount", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("realized_pnl_amount", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("cash_ratio", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("daily_return_ratio", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("weekly_return_ratio", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("monthly_return_ratio", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("max_drawdown_ratio", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolio.id"],
            name=op.f("fk_portfolio_snapshot__portfolio_id__portfolio"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolio_snapshot")),
    )
    op.create_index(
        op.f("ix_portfolio_snapshot__portfolio_id__snapshot_date"),
        "portfolio_snapshot",
        ["portfolio_id", "snapshot_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_portfolio_snapshot__run_id"), "portfolio_snapshot", ["run_id"], unique=False
    )
    op.create_index(
        op.f("ix_portfolio_snapshot__workflow_name__snapshot_date"),
        "portfolio_snapshot",
        ["workflow_name", "snapshot_date"],
        unique=False,
    )

    op.create_table(
        "review_report",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("workflow_name", sa.String(length=64), nullable=True),
        sa.Column("period_type", report_period_type_enum, nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("report_markdown", sa.Text(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("created_by_agent", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolio.id"],
            name=op.f("fk_review_report__portfolio_id__portfolio"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_report")),
    )
    op.create_index(
        op.f("ix_review_report__portfolio_id__period_end"),
        "review_report",
        ["portfolio_id", "period_end"],
        unique=False,
    )
    op.create_index(op.f("ix_review_report__run_id"), "review_report", ["run_id"], unique=False)
    op.create_index(
        op.f("ix_review_report__workflow_name__period_type"),
        "review_report",
        ["workflow_name", "period_type"],
        unique=False,
    )

    op.create_table(
        "strategy_proposal",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("workflow_name", sa.String(length=64), nullable=True),
        sa.Column("proposal_date", sa.Date(), nullable=False),
        sa.Column("thesis", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("recommended_actions_json", sa.JSON(), nullable=True),
        sa.Column("risk_notes", sa.Text(), nullable=True),
        sa.Column("counterarguments", sa.Text(), nullable=True),
        sa.Column("final_decision", sa.String(length=64), nullable=True),
        sa.Column("confidence_score", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("created_by_agent", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolio.id"],
            name=op.f("fk_strategy_proposal__portfolio_id__portfolio"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategy_proposal")),
    )
    op.create_index(
        op.f("ix_strategy_proposal__portfolio_id__proposal_date"),
        "strategy_proposal",
        ["portfolio_id", "proposal_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_strategy_proposal__run_id"), "strategy_proposal", ["run_id"], unique=False
    )
    op.create_index(
        op.f("ix_strategy_proposal__workflow_name__proposal_date"),
        "strategy_proposal",
        ["workflow_name", "proposal_date"],
        unique=False,
    )

    op.create_table(
        "agent_debate_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("workflow_name", sa.String(length=64), nullable=False),
        sa.Column("agent_name", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("tool_calls_json", sa.JSON(), nullable=True),
        sa.Column("trace_reference", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolio.id"],
            name=op.f("fk_agent_debate_log__portfolio_id__portfolio"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_debate_log")),
    )
    op.create_index(
        op.f("ix_agent_debate_log__run_id__created_at"),
        "agent_debate_log",
        ["run_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_debate_log__portfolio_id__workflow_name"),
        "agent_debate_log",
        ["portfolio_id", "workflow_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_debate_log__agent_name__created_at"),
        "agent_debate_log",
        ["agent_name", "created_at"],
        unique=False,
    )

    op.create_table(
        "system_event_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("workflow_name", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("event_message", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolio.id"],
            name=op.f("fk_system_event_log__portfolio_id__portfolio"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_event_log")),
    )
    op.create_index(
        op.f("ix_system_event_log__run_id__created_at"),
        "system_event_log",
        ["run_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_system_event_log__event_type__created_at"),
        "system_event_log",
        ["event_type", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_system_event_log__portfolio_id__workflow_name"),
        "system_event_log",
        ["portfolio_id", "workflow_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_system_event_log__portfolio_id__workflow_name"), table_name="system_event_log"
    )
    op.drop_index(
        op.f("ix_system_event_log__event_type__created_at"), table_name="system_event_log"
    )
    op.drop_index(op.f("ix_system_event_log__run_id__created_at"), table_name="system_event_log")
    op.drop_table("system_event_log")

    op.drop_index(
        op.f("ix_agent_debate_log__agent_name__created_at"), table_name="agent_debate_log"
    )
    op.drop_index(
        op.f("ix_agent_debate_log__portfolio_id__workflow_name"), table_name="agent_debate_log"
    )
    op.drop_index(op.f("ix_agent_debate_log__run_id__created_at"), table_name="agent_debate_log")
    op.drop_table("agent_debate_log")

    op.drop_index(
        op.f("ix_strategy_proposal__workflow_name__proposal_date"), table_name="strategy_proposal"
    )
    op.drop_index(op.f("ix_strategy_proposal__run_id"), table_name="strategy_proposal")
    op.drop_index(
        op.f("ix_strategy_proposal__portfolio_id__proposal_date"), table_name="strategy_proposal"
    )
    op.drop_table("strategy_proposal")

    op.drop_index(op.f("ix_review_report__workflow_name__period_type"), table_name="review_report")
    op.drop_index(op.f("ix_review_report__run_id"), table_name="review_report")
    op.drop_index(op.f("ix_review_report__portfolio_id__period_end"), table_name="review_report")
    op.drop_table("review_report")

    op.drop_index(
        op.f("ix_portfolio_snapshot__workflow_name__snapshot_date"), table_name="portfolio_snapshot"
    )
    op.drop_index(op.f("ix_portfolio_snapshot__run_id"), table_name="portfolio_snapshot")
    op.drop_index(
        op.f("ix_portfolio_snapshot__portfolio_id__snapshot_date"), table_name="portfolio_snapshot"
    )
    op.drop_table("portfolio_snapshot")

    op.drop_index(op.f("ix_nav_snapshot__source_name__nav_date"), table_name="nav_snapshot")
    op.drop_index(op.f("ix_nav_snapshot__fund_id__nav_date"), table_name="nav_snapshot")
    op.drop_table("nav_snapshot")

    op.drop_index(
        op.f("ix_position_lot__portfolio_id__fund_id__lot_key"), table_name="position_lot"
    )
    op.drop_index(op.f("ix_position_lot__run_id"), table_name="position_lot")
    op.drop_index(op.f("ix_position_lot__fund_id__as_of_date"), table_name="position_lot")
    op.drop_index(op.f("ix_position_lot__portfolio_id__as_of_date"), table_name="position_lot")
    op.drop_table("position_lot")

    op.drop_index(op.f("ix_transaction__source_name__source_reference"), table_name="transaction")
    op.drop_index(op.f("ix_transaction__fund_id__trade_date"), table_name="transaction")
    op.drop_index(op.f("ix_transaction__portfolio_id__trade_date"), table_name="transaction")
    op.drop_table("transaction")

    op.drop_index(op.f("ix_portfolio__portfolio_name"), table_name="portfolio")
    op.drop_table("portfolio")

    op.drop_index(op.f("ix_fund_master__fund_status"), table_name="fund_master")
    op.drop_index(op.f("ix_fund_master__fund_name"), table_name="fund_master")
    op.drop_table("fund_master")
