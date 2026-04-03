"""Unit tests for the scheduler CLI argument parsing."""

from __future__ import annotations

from datetime import date

from fund_manager.scheduler.cli import _parse_args


class TestCliParseArgs:
    def test_parse_daily(self) -> None:
        args = _parse_args(["daily", "--portfolio-id", "1"])
        assert args.frequency == "daily"
        assert args.portfolio_id == 1
        assert args.as_of_date is None
        assert args.job_name is None

    def test_parse_with_as_of_date(self) -> None:
        args = _parse_args(
            [
                "weekly",
                "--portfolio-id",
                "2",
                "--as-of-date",
                "2026-03-15",
            ]
        )
        assert args.frequency == "weekly"
        assert args.portfolio_id == 2
        assert args.as_of_date == date(2026, 3, 15)

    def test_parse_with_job_name(self) -> None:
        args = _parse_args(
            [
                "monthly",
                "--portfolio-id",
                "3",
                "--job-name",
                "monthly_strategy_debate",
            ]
        )
        assert args.frequency == "monthly"
        assert args.job_name == "monthly_strategy_debate"

    def test_parse_all_options(self) -> None:
        args = _parse_args(
            [
                "weekly",
                "--portfolio-id",
                "5",
                "--as-of-date",
                "2026-01-01",
                "--job-name",
                "weekly_review",
            ]
        )
        assert args.frequency == "weekly"
        assert args.portfolio_id == 5
        assert args.as_of_date == date(2026, 1, 1)
        assert args.job_name == "weekly_review"
