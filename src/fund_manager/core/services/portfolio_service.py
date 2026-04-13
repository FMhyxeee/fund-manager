"""Application-level services that assemble portfolio snapshots from storage."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from fund_manager.core.domain.decimal_constants import NAV_QUANTIZER, UNITS_QUANTIZER, ZERO
from fund_manager.core.domain.metrics import (
    ACCOUNTING_ASSUMPTIONS_NOTE,
    PortfolioValuePoint,
    PositionValuationInput,
    quantize_money,
)
from fund_manager.core.services.analytics_service import AnalyticsService, PositionMetrics
from fund_manager.storage.models import NavSnapshot, PositionLot
from fund_manager.storage.repo import (
    NavSnapshotRepository,
    PortfolioRepository,
    PortfolioSnapshotRepository,
    PositionLotRepository,
    resolve_authoritative_position_lots,
)
from fund_manager.storage.repo.protocols import (
    NavSnapshotRepositoryProtocol,
    PortfolioRepositoryProtocol,
    PortfolioSnapshotRepositoryProtocol,
    PositionLotRepositoryProtocol,
)

class PortfolioServiceError(ValueError):
    """Base exception for portfolio snapshot assembly failures."""


class PortfolioNotFoundError(PortfolioServiceError):
    """Raised when a requested portfolio does not exist."""

    def __init__(self, portfolio_id: int) -> None:
        super().__init__(f"Portfolio {portfolio_id} was not found.")
        self.portfolio_id = portfolio_id


class IncompletePortfolioSnapshotError(PortfolioServiceError):
    """Raised when a snapshot cannot be persisted because canonical values are incomplete."""

    def __init__(self, missing_nav_fund_codes: tuple[str, ...]) -> None:
        fund_codes = ", ".join(missing_nav_fund_codes) if missing_nav_fund_codes else "unknown"
        super().__init__(
            "Cannot persist a portfolio snapshot while NAV data is missing for: "
            f"{fund_codes}."
        )
        self.missing_nav_fund_codes = missing_nav_fund_codes


@dataclass(frozen=True)
class PortfolioValuationDTO:
    """One portfolio-level valuation point suitable for APIs and agent tools."""

    as_of_date: date
    market_value_amount: Decimal


@dataclass(frozen=True)
class PortfolioPositionDTO:
    """Aggregated position state plus deterministic metrics for one fund."""

    fund_id: int
    fund_code: str
    fund_name: str
    position_as_of_date: date
    units: Decimal
    average_cost_per_unit: Decimal
    total_cost_amount: Decimal
    latest_nav_date: date | None
    latest_nav_per_unit: Decimal | None
    current_value_amount: Decimal | None
    unrealized_pnl_amount: Decimal | None
    weight_ratio: Decimal | None
    missing_nav: bool
    lot_count: int
    lot_keys: tuple[str, ...]


@dataclass(frozen=True)
class PortfolioSnapshotDTO:
    """Structured snapshot output assembled from stored positions and NAV history."""

    portfolio_id: int
    portfolio_code: str
    portfolio_name: str
    as_of_date: date
    snapshot_record_id: int | None
    run_id: str | None
    workflow_name: str | None
    position_count: int
    total_cost_amount: Decimal
    total_market_value_amount: Decimal | None
    unrealized_pnl_amount: Decimal | None
    daily_return_ratio: Decimal | None
    weekly_return_ratio: Decimal | None
    monthly_return_ratio: Decimal | None
    period_return_ratio: Decimal | None
    max_drawdown_ratio: Decimal | None
    missing_nav_fund_codes: tuple[str, ...]
    valuation_history_start_date: date | None
    valuation_history_end_date: date | None
    valuation_history: tuple[PortfolioValuationDTO, ...]
    positions: tuple[PortfolioPositionDTO, ...]
    accounting_assumptions_note: str = ACCOUNTING_ASSUMPTIONS_NOTE

    def to_dict(self) -> dict[str, object]:
        """Render the nested DTO as a plain dictionary."""
        return asdict(self)


@dataclass
class _PositionAggregate:
    fund_id: int
    fund_code: str
    fund_name: str
    position_as_of_date: date
    units: Decimal
    total_cost_amount: Decimal
    lot_keys: list[str]


class PortfolioService:
    """Assemble deterministic portfolio snapshots from persisted accounting records."""

    def __init__(
        self,
        session: Session,
        *,
        analytics_service: AnalyticsService | None = None,
        portfolio_repo: PortfolioRepositoryProtocol | None = None,
        position_lot_repo: PositionLotRepositoryProtocol | None = None,
        nav_snapshot_repo: NavSnapshotRepositoryProtocol | None = None,
        portfolio_snapshot_repo: PortfolioSnapshotRepositoryProtocol | None = None,
    ) -> None:
        self._session = session
        self._analytics_service = analytics_service or AnalyticsService()
        self._portfolio_repo = portfolio_repo or PortfolioRepository(session)
        self._position_lot_repo = position_lot_repo or PositionLotRepository(session)
        self._nav_snapshot_repo = nav_snapshot_repo or NavSnapshotRepository(session)
        self._portfolio_snapshot_repo = (
            portfolio_snapshot_repo or PortfolioSnapshotRepository(session)
        )

    def assemble_portfolio_snapshot(
        self,
        portfolio_id: int,
        *,
        as_of_date: date,
        run_id: str | None = None,
        workflow_name: str | None = None,
    ) -> PortfolioSnapshotDTO:
        """Assemble a deterministic portfolio snapshot from persisted lot and NAV data."""
        portfolio = self._portfolio_repo.get_by_id(portfolio_id)
        if portfolio is None:
            raise PortfolioNotFoundError(portfolio_id)

        position_lots = self._position_lot_repo.list_for_portfolio_up_to(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
        )
        current_lots = self._latest_authoritative_lots(position_lots)
        latest_nav_by_fund_id = self._latest_nav_by_fund_id(
            self._nav_snapshot_repo.list_for_funds_up_to(
                fund_ids=sorted({position_lot.fund_id for position_lot in current_lots}),
                as_of_date=as_of_date,
            )
        )

        position_dtos, position_inputs = self._build_position_snapshot_dtos(
            current_lots,
            latest_nav_by_fund_id,
        )
        valuation_history = self._build_valuation_history(position_lots, as_of_date=as_of_date)
        valuation_points = tuple(
            PortfolioValuePoint(
                point.as_of_date,
                point.market_value_amount,
            )
            for point in valuation_history
        )
        portfolio_metrics = self._analytics_service.compute_portfolio_metrics(
            position_inputs,
            valuation_history=valuation_points,
        )
        performance_metrics = self._analytics_service.compute_performance_metrics(
            valuation_points,
            as_of_date=as_of_date,
        )

        return PortfolioSnapshotDTO(
            portfolio_id=portfolio.id,
            portfolio_code=portfolio.portfolio_code,
            portfolio_name=portfolio.portfolio_name,
            as_of_date=as_of_date,
            snapshot_record_id=None,
            run_id=run_id,
            workflow_name=workflow_name,
            position_count=len(position_dtos),
            total_cost_amount=portfolio_metrics.total_cost_amount,
            total_market_value_amount=portfolio_metrics.total_market_value_amount,
            unrealized_pnl_amount=portfolio_metrics.unrealized_pnl_amount,
            daily_return_ratio=performance_metrics.daily_return_ratio,
            weekly_return_ratio=performance_metrics.weekly_return_ratio,
            monthly_return_ratio=performance_metrics.monthly_return_ratio,
            period_return_ratio=performance_metrics.period_return_ratio,
            max_drawdown_ratio=performance_metrics.max_drawdown_ratio,
            missing_nav_fund_codes=portfolio_metrics.missing_nav_fund_codes,
            valuation_history_start_date=performance_metrics.valuation_history_start_date,
            valuation_history_end_date=performance_metrics.valuation_history_end_date,
            valuation_history=valuation_history,
            positions=position_dtos,
        )

    def get_portfolio_snapshot(
        self,
        portfolio_id: int,
        *,
        as_of_date: date,
        run_id: str | None = None,
        workflow_name: str | None = None,
    ) -> PortfolioSnapshotDTO:
        """Alias for assembling a portfolio snapshot for read-heavy call sites."""
        return self.assemble_portfolio_snapshot(
            portfolio_id,
            as_of_date=as_of_date,
            run_id=run_id,
            workflow_name=workflow_name,
        )

    def get_position_breakdown(
        self,
        portfolio_id: int,
        *,
        as_of_date: date,
    ) -> tuple[PortfolioPositionDTO, ...]:
        """Return only the aggregated position breakdown for a portfolio snapshot."""
        snapshot = self.assemble_portfolio_snapshot(
            portfolio_id,
            as_of_date=as_of_date,
        )
        return snapshot.positions

    def save_portfolio_snapshot(
        self,
        portfolio_id: int,
        *,
        as_of_date: date,
        run_id: str | None = None,
        workflow_name: str | None = None,
    ) -> PortfolioSnapshotDTO:
        """Persist a complete portfolio snapshot row and return the stored DTO."""
        snapshot = self.assemble_portfolio_snapshot(
            portfolio_id,
            as_of_date=as_of_date,
            run_id=run_id,
            workflow_name=workflow_name,
        )
        if snapshot.total_market_value_amount is None or snapshot.unrealized_pnl_amount is None:
            raise IncompletePortfolioSnapshotError(snapshot.missing_nav_fund_codes)

        try:
            portfolio_snapshot = self._portfolio_snapshot_repo.append(
                portfolio_id=portfolio_id,
                snapshot_date=as_of_date,
                total_cost_amount=snapshot.total_cost_amount,
                total_market_value_amount=snapshot.total_market_value_amount,
                unrealized_pnl_amount=snapshot.unrealized_pnl_amount,
                daily_return_ratio=snapshot.daily_return_ratio,
                weekly_return_ratio=snapshot.weekly_return_ratio,
                monthly_return_ratio=snapshot.monthly_return_ratio,
                max_drawdown_ratio=snapshot.max_drawdown_ratio,
                run_id=run_id,
                workflow_name=workflow_name,
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

        return replace(snapshot, snapshot_record_id=portfolio_snapshot.id)

    def _build_position_snapshot_dtos(
        self,
        position_lots: Iterable[PositionLot],
        latest_nav_by_fund_id: Mapping[int, NavSnapshot],
    ) -> tuple[tuple[PortfolioPositionDTO, ...], tuple[PositionValuationInput, ...]]:
        aggregates = self._aggregate_positions(position_lots)
        position_inputs = tuple(
            PositionValuationInput(
                fund_code=aggregate.fund_code,
                units=aggregate.units,
                total_cost_amount=aggregate.total_cost_amount,
                nav_per_unit=latest_nav_by_fund_id.get(aggregate.fund_id).unit_nav_amount
                if aggregate.fund_id in latest_nav_by_fund_id
                else None,
            )
            for aggregate in aggregates
        )
        metrics_by_fund_code = {
            metric.fund_code: metric
            for metric in self._analytics_service.compute_position_metrics(position_inputs)
        }

        position_dtos = tuple(
            self._build_position_dto(
                aggregate=aggregate,
                latest_nav=latest_nav_by_fund_id.get(aggregate.fund_id),
                current_metrics=metrics_by_fund_code[aggregate.fund_code],
            )
            for aggregate in aggregates
        )
        return position_dtos, position_inputs

    def _build_position_dto(
        self,
        *,
        aggregate: _PositionAggregate,
        latest_nav: NavSnapshot | None,
        current_metrics: PositionMetrics,
    ) -> PortfolioPositionDTO:
        return PortfolioPositionDTO(
            fund_id=aggregate.fund_id,
            fund_code=aggregate.fund_code,
            fund_name=aggregate.fund_name,
            position_as_of_date=aggregate.position_as_of_date,
            units=aggregate.units,
            average_cost_per_unit=self._average_cost_per_unit(
                aggregate.total_cost_amount,
                aggregate.units,
            ),
            total_cost_amount=aggregate.total_cost_amount,
            latest_nav_date=latest_nav.nav_date if latest_nav is not None else None,
            latest_nav_per_unit=latest_nav.unit_nav_amount if latest_nav is not None else None,
            current_value_amount=current_metrics.current_value_amount,
            unrealized_pnl_amount=current_metrics.unrealized_pnl_amount,
            weight_ratio=current_metrics.weight_ratio,
            missing_nav=current_metrics.missing_nav,
            lot_count=len(aggregate.lot_keys),
            lot_keys=tuple(aggregate.lot_keys),
        )

    def _build_valuation_history(
        self,
        position_lots: list[PositionLot],
        *,
        as_of_date: date,
    ) -> tuple[PortfolioValuationDTO, ...]:
        """Build valuation history from lot state changes and NAV event dates."""
        if not position_lots:
            return ()

        nav_snapshots = self._nav_snapshot_repo.list_for_funds_up_to(
            fund_ids=sorted({position_lot.fund_id for position_lot in position_lots}),
            as_of_date=as_of_date,
        )
        candidate_dates = sorted(
            {
                *(position_lot.as_of_date for position_lot in position_lots),
                *(nav_snapshot.nav_date for nav_snapshot in nav_snapshots),
            }
        )
        if not candidate_dates:
            return ()

        latest_lot_by_key: dict[str, PositionLot] = {}
        latest_nav_by_fund_id: dict[int, NavSnapshot] = {}
        valuation_history: list[PortfolioValuationDTO] = []
        lot_index = 0
        nav_index = 0

        for candidate_date in candidate_dates:
            while (
                lot_index < len(position_lots)
                and position_lots[lot_index].as_of_date <= candidate_date
            ):
                latest_lot_by_key[position_lots[lot_index].lot_key] = position_lots[lot_index]
                lot_index += 1
            while (
                nav_index < len(nav_snapshots)
                and nav_snapshots[nav_index].nav_date <= candidate_date
            ):
                latest_nav_by_fund_id[nav_snapshots[nav_index].fund_id] = nav_snapshots[nav_index]
                nav_index += 1

            aggregates = self._aggregate_positions(
                self._latest_authoritative_lots(latest_lot_by_key.values())
            )
            position_inputs = tuple(
                PositionValuationInput(
                    fund_code=aggregate.fund_code,
                    units=aggregate.units,
                    total_cost_amount=aggregate.total_cost_amount,
                    nav_per_unit=latest_nav_by_fund_id.get(aggregate.fund_id).unit_nav_amount
                    if aggregate.fund_id in latest_nav_by_fund_id
                    else None,
                )
                for aggregate in aggregates
            )
            portfolio_metrics = self._analytics_service.compute_portfolio_metrics(position_inputs)
            if portfolio_metrics.total_market_value_amount is None:
                continue

            valuation_history.append(
                PortfolioValuationDTO(
                    as_of_date=candidate_date,
                    market_value_amount=portfolio_metrics.total_market_value_amount,
                )
            )

        return tuple(valuation_history)

    def _aggregate_positions(
        self,
        position_lots: Iterable[PositionLot],
    ) -> tuple[_PositionAggregate, ...]:
        grouped: dict[int, _PositionAggregate] = {}

        for position_lot in position_lots:
            if position_lot.remaining_units <= ZERO:
                continue

            fund = position_lot.fund
            existing = grouped.get(fund.id)
            if existing is None:
                grouped[fund.id] = _PositionAggregate(
                    fund_id=fund.id,
                    fund_code=fund.fund_code,
                    fund_name=fund.fund_name,
                    position_as_of_date=position_lot.as_of_date,
                    units=self._quantize_units(position_lot.remaining_units),
                    total_cost_amount=quantize_money(position_lot.total_cost_amount),
                    lot_keys=[position_lot.lot_key],
                )
                continue

            existing.position_as_of_date = max(
                existing.position_as_of_date,
                position_lot.as_of_date,
            )
            existing.units = self._quantize_units(existing.units + position_lot.remaining_units)
            existing.total_cost_amount = quantize_money(
                existing.total_cost_amount + position_lot.total_cost_amount
            )
            existing.lot_keys.append(position_lot.lot_key)

        return tuple(
            sorted(
                grouped.values(),
                key=lambda aggregate: (aggregate.fund_code, aggregate.fund_name),
            )
        )

    def _latest_authoritative_lots(
        self,
        position_lots: Iterable[PositionLot],
    ) -> tuple[PositionLot, ...]:
        return resolve_authoritative_position_lots(position_lots)

    def _latest_nav_by_fund_id(
        self,
        nav_snapshots: Iterable[NavSnapshot],
    ) -> dict[int, NavSnapshot]:
        latest_by_fund_id: dict[int, NavSnapshot] = {}
        for nav_snapshot in nav_snapshots:
            latest_by_fund_id[nav_snapshot.fund_id] = nav_snapshot
        return latest_by_fund_id

    def _average_cost_per_unit(
        self,
        total_cost_amount: Decimal,
        units: Decimal,
    ) -> Decimal:
        if units == ZERO:
            return self._quantize_nav(ZERO)
        return self._quantize_nav(total_cost_amount / units)

    def _quantize_units(self, value: Decimal) -> Decimal:
        return value.quantize(UNITS_QUANTIZER, rounding=ROUND_HALF_UP)

    def _quantize_nav(self, value: Decimal) -> Decimal:
        return value.quantize(NAV_QUANTIZER, rounding=ROUND_HALF_UP)


__all__ = [
    "IncompletePortfolioSnapshotError",
    "PortfolioNotFoundError",
    "PortfolioPositionDTO",
    "PortfolioService",
    "PortfolioSnapshotDTO",
    "PortfolioValuationDTO",
]
