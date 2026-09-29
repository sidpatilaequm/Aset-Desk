"""Convert database rows into the JSON shapes the browser app uses (camelCase)."""
from datetime import date, datetime
from decimal import Decimal


def iso(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat(timespec="milliseconds") + "Z"
    if isinstance(v, date):
        return v.isoformat()
    return v


def num(v):
    if v is None:
        return None
    return float(v) if isinstance(v, Decimal) else v


def asset_json(a):
    return {
        "id": a.id, "name": a.name, "category": a.category, "status": a.status, "serial": a.serial or "",
        "model": a.model or "", "vendor": a.vendor or "", "vendorTaxId": a.vendor_tax_id or "",
        "invoiceNumber": a.invoice_number or "", "invoiceBlobId": a.invoice_file_id,
        "location": a.location or "", "department": a.department or "", "notes": a.notes or "",
        "purchaseDate": iso(a.purchase_date), "inServiceDate": iso(a.in_service_date),
        "cost": num(a.cost), "salvage": num(a.salvage), "life": a.life_years, "method": a.method,
        "rate": num(a.wdv_rate) if a.wdv_rate is not None else "", "source": a.source,
        "assignedTo": a.assigned_to, "allocatedAt": iso(a.allocated_at), "allocatedBy": a.allocated_by,
        "acknowledgedAt": iso(a.acknowledged_at), "acknowledgedBy": a.acknowledged_by, "acknowledgedName": a.acknowledged_name,
        "disposedAt": iso(a.disposed_at), "soldTo": a.sold_to, "salePrice": num(a.sale_price), "saleId": a.sale_id,
        "createdAt": iso(a.created_at), "createdBy": a.created_by, "updatedAt": iso(a.updated_at),
        "allocations": [{"to": x.employee_id, "from": iso(x.from_at), "until": iso(x.until_at), "by": x.allocated_by,
                         "note": x.note or "", "returnCondition": x.return_condition, "returnNote": x.return_note or ""}
                        for x in a.allocations],
        "log": [{"at": iso(l.at), "by": l.by_user, "text": l.text} for l in a.log],
    }


def ticket_json(t):
    return {
        "id": t.id, "subject": t.subject, "assetId": t.asset_id, "assetTag": t.asset_tag or "", "assetName": t.asset_name or "",
        "assetSerial": t.asset_serial or "", "category": t.category, "priority": t.priority, "status": t.status,
        "requesterId": t.requester_id, "assigneeId": t.assignee_id, "createdAt": iso(t.created_at), "updatedAt": iso(t.updated_at),
        "dueAt": iso(t.due_at), "firstResponseAt": iso(t.first_response_at), "solvedAt": iso(t.solved_at), "closedAt": iso(t.closed_at),
        "resolution": t.resolution or "", "rating": t.rating, "lastMessageAt": iso(t.last_message_at), "lastMessageBy": t.last_message_by,
        "lastPublicAt": iso(t.last_public_at), "lastPreview": t.last_preview or "", "channel": "chat",
    }


def message_json(m):
    att = None
    if m.attachment is not None:
        att = {"id": m.attachment.id, "type": m.attachment.content_type, "name": m.attachment.filename}
    return {"id": m.id, "at": iso(m.at), "by": m.by_user, "body": m.body, "kind": m.kind, "attachment": att}


def return_json(r):
    return {
        "id": r.id, "type": r.type, "employeeId": r.employee_id, "reason": r.reason, "note": r.note or "",
        "plannedAt": iso(r.planned_at), "lastDay": iso(r.last_day), "department": r.department or "", "personalEmail": r.personal_email or "",
        "stage": r.stage, "createdAt": iso(r.created_at), "updatedAt": iso(r.updated_at), "clearedAt": iso(r.cleared_at),
        "signoffs": {
            "it": {"by": r.it_signoff_by, "at": iso(r.it_signoff_at), "comment": r.it_comment or ""} if r.it_signoff_by else None,
            "finance": {"by": r.fin_signoff_by, "at": iso(r.fin_signoff_at), "comment": r.fin_comment or "", "deduction": num(r.fin_deduction)} if r.fin_signoff_by else None,
        },
        "ffStatus": r.ff_status, "ffDeductedAt": iso(r.ff_deducted_at),
        "items": [{"key": i.item_key, "kind": i.kind, "assetId": i.asset_id, "tag": i.tag, "name": i.name, "serial": i.serial or "",
                   "cost": num(i.cost), "bookValue": num(i.book_value), "state": i.state, "condition": i.condition or "",
                   "recovery": num(i.recovery), "note": i.note or "", "by": i.by_user, "at": iso(i.at)} for i in r.items],
        "history": [{"at": iso(h.at), "by": h.by_user, "text": h.text} for h in r.history],
    }


def sale_json(s):
    return {
        "id": s.id, "assetId": s.asset_id, "tag": s.tag, "name": s.name, "serial": s.serial or "", "employeeId": s.employee_id,
        "price": num(s.price), "costAtOffer": num(s.cost_at_offer), "bookValueAtOffer": num(s.book_value_at_offer),
        "bookValueAtSale": num(s.book_value_at_sale), "instalments": s.instalments, "startMonth": s.start_month, "note": s.note or "",
        "stage": s.stage, "createdBy": s.created_by, "createdAt": iso(s.created_at), "updatedAt": iso(s.updated_at),
        "financeApproval": {"by": s.fin_by, "at": iso(s.fin_at), "comment": s.fin_comment or ""} if s.fin_by else None,
        "acceptance": {"by": s.employee_id, "at": iso(s.accepted_at), "name": s.accepted_name} if s.accepted_at else None,
        "soldAt": iso(s.sold_at),
        "schedule": [{"no": i.no, "month": i.month, "amount": num(i.amount), "status": i.status, "at": iso(i.at), "by": i.by_user} for i in s.schedule],
        "history": [{"at": iso(h.at), "by": h.by_user, "text": h.text} for h in s.history],
    }
