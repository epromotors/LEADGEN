import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional, List

from app.database import get_db
from app.models import ActivityLog, Lead, Audit, Campaign
from app.schemas import ActivityLogResponse, DashboardMetrics

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("/", response_model=List[ActivityLogResponse], summary="Recent activity log")
async def get_activity_log(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(limit)
    )
    return result.scalars().all()


@router.get("/metrics", response_model=DashboardMetrics, summary="Dashboard KPI metrics")
async def get_metrics(db: AsyncSession = Depends(get_db)):
    total_leads = (await db.execute(select(func.count(Lead.id)))).scalar_one()
    audits_complete = (await db.execute(
        select(func.count(Audit.id)).where(Audit.status == "done")
    )).scalar_one()
    emails_sent = (await db.execute(
        select(func.count(ActivityLog.id)).where(ActivityLog.event_type == "email_sent")
    )).scalar_one()
    campaigns_active = (await db.execute(
        select(func.count(Campaign.id)).where(
            Campaign.status.in_(["sending", "scheduled"])
        )
    )).scalar_one()

    return DashboardMetrics(
        total_leads=total_leads,
        audits_complete=audits_complete,
        emails_sent=emails_sent,
        campaigns_active=campaigns_active,
    )
