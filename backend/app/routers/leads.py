import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Lead, ActivityLog
from app.schemas import LeadResponse, LeadListResponse, LeadUpdate
from app.utils.csv_parser import parse_and_clean_csv

router = APIRouter(prefix="/leads", tags=["leads"])


def _make_lead_response(lead: Lead) -> dict:
    """
    Build a LeadResponse-compatible dict from a Lead ORM instance.
    Pulls audit_error from the eagerly-loaded .audit relationship so the
    skipped-site banner appears correctly in the frontend table.
    """
    audit = getattr(lead, 'audit', None)
    return LeadResponse.model_validate(lead).model_copy(
        update={
            "audit_error": audit.error_message if audit else None,
            "audit_status": audit.status if audit else None,
        }
    )



@router.delete("/all", summary="Delete ALL leads and their audits")
async def delete_all_leads(db: AsyncSession = Depends(get_db)):
    """Hard-delete every lead and every audit record. Irreversible."""
    from sqlalchemy import delete as sql_delete
    from app.models import Audit
    # Delete audits first (FK constraint), then all leads
    await db.execute(sql_delete(Audit))
    result = await db.execute(sql_delete(Lead))
    await db.commit()
    count = result.rowcount
    log = ActivityLog(
        event_type="leads_deleted",
        message=f"Deleted ALL {count} lead(s) and their audits.",
    )
    db.add(log)
    await db.commit()
    return {"deleted": count}


@router.post("/upload", summary="Upload leads CSV")
async def upload_leads(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Accept a CSV file. Parse, clean, deduplicate against existing DB entries,
    and bulk insert new leads.
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted.")

    content = await file.read()
    rows = parse_and_clean_csv(content)

    if not rows:
        raise HTTPException(status_code=400, detail="No valid leads found in CSV.")

    # Fetch existing emails to deduplicate against DB
    existing = await db.execute(select(Lead.email))
    existing_emails = {row[0] for row in existing.fetchall()}

    new_leads = []
    skipped = 0
    for row in rows:
        if row["email"] in existing_emails:
            skipped += 1
            continue
        lead = Lead(**row)
        db.add(lead)
        new_leads.append(lead)
        existing_emails.add(row["email"])

    await db.commit()

    # Log the batch
    if new_leads:
        log = ActivityLog(
            event_type="leads_imported",
            message=f"Imported {len(new_leads)} leads from '{file.filename}'. "
                    f"Skipped {skipped} duplicates.",
        )
        db.add(log)
        await db.commit()

    return {
        "imported": len(new_leads),
        "skipped_duplicates": skipped,
        "total_in_file": len(rows),
    }


@router.get("/", response_model=LeadListResponse, summary="List all leads")
async def list_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=5000),
    status: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Search by business name or email"),
    db: AsyncSession = Depends(get_db),
):
    from app.models import Audit
    from sqlalchemy import or_, cast, String
    query = select(Lead).order_by(Lead.created_at.desc())
    count_q = select(func.count()).select_from(Lead)

    if status == "skipped":
        query = query.join(Audit).where(Audit.error_message.like("SITE_STATUS:%"))
        count_q = count_q.join(Audit).where(Audit.error_message.like("SITE_STATUS:%"))
    elif status:
        query = query.where(Lead.status == status)
        count_q = count_q.where(Lead.status == status)

    if q and q.strip():
        term = f"%{q.strip()}%"
        search_filter = or_(
            Lead.business_name.ilike(term),
            Lead.email.ilike(term),
            Lead.website.ilike(term),
        )
        query = query.where(search_filter)
        count_q = count_q.where(search_filter)

    total = (await db.execute(count_q)).scalar_one()

    query = query.options(selectinload(Lead.audit)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    leads = result.scalars().all()

    items = [_make_lead_response(lead) for lead in leads]
    return LeadListResponse(total=total, items=items)


@router.get("/{lead_id}", response_model=LeadResponse, summary="Get a single lead")
async def get_lead(lead_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id).options(selectinload(Lead.audit))
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")
    return _make_lead_response(lead)


@router.delete("/{lead_id}", summary="Delete a lead")
async def delete_lead(lead_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")
    await db.delete(lead)
    await db.commit()
    return {"deleted": str(lead_id)}


@router.patch("/{lead_id}", response_model=LeadResponse, summary="Update lead fields")
async def update_lead(
    lead_id: uuid.UUID,
    body: LeadUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Partially update lead fields (business_name, email, phone, website)."""
    lead = await db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    updated_fields = []
    if body.business_name is not None:
        lead.business_name = body.business_name.strip()
        updated_fields.append("name")
    if body.email is not None:
        lead.email = body.email.strip()
        updated_fields.append("email")
    if body.phone is not None:
        lead.phone = body.phone.strip() or None
        updated_fields.append("phone")
    if body.website is not None:
        lead.website = body.website.strip()
        updated_fields.append("website")

    await db.commit()

    # Re-fetch with audit relationship so audit_error is included in response
    result = await db.execute(
        select(Lead).where(Lead.id == lead_id).options(selectinload(Lead.audit))
    )
    lead = result.scalar_one()

    log = ActivityLog(
        event_type="lead_updated",
        lead_id=lead.id,
        message=f"Updated {', '.join(updated_fields) or 'fields'} for {lead.business_name} ({lead.email}).",
    )
    db.add(log)
    await db.commit()

    return _make_lead_response(lead)


@router.post("/clean-names", summary="Strip taglines from business names (remove from first - or |)")
async def clean_all_names(db: AsyncSession = Depends(get_db)):
    """
    Iterate every lead and strip anything from the first ' - ' or ' | '
    separator onwards in the business name.

    Example: Bigmen Stout Men's Shop - Bigmen.com, Inc
          →  Bigmen Stout Men's Shop
    """
    from app.utils.csv_parser import clean_business_name

    result = await db.execute(select(Lead))
    leads = result.scalars().all()

    cleaned_count = 0
    for lead in leads:
        trimmed = clean_business_name(lead.business_name or "")
        if trimmed and trimmed != lead.business_name:
            lead.business_name = trimmed
            cleaned_count += 1

    if cleaned_count:
        await db.commit()
        log = ActivityLog(
            event_type="names_cleaned",
            message=f"Stripped taglines from {cleaned_count} business name(s).",
        )
        db.add(log)
        await db.commit()

    return {
        "cleaned": cleaned_count,
        "already_clean": len(leads) - cleaned_count,
        "total": len(leads),
    }


@router.post("/clean-urls", summary="Trim all website URLs to root domain")
async def clean_all_urls(db: AsyncSession = Depends(get_db)):
    """
    Iterate every lead and normalise its website to the root URL
    (scheme + domain + trailing slash), stripping any internal page paths.

    Example: https://balanicustom.com/custom-suits-indianapolis
          →  https://balanicustom.com/
    """
    from app.utils.csv_parser import clean_website

    result = await db.execute(select(Lead))
    leads = result.scalars().all()

    cleaned_count = 0
    for lead in leads:
        trimmed = clean_website(lead.website or "")
        if trimmed and trimmed != lead.website:
            lead.website = trimmed
            cleaned_count += 1

    if cleaned_count:
        await db.commit()
        log = ActivityLog(
            event_type="urls_cleaned",
            message=f"Trimmed {cleaned_count} lead website(s) to root URL.",
        )
        db.add(log)
        await db.commit()

    return {
        "cleaned": cleaned_count,
        "already_clean": len(leads) - cleaned_count,
        "total": len(leads),
    }


@router.post("/bulk-delete", summary="Bulk delete leads by ID list")
async def bulk_delete_leads(
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """Accept {ids: [uuid, ...]} and delete all matching leads."""
    from sqlalchemy import delete as sql_delete
    ids = payload.get("ids", [])
    if not ids:
        raise HTTPException(status_code=400, detail="No IDs provided.")

    # Convert strings to UUIDs
    try:
        uuid_list = [uuid.UUID(str(i)) for i in ids]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID in list.")

    # Delete audits first (passive_deletes handles it via DB cascade,
    # but bulk SQL delete skips ORM so we do it explicitly)
    from app.models import Audit
    await db.execute(sql_delete(Audit).where(Audit.lead_id.in_(uuid_list)))

    # Delete leads
    result = await db.execute(
        sql_delete(Lead).where(Lead.id.in_(uuid_list))
    )
    await db.commit()

    count = result.rowcount
    log = ActivityLog(
        event_type="leads_deleted",
        message=f"Bulk deleted {count} lead(s).",
    )
    db.add(log)
    await db.commit()

    return {"deleted": count}
