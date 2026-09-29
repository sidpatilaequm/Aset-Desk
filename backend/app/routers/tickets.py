"""Support chat: employees raise requests on their own assets; IT works them to resolution."""
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import ai
from ..db import get_db, next_id, utcnow
from ..models import File, Ticket, TicketMessage, User
from ..perms import AGENT_ROLES
from ..security import CurrentUser, current_user, get_config, role_of
from ..serialize import message_json, ticket_json
from ..services import get_asset, log_asset, user_name

router = APIRouter(prefix="/api/tickets")
PRIORITY_HOURS = {"Critical": 4, "High": 24, "Medium": 72, "Low": 168}
CATEGORIES = ["Hardware fault", "Software issue", "Physical damage", "Lost or stolen", "Replacement request", "Access / setup", "Other"]


def _ticket(db: Session, tid: str, cu: CurrentUser, lock=False) -> Ticket:
    q = select(Ticket).where(Ticket.id == tid)
    if lock:
        q = q.with_for_update()
    t = db.execute(q).scalar_one_or_none()
    if not t:
        raise HTTPException(404, "Request not found.")
    if not (cu.can("tickets.viewAll") or t.requester_id == cu.id or t.assignee_id == cu.id):
        raise HTTPException(403, "You don't have access to this request.")
    return t


def _msg(db, t, by, body, kind, attachment=None, at=None):
    m = TicketMessage(ticket_id=t.id, at=at or utcnow(), by_user=by, kind=kind, body=body, attachment_file_id=attachment)
    db.add(m)
    return m


def _attachment(db, fid):
    if not fid:
        return None
    if not db.get(File, fid):
        raise HTTPException(400, "Attachment not found.")
    return fid


class NewTicket(BaseModel):
    assetId: str
    category: str
    priority: str = "Medium"
    subject: str = ""
    body: str = Field(min_length=5, max_length=10000)
    attachmentId: str | None = None


@router.post("")
def create(b: NewTicket, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("tickets.raise")
    a = get_asset(db, b.assetId)
    if a.assigned_to != cu.id or a.status in ("Disposed", "Retired", "Sold"):
        raise HTTPException(403, "You can only raise requests on assets allocated to you.")
    if b.priority not in PRIORITY_HOURS or b.category not in CATEGORIES:
        raise HTTPException(400, "Choose a valid type and urgency.")
    now = utcnow()
    t = Ticket(id=next_id(db, "TKT"), subject=(b.subject.strip() or f"{b.category} – {a.name}")[:200], asset_id=a.id, asset_tag=a.id,
               asset_name=a.name, asset_serial=a.serial, category=b.category, priority=b.priority, status="New",
               requester_id=cu.id, created_at=now, updated_at=now, due_at=now + timedelta(hours=PRIORITY_HOURS[b.priority]),
               last_message_at=now, last_message_by=cu.id, last_public_at=now, last_preview=b.body.strip()[:140])
    db.add(t); db.flush()
    _msg(db, t, cu.id, b.body.strip(), "public", _attachment(db, b.attachmentId), at=now)
    _msg(db, t, cu.id, f"Request {t.id} raised on serial {a.serial or 'No serial'} and sent to the IT support queue", "system", at=now + timedelta(milliseconds=1))
    db.commit()
    return ticket_json(t)


@router.get("/{tid}/messages")
def messages(tid: str, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    t = _ticket(db, tid, cu)
    ms = db.execute(select(TicketMessage).where(TicketMessage.ticket_id == t.id).order_by(TicketMessage.at, TicketMessage.id)).scalars().all()
    agent = cu.can("tickets.manage")
    return [message_json(m) for m in ms if agent or m.kind != "internal"]


class Reply(BaseModel):
    body: str = Field(default="", max_length=10000)
    kind: str = Field(default="public", pattern="^(public|internal)$")
    status: str | None = None
    attachmentId: str | None = None


def _restore_asset(db, t, by):
    if not t.asset_id:
        return
    a = get_asset(db, t.asset_id, lock=True)
    if a.status == "Under repair":
        a.status = "In use" if a.assigned_to else "In stock"
        log_asset(db, a, by, f"Back in service after {t.id}")


@router.post("/{tid}/messages")
def reply(tid: str, b: Reply, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    t = _ticket(db, tid, cu, lock=True)
    if t.status == "Closed":
        raise HTTPException(409, "This request is closed.")
    body = b.body.strip(); now = utcnow()
    agent_view = cu.can("tickets.manage") and t.requester_id != cu.id
    if agent_view:
        st = b.status or ("Open" if t.status in ("New", "Solved") else t.status)
        if st not in ("Open", "Pending", "On-hold", "Solved"):
            raise HTTPException(400, "Unknown status.")
        if not body and st == t.status:
            raise HTTPException(400, "Write a reply first.")
        if st in ("Solved", "Pending") and not (body and b.kind == "public"):
            raise HTTPException(400, "Tell the employee what fixed it." if st == "Solved" else "Ask the employee your question in a reply first.")
        if body:
            _msg(db, t, cu.id, body, b.kind, _attachment(db, b.attachmentId), at=now)
        t.last_message_at = now; t.last_message_by = cu.id; t.updated_at = now
        if body and b.kind == "public":
            t.last_public_at = now; t.last_preview = body[:140]
            t.first_response_at = t.first_response_at or now
        seq = 1
        if not t.assignee_id:
            t.assignee_id = cu.id
            _msg(db, t, cu.id, f"{cu.user.name or cu.user.email} picked up this request", "system", at=now + timedelta(milliseconds=seq)); seq += 1
        if st != t.status:
            _msg(db, t, cu.id, f"Status changed to {st}", "system", at=now + timedelta(milliseconds=seq))
            if st == "Solved":
                t.solved_at = now; t.resolution = body
            if t.status == "Solved":
                t.solved_at = None
            t.status = st
            if st == "Solved":
                _restore_asset(db, t, cu.id)
    elif t.requester_id == cu.id:
        if not body and not b.attachmentId:
            raise HTTPException(400, "Write a message first.")
        if b.kind != "public":
            raise HTTPException(403, "Only IT can add internal notes.")
        _msg(db, t, cu.id, body or "(attachment)", "public", _attachment(db, b.attachmentId), at=now)
        t.last_message_at = now; t.last_message_by = cu.id; t.last_public_at = now; t.updated_at = now
        t.last_preview = (body or "Sent an attachment")[:140]
        if t.status in ("Pending", "Solved"):
            if t.status == "Solved":
                t.solved_at = None
                _msg(db, t, cu.id, "Reopened — the employee says it isn't fixed", "system", at=now + timedelta(milliseconds=1))
            t.status = "Open" if t.assignee_id else "New"
    else:
        raise HTTPException(403, "Only the requester or IT support can reply.")
    db.commit()
    return ticket_json(t)


class TicketPatch(BaseModel):
    assigneeId: str | None = None
    priority: str | None = None
    unassign: bool = False


@router.patch("/{tid}")
def update(tid: str, b: TicketPatch, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("tickets.manage")
    t = _ticket(db, tid, cu, lock=True)
    if t.status == "Closed":
        raise HTTPException(409, "This request is closed.")
    now = utcnow()
    if b.assigneeId or b.unassign:
        if b.assigneeId:
            u = db.get(User, b.assigneeId)
            if not u or role_of(u, get_config(db)) not in AGENT_ROLES:
                raise HTTPException(400, "Assign to someone in IT support.")
        t.assignee_id = None if b.unassign else b.assigneeId
        if t.assignee_id and t.status == "New":
            t.status = "Open"
        if not t.assignee_id and t.status == "Open":
            t.status = "New"
        _msg(db, t, cu.id, f"Assigned to {user_name(db, t.assignee_id)}" if t.assignee_id else "Unassigned", "system", at=now)
    if b.priority and b.priority != t.priority:
        if b.priority not in PRIORITY_HOURS:
            raise HTTPException(400, "Unknown priority.")
        _msg(db, t, cu.id, f"Priority changed from {t.priority} to {b.priority}", "system", at=now + timedelta(milliseconds=1))
        t.priority = b.priority; t.due_at = t.created_at + timedelta(hours=PRIORITY_HOURS[b.priority])
    t.updated_at = now; t.last_message_at = now; t.last_message_by = cu.id
    db.commit()
    return ticket_json(t)


class Confirm(BaseModel):
    fixed: bool


@router.post("/{tid}/confirm")
def confirm(tid: str, b: Confirm, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    t = _ticket(db, tid, cu, lock=True)
    if t.requester_id != cu.id or t.status != "Solved":
        raise HTTPException(409, "Only the requester can confirm a solved request.")
    now = utcnow()
    if b.fixed:
        t.status = "Closed"; t.closed_at = now
        _msg(db, t, cu.id, "Closed — the employee confirmed it's fixed", "system", at=now)
    else:
        t.status = "Open" if t.assignee_id else "New"; t.solved_at = None
        _msg(db, t, cu.id, "Reopened — the employee says it isn't fixed", "system", at=now)
    t.updated_at = now; t.last_message_at = now; t.last_message_by = cu.id
    db.commit()
    return ticket_json(t)


class Rate(BaseModel):
    rating: str = Field(pattern="^(good|bad)$")


@router.post("/{tid}/rate")
def rate(tid: str, b: Rate, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    t = _ticket(db, tid, cu, lock=True)
    if t.requester_id != cu.id or t.status != "Closed" or t.rating:
        raise HTTPException(409, "You can rate a request once, after it's closed.")
    t.rating = b.rating
    _msg(db, t, cu.id, f"Employee rated the support: {'Good' if b.rating == 'good' else 'Not good'}", "system")
    db.commit()
    return ticket_json(t)


class Repair(BaseModel):
    on: bool


@router.post("/{tid}/repair")
def repair(tid: str, b: Repair, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("tickets.manage")
    t = _ticket(db, tid, cu)
    if not t.asset_id:
        raise HTTPException(400, "This request has no asset.")
    a = get_asset(db, t.asset_id, lock=True)
    if b.on and a.status in ("In use", "In stock"):
        a.status = "Under repair"; log_asset(db, a, cu.id, f"Under repair for {t.id}")
    elif not b.on and a.status == "Under repair":
        a.status = "In use" if a.assigned_to else "In stock"; log_asset(db, a, cu.id, f"Back in service after {t.id}")
    db.commit()
    return {"status": a.status}


@router.post("/{tid}/suggest")
def suggest(tid: str, cu: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    cu.require("tickets.manage")
    t = _ticket(db, tid, cu)
    ms = db.execute(select(TicketMessage).where(TicketMessage.ticket_id == t.id, TicketMessage.kind != "system")
                    .order_by(TicketMessage.at.desc()).limit(12)).scalars().all()
    hist = "\n".join(f"{'Employee' if m.by_user == t.requester_id else 'IT'}{' (internal note)' if m.kind == 'internal' else ''}: {m.body}" for m in reversed(ms))
    a = get_asset(db, t.asset_id) if t.asset_id else None
    prompt = (f"You are drafting a reply from a company IT support agent to an employee, inside a help-desk chat.\n"
              f"Request: {t.subject}\nType: {t.category} · Priority: {t.priority}\n"
              f"Asset: {a.name + ' (' + a.category + (', model ' + a.model if a.model else '') + ', serial ' + (t.asset_serial or 'unknown') + ')' if a else 'unknown'}\n\n"
              f"Conversation so far:\n{hist[-6000:]}\n\n"
              "Write only the reply text the agent will send: friendly, plain language, under 130 words. If useful, give numbered "
              "troubleshooting steps the employee can try, and say what IT will do next if they don't work. Don't invent policies, "
              "dates or promises. No subject line, no signature, no placeholders.")
    return {"text": ai.draft_reply(prompt)}
