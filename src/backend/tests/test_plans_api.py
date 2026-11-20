import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine

from naiad.api.plans import create_plan, list_plans
from naiad.api.schemas import CreatePlanRequest
from naiad.config import AppConfig
from naiad.domain.models import Plan


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "0", str(24 * 400)])
async def test_create_plan_rejects_invalid_relative_hours(
    minimal_config: AppConfig, engine, value: str
) -> None:
    """Non-finite / non-positive / absurd horizons are a 422, not a 500 from
    timedelta overflowing."""
    body = CreatePlanRequest(sequence_id="seq_1", mode="in_hours", value=value)
    with Session(engine) as session, pytest.raises(HTTPException) as exc:
        await create_plan(body, None, minimal_config, session)
    assert exc.value.status_code == 422


async def test_create_plan_in_hours(minimal_config: AppConfig, engine) -> None:
    body = CreatePlanRequest(sequence_id="seq_1", mode="in_hours", value=2)
    with Session(engine) as session:
        plan = await create_plan(body, None, minimal_config, session)
    expected = datetime.now(UTC) + timedelta(hours=2)
    assert abs((plan.scheduled_at.replace(tzinfo=UTC) - expected).total_seconds()) < 5


async def test_list_plans_includes_overdue_pending_plan(minimal_config: AppConfig, engine) -> None:
    """A due plan still waiting on a conflict retry stays visible (and thus
    cancellable) instead of disappearing from the list."""
    with Session(engine) as session:
        session.add(
            Plan(
                id=str(uuid.uuid4()),
                sequence_id="seq_1",
                scheduled_at=(datetime.now(UTC) - timedelta(minutes=5)).replace(tzinfo=None),
            )
        )
        session.commit()
        plans = await list_plans(None, minimal_config, session)
    assert len(plans) == 1
