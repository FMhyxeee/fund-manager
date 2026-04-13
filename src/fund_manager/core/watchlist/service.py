"""Watchlist / style leader / candidate-fit read-model service."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from importlib import resources
from typing import Any

from sqlalchemy.orm import Session

from fund_manager.core.services.portfolio_read_service import PortfolioReadService
from fund_manager.storage.models import FundMaster
from fund_manager.storage.repo import FundMasterRepository, NavSnapshotRepository


@dataclass(frozen=True)
class WatchlistSeedItem:
    fund_code: str
    category: str
    style_tags: tuple[str, ...]
    risk_level: str
    is_watchlist_eligible: bool
    is_leader_eligible: bool
    notes: str | None = None


@dataclass(frozen=True)
class WatchlistCandidateDTO:
    fund_code: str
    fund_name: str
    category: str
    fit_label: str
    reason: str
    caution: str
    risk_level: str
    score: float


@dataclass(frozen=True)
class WatchlistResultDTO:
    portfolio_id: int | None
    portfolio_name: str | None
    as_of_date: date
    risk_profile: str
    core_watchlist: tuple[WatchlistCandidateDTO, ...]
    extended_watchlist: tuple[WatchlistCandidateDTO, ...]


@dataclass(frozen=True)
class CandidateFitAnalysisDTO:
    fund_code: str
    fund_name: str
    category: str
    fit_label: str
    overlap_level: str
    estimated_style_impact: str
    reasoning: str
    notes: tuple[str, ...]


@dataclass(frozen=True)
class FundLeaderDTO:
    fund_code: str
    fund_name: str
    category: str
    latest_nav_date: date
    latest_unit_nav_amount: str
    leader_reason: str
    caution: str


class FundWatchlistService:
    """Build deterministic watchlist outputs from a curated seed universe."""

    def __init__(
        self,
        session: Session,
        *,
        portfolio_read_service: PortfolioReadService | None = None,
        fund_repo: FundMasterRepository | None = None,
        nav_repo: NavSnapshotRepository | None = None,
    ) -> None:
        self._session = session
        self._portfolio_read_service = portfolio_read_service or PortfolioReadService(session)
        self._fund_repo = fund_repo or FundMasterRepository(session)
        self._nav_repo = nav_repo or NavSnapshotRepository(session)
        self._seed_items = self._load_seed_items()

    def build_watchlist_candidates(
        self,
        *,
        as_of_date: date,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
        risk_profile: str = "balanced",
        max_results: int = 6,
        include_categories: tuple[str, ...] | None = None,
        exclude_high_overlap: bool = True,
    ) -> WatchlistResultDTO:
        portfolio_summary = None
        held_codes: set[str] = set()
        held_categories: set[str] = set()
        if portfolio_id is not None or portfolio_name is not None:
            resolved = self._portfolio_read_service.get_position_breakdown(
                as_of_date=as_of_date,
                portfolio_id=portfolio_id,
                portfolio_name=portfolio_name,
            )
            portfolio_summary = resolved.portfolio
            held_codes = {position.fund_code for position in resolved.positions}
            held_categories = {
                seed.category
                for position in resolved.positions
                for seed in self._seed_items
                if seed.fund_code == position.fund_code
            }

        candidates: list[WatchlistCandidateDTO] = []
        for seed in self._seed_items:
            if not seed.is_watchlist_eligible:
                continue
            if include_categories is not None and seed.category not in include_categories:
                continue
            fund = self._fund_repo.get_by_code(seed.fund_code)
            if fund is None:
                continue
            fit = self._analyze_fit(seed=seed, fund=fund, held_codes=held_codes, held_categories=held_categories)
            if exclude_high_overlap and fit.fit_label in {"overlap_high", "high_beta_duplicate"}:
                continue
            score = self._score_watch_candidate(seed=seed, fit_label=fit.fit_label, risk_profile=risk_profile)
            candidates.append(
                WatchlistCandidateDTO(
                    fund_code=fund.fund_code,
                    fund_name=fund.fund_name,
                    category=seed.category,
                    fit_label=fit.fit_label,
                    reason=fit.reasoning,
                    caution=self._build_caution(seed, fit.fit_label),
                    risk_level=seed.risk_level,
                    score=score,
                )
            )

        ranked = tuple(sorted(candidates, key=lambda item: (-item.score, item.fund_code)))
        core_count = min(3, len(ranked), max_results)
        core = ranked[:core_count]
        extended = ranked[core_count:max_results]
        return WatchlistResultDTO(
            portfolio_id=portfolio_summary.portfolio_id if portfolio_summary else portfolio_id,
            portfolio_name=portfolio_summary.portfolio_name if portfolio_summary else portfolio_name,
            as_of_date=as_of_date,
            risk_profile=risk_profile,
            core_watchlist=core,
            extended_watchlist=extended,
        )

    def analyze_candidate_fit(
        self,
        *,
        as_of_date: date,
        fund_code: str,
        portfolio_id: int | None = None,
        portfolio_name: str | None = None,
    ) -> CandidateFitAnalysisDTO:
        seed = self._require_seed(fund_code)
        fund = self._require_fund(fund_code)
        resolved = self._portfolio_read_service.get_position_breakdown(
            as_of_date=as_of_date,
            portfolio_id=portfolio_id,
            portfolio_name=portfolio_name,
        )
        held_codes = {position.fund_code for position in resolved.positions}
        held_categories = {
            item.category
            for position in resolved.positions
            for item in self._seed_items
            if item.fund_code == position.fund_code
        }
        fit = self._analyze_fit(seed=seed, fund=fund, held_codes=held_codes, held_categories=held_categories)
        return CandidateFitAnalysisDTO(
            fund_code=fund.fund_code,
            fund_name=fund.fund_name,
            category=seed.category,
            fit_label=fit.fit_label,
            overlap_level=fit.overlap_level,
            estimated_style_impact=fit.estimated_style_impact,
            reasoning=fit.reasoning,
            notes=fit.notes,
        )

    def build_style_leaders(
        self,
        *,
        as_of_date: date,
        categories: tuple[str, ...] | None = None,
        max_per_category: int = 1,
    ) -> dict[str, tuple[FundLeaderDTO, ...]]:
        selected_categories = set(categories) if categories is not None else None
        grouped: dict[str, list[FundLeaderDTO]] = {}
        for seed in self._seed_items:
            if not seed.is_leader_eligible:
                continue
            if selected_categories is not None and seed.category not in selected_categories:
                continue
            fund = self._fund_repo.get_by_code(seed.fund_code)
            if fund is None:
                continue
            latest_nav_date = self._nav_repo.get_latest_nav_date(fund_id=fund.id)
            if latest_nav_date is None or latest_nav_date > as_of_date:
                continue
            nav_rows = self._nav_repo.list_for_funds_up_to(fund_ids=[fund.id], as_of_date=as_of_date)
            latest_row = nav_rows[-1] if nav_rows else None
            if latest_row is None:
                continue
            grouped.setdefault(seed.category, []).append(
                FundLeaderDTO(
                    fund_code=fund.fund_code,
                    fund_name=fund.fund_name,
                    category=seed.category,
                    latest_nav_date=latest_row.nav_date,
                    latest_unit_nav_amount=str(latest_row.unit_nav_amount),
                    leader_reason=self._leader_reason(seed),
                    caution=self._leader_caution(seed, latest_row.nav_date, as_of_date),
                )
            )

        return {
            category: tuple(items[:max_per_category])
            for category, items in sorted(grouped.items())
        }

    def _require_seed(self, fund_code: str) -> WatchlistSeedItem:
        for item in self._seed_items:
            if item.fund_code == fund_code:
                return item
        msg = f"Fund {fund_code} is not configured in watchlist seed."
        raise ValueError(msg)

    def _require_fund(self, fund_code: str) -> FundMaster:
        fund = self._fund_repo.get_by_code(fund_code)
        if fund is None:
            msg = f"Fund {fund_code} was not found."
            raise ValueError(msg)
        return fund

    def _load_seed_items(self) -> tuple[WatchlistSeedItem, ...]:
        raw = resources.files("fund_manager.data").joinpath("watchlist_seed.json").read_text(encoding="utf-8")
        payload = json.loads(raw)
        return tuple(
            WatchlistSeedItem(
                fund_code=item["fund_code"],
                category=item["category"],
                style_tags=tuple(item.get("style_tags", [])),
                risk_level=item["risk_level"],
                is_watchlist_eligible=bool(item.get("is_watchlist_eligible", True)),
                is_leader_eligible=bool(item.get("is_leader_eligible", True)),
                notes=item.get("notes"),
            )
            for item in payload
        )

    def _score_watch_candidate(self, *, seed: WatchlistSeedItem, fit_label: str, risk_profile: str) -> float:
        score = 10.0
        if fit_label == "complementary":
            score += 5.0
        elif fit_label == "defensive_addition":
            score += 4.0
        elif fit_label == "neutral":
            score += 2.0
        elif fit_label == "high_beta_duplicate":
            score -= 4.0
        elif fit_label == "overlap_high":
            score -= 5.0

        if risk_profile == "conservative" and seed.risk_level == "low":
            score += 2.0
        if risk_profile == "balanced" and seed.category in {"healthcare", "broad_index"}:
            score += 1.0
        if risk_profile == "aggressive" and seed.risk_level == "high":
            score += 2.0
        return score

    def _build_caution(self, seed: WatchlistSeedItem, fit_label: str) -> str:
        if fit_label == "high_beta_duplicate":
            return "与现有高波动暴露重合较高，适合观察，不适合追高。"
        if seed.risk_level == "high":
            return "高波动方向，更适合观察或回调分批，不适合追涨。"
        if seed.category == "defensive_dividend":
            return "偏防守方向，若组合已较防守，需防止过度保守。"
        return "先作为观察池候选，不直接等同于买入建议。"

    def _leader_reason(self, seed: WatchlistSeedItem) -> str:
        if seed.category == "technology_growth":
            return "科技成长风格风向标。"
        if seed.category == "healthcare":
            return "医药修复方向风向标。"
        if seed.category == "broad_index":
            return "宽基承接方向代表。"
        if seed.category == "consumer":
            return "消费修复方向代表。"
        return "防守风格代表。"

    def _leader_caution(self, seed: WatchlistSeedItem, latest_nav_date: date, as_of_date: date) -> str:
        if latest_nav_date < as_of_date - timedelta(days=10):
            return "净值更新有滞后，仅适合作弱风向参考。"
        if seed.risk_level == "high":
            return "高弹性风格，仅作为风向标观察，不代表当前适合买入。"
        return "可作为风格参考，但仍需结合组合上下文。"

    def _analyze_fit(
        self,
        *,
        seed: WatchlistSeedItem,
        fund: FundMaster,
        held_codes: set[str],
        held_categories: set[str],
    ) -> _FitResult:
        if fund.fund_code in held_codes:
            return _FitResult(
                fit_label="overlap_high",
                overlap_level="high",
                estimated_style_impact="reinforces_existing_exposure",
                reasoning="该基金已在当前组合中，重复加入不会提供新的观察价值。",
                notes=("更适合作为持仓跟踪对象",),
            )
        if seed.category in held_categories and seed.risk_level == "high":
            return _FitResult(
                fit_label="high_beta_duplicate",
                overlap_level="high",
                estimated_style_impact="adds_high_beta_duplicate_exposure",
                reasoning="当前组合已含同类高波动暴露，再加入更像风格重复而不是有效补充。",
                notes=("适合做风向标", "不适合直接扩表"),
            )
        if seed.category in held_categories:
            return _FitResult(
                fit_label="overlap_high",
                overlap_level="medium",
                estimated_style_impact="reinforces_existing_style",
                reasoning="当前组合已有相近风格暴露，这只基金更多是同风格替代项。",
                notes=("可作对照观察",),
            )
        if seed.category == "defensive_dividend":
            return _FitResult(
                fit_label="defensive_addition",
                overlap_level="low",
                estimated_style_impact="adds_defensive_exposure",
                reasoning="当前组合偏成长与主题，这类基金可作为防守补充方向观察。",
                notes=("适合市场转防守时再评估",),
            )
        return _FitResult(
            fit_label="complementary",
            overlap_level="low",
            estimated_style_impact=f"adds_{seed.category}_exposure",
            reasoning="与当前组合重合较低，更适合作为补充观察方向。",
            notes=("适合进入观察池",),
        )


@dataclass(frozen=True)
class _FitResult:
    fit_label: str
    overlap_level: str
    estimated_style_impact: str
    reasoning: str
    notes: tuple[str, ...]
