from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import String, Integer, BigInteger, Text, Date, DateTime, Numeric, ForeignKey, JSON
from sqlalchemy.dialects.mysql import DATETIME as MYSQL_DATETIME
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


DT3 = DateTime().with_variant(MYSQL_DATETIME(fsp=3), "mysql")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    provider: Mapped[str | None] = mapped_column(String(16))
    provider_subject: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str | None] = mapped_column(String(32))
    department: Mapped[str | None] = mapped_column(String(120))
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_sign_in_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_by: Mapped[str | None] = mapped_column(String(36))


class File(Base):
    __tablename__ = "files"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(500))
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(64), default="Other")
    status: Mapped[str] = mapped_column(String(24), default="In stock")
    serial: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(160))
    vendor: Mapped[str | None] = mapped_column(String(200))
    vendor_tax_id: Mapped[str | None] = mapped_column(String(40))
    invoice_number: Mapped[str | None] = mapped_column(String(80))
    invoice_file_id: Mapped[str | None] = mapped_column(ForeignKey("files.id"))
    location: Mapped[str | None] = mapped_column(String(160))
    department: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    purchase_date: Mapped[date | None] = mapped_column(Date)
    in_service_date: Mapped[date | None] = mapped_column(Date)
    cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    salvage: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    life_years: Mapped[int] = mapped_column(Integer, default=3)
    method: Mapped[str] = mapped_column(String(4), default="SL")
    wdv_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    source: Mapped[str] = mapped_column(String(16), default="manual")
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    allocated_at: Mapped[datetime | None] = mapped_column(DateTime)
    allocated_by: Mapped[str | None] = mapped_column(String(36))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
    acknowledged_by: Mapped[str | None] = mapped_column(String(36))
    acknowledged_name: Mapped[str | None] = mapped_column(String(255))
    disposed_at: Mapped[datetime | None] = mapped_column(DateTime)
    sold_to: Mapped[str | None] = mapped_column(String(36))
    sale_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    sale_id: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    allocations: Mapped[list["Allocation"]] = relationship(back_populates="asset", order_by="Allocation.from_at", cascade="all, delete-orphan")
    log: Mapped[list["AssetLog"]] = relationship(order_by="AssetLog.at", cascade="all, delete-orphan")


class Allocation(Base):
    __tablename__ = "asset_allocations"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    employee_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    from_at: Mapped[datetime] = mapped_column(DateTime)
    until_at: Mapped[datetime | None] = mapped_column(DateTime)
    allocated_by: Mapped[str | None] = mapped_column(String(36))
    note: Mapped[str | None] = mapped_column(String(500))
    return_condition: Mapped[str | None] = mapped_column(String(40))
    return_note: Mapped[str | None] = mapped_column(String(500))
    asset: Mapped[Asset] = relationship(back_populates="allocations")


class AssetLog(Base):
    __tablename__ = "asset_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    at: Mapped[datetime] = mapped_column(DT3)
    by_user: Mapped[str | None] = mapped_column(String(36))
    text: Mapped[str] = mapped_column(String(1000))


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    subject: Mapped[str] = mapped_column(String(200))
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    asset_tag: Mapped[str | None] = mapped_column(String(16))
    asset_name: Mapped[str | None] = mapped_column(String(255))
    asset_serial: Mapped[str | None] = mapped_column(String(120))
    category: Mapped[str | None] = mapped_column(String(64))
    priority: Mapped[str] = mapped_column(String(16), default="Medium")
    status: Mapped[str] = mapped_column(String(16), default="New")
    requester_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    due_at: Mapped[datetime | None] = mapped_column(DateTime)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolution: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[str | None] = mapped_column(String(8))
    last_message_at: Mapped[datetime | None] = mapped_column(DT3)
    last_message_by: Mapped[str | None] = mapped_column(String(36))
    last_public_at: Mapped[datetime | None] = mapped_column(DT3)
    last_preview: Mapped[str | None] = mapped_column(String(200))


class TicketMessage(Base):
    __tablename__ = "ticket_messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"))
    at: Mapped[datetime] = mapped_column(DT3)
    by_user: Mapped[str | None] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(10))
    body: Mapped[str] = mapped_column(Text)
    attachment_file_id: Mapped[str | None] = mapped_column(ForeignKey("files.id"))
    attachment: Mapped[File | None] = relationship(lazy="joined")


class AssetReturn(Base):
    __tablename__ = "asset_returns"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    type: Mapped[str] = mapped_column(String(8))
    employee_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(Text)
    planned_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_day: Mapped[date | None] = mapped_column(Date)
    department: Mapped[str | None] = mapped_column(String(120))
    personal_email: Mapped[str | None] = mapped_column(String(255))
    stage: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime)
    it_signoff_by: Mapped[str | None] = mapped_column(String(36))
    it_signoff_at: Mapped[datetime | None] = mapped_column(DateTime)
    it_comment: Mapped[str | None] = mapped_column(Text)
    fin_signoff_by: Mapped[str | None] = mapped_column(String(36))
    fin_signoff_at: Mapped[datetime | None] = mapped_column(DateTime)
    fin_comment: Mapped[str | None] = mapped_column(Text)
    fin_deduction: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    ff_status: Mapped[str | None] = mapped_column(String(16))
    ff_deducted_at: Mapped[datetime | None] = mapped_column(DateTime)
    items: Mapped[list["ReturnItem"]] = relationship(order_by="ReturnItem.id", cascade="all, delete-orphan")
    history: Mapped[list["ReturnHistory"]] = relationship(order_by="ReturnHistory.at", cascade="all, delete-orphan")


class ReturnItem(Base):
    __tablename__ = "return_items"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    return_id: Mapped[str] = mapped_column(ForeignKey("asset_returns.id"))
    item_key: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(8))
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    tag: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(255))
    serial: Mapped[str | None] = mapped_column(String(120))
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    book_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    state: Mapped[str] = mapped_column(String(12), default="Pending")
    condition: Mapped[str | None] = mapped_column("condition", String(12))
    recovery: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    note: Mapped[str | None] = mapped_column(String(500))
    by_user: Mapped[str | None] = mapped_column(String(36))
    at: Mapped[datetime | None] = mapped_column(DateTime)


class ReturnHistory(Base):
    __tablename__ = "return_history"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    return_id: Mapped[str] = mapped_column(ForeignKey("asset_returns.id"))
    at: Mapped[datetime] = mapped_column(DT3)
    by_user: Mapped[str | None] = mapped_column(String(36))
    text: Mapped[str] = mapped_column(String(1000))


class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    tag: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(255))
    serial: Mapped[str | None] = mapped_column(String(120))
    employee_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    cost_at_offer: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    book_value_at_offer: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    book_value_at_sale: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    instalments: Mapped[int] = mapped_column(Integer)
    start_month: Mapped[str] = mapped_column(String(7))
    note: Mapped[str | None] = mapped_column(String(500))
    stage: Mapped[str] = mapped_column(String(24))
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    fin_by: Mapped[str | None] = mapped_column(String(36))
    fin_at: Mapped[datetime | None] = mapped_column(DateTime)
    fin_comment: Mapped[str | None] = mapped_column(String(500))
    accepted_name: Mapped[str | None] = mapped_column(String(255))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime)
    sold_at: Mapped[datetime | None] = mapped_column(DateTime)
    schedule: Mapped[list["SaleInstalment"]] = relationship(order_by="SaleInstalment.no", cascade="all, delete-orphan")
    history: Mapped[list["SaleHistory"]] = relationship(order_by="SaleHistory.at", cascade="all, delete-orphan")


class SaleInstalment(Base):
    __tablename__ = "sale_instalments"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sale_id: Mapped[str] = mapped_column(ForeignKey("sales.id"))
    no: Mapped[int] = mapped_column(Integer)
    month: Mapped[str] = mapped_column(String(7))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(24), default="Scheduled")
    at: Mapped[datetime | None] = mapped_column(DateTime)
    by_user: Mapped[str | None] = mapped_column(String(36))


class SaleHistory(Base):
    __tablename__ = "sale_history"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sale_id: Mapped[str] = mapped_column(ForeignKey("sales.id"))
    at: Mapped[datetime] = mapped_column(DT3)
    by_user: Mapped[str | None] = mapped_column(String(36))
    text: Mapped[str] = mapped_column(String(1000))
