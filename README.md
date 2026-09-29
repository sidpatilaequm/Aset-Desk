# Asset Desk

IT asset management with depreciation, invoice reading, employee allocation, a chat-based support desk, returns, exit clearance, sales of assets to employees and a salary-deduction payroll input.

| Layer | Technology | Folder |
|---|---|---|
| Front end | HTML5 + vanilla JavaScript (single page, no build step) | `frontend/index.html` |
| Middleware | Python 3.11+ · FastAPI · SQLAlchemy 2 · Authlib (OpenID Connect) | `backend/app/` |
| Database | MySQL 8 (InnoDB, utf8mb4, UTC timestamps) | `database/schema.sql` |

The browser never touches the database. Every action goes through the Python API, which checks the signed-in person's role and enforces the workflow rules (who can allocate, receive returns, sign off, approve sales, and so on).

```
Browser (index.html) ──HTTPS/JSON──▶ FastAPI (auth, roles, workflows) ──SQL──▶ MySQL
                                        │
                                        ├─▶ Microsoft Entra ID / Google (sign-in)
                                        └─▶ Claude API (invoice reading, reply drafts — optional)
```

## Quick start with Docker

```bash
cp backend/.env.example backend/.env      # then edit it (see "Configuration")
export DB_PASSWORD='a-strong-password' DB_ROOT_PASSWORD='another-strong-password'
docker compose up -d --build
```

Open http://localhost:8000. MySQL creates the tables from `database/schema.sql` on first start.

## Manual setup

1. **MySQL 8** — create a database and user:

   ```sql
   CREATE DATABASE assetdesk CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
   CREATE USER 'assetdesk'@'%' IDENTIFIED BY 'a-strong-password';
   GRANT ALL ON assetdesk.* TO 'assetdesk'@'%';
   ```

2. **Python**

   ```bash
   cd backend
   python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   cp .env.example .env                                    # edit DATABASE_URL, SECRET_KEY, ADMIN_EMAILS …
   python -m app.init_db                                   # creates the tables (safe to re-run)
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

3. Open http://localhost:8000.

For a first look without SSO, set `DEV_LOGIN=true` in `.env`: the sign-in page then shows an email/name form. Sign in with an address listed in `ADMIN_EMAILS` to get the Admin role. **Never enable `DEV_LOGIN` in production.**

## Configuration (`backend/.env`)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | `mysql+pymysql://user:password@host:3306/assetdesk?charset=utf8mb4` |
| `SECRET_KEY` | Signs the session cookie. Generate with `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `BASE_URL` | Public URL, used to build OAuth redirect URIs, e.g. `https://assets.yourcompany.com` |
| `ADMIN_EMAILS` | Comma-separated emails that are Admin by default and can always manage people and settings |
| `COOKIE_SECURE` | `true` when served over HTTPS |
| `UPLOAD_DIR` | Where invoices and chat attachments are stored |
| `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET` | Microsoft Entra ID sign-in |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google Workspace sign-in |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Optional. Enables invoice reading and "Suggest reply" (default model `claude-sonnet-5-5`) |
| `DEV_LOGIN` | `true` only for local development |

### Microsoft Entra ID (Azure AD)

1. Azure portal → **Microsoft Entra ID → App registrations → New registration**.
2. Supported account types: *Accounts in this organizational directory only*.
3. Redirect URI (Web): `{BASE_URL}/auth/callback/microsoft`.
4. **Certificates & secrets → New client secret** → copy the value to `MS_CLIENT_SECRET`.
5. Copy *Directory (tenant) ID* → `MS_TENANT_ID` and *Application (client) ID* → `MS_CLIENT_ID`.
6. Optional, for group-based roles: **Token configuration → Add groups claim → Security groups**. Then in the app, under **Sign-in & settings**, map group object IDs to roles, one per line, for example `3f1c… = IT Support`. The mapping is applied the first time a person without a role signs in.

### Google Workspace

1. Google Cloud console → **APIs & Services → Credentials → Create credentials → OAuth client ID** (type *Web application*).
2. Authorised redirect URI: `{BASE_URL}/auth/callback/google`.
3. Copy the client ID and secret to `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
4. In the app, set the **Allowed email domain** for Google. The server checks both the email and Google's `hd` (hosted domain) claim.

A provider appears on the sign-in page only when its keys are set in `.env` and it's allowed under **Sign-in & settings**.

## Roles

| Role | Can do |
|---|---|
| Admin | People, roles and settings. Sees everything, but doesn't allocate, receive or sign off (separation of duties) |
| IT Asset Manager | Add and import assets, **allocate** to employees (with date and time), take assets back, receive returns and exit handovers, propose sales |
| IT Manager | Sign off exit clearances |
| Finance | Depreciation settings and reports, approve sales, final exit sign-off, payroll deductions |
| IT Support | Support inbox: reply, assign, solve |
| Employee | See their own assets, sign for them, raise support requests on them, return them, submit exit clearance, accept purchase offers |

Nobody can approve or process their own request, return, clearance or sale.

## Workflows

- **Allocation** — Allocations page. Pick an in-stock asset, the employee and the handover date and time. Every hand-over is stored in `asset_allocations` with `from_at` and `until_at`.
- **Support** — Employees raise chat requests on their own assets only; the asset's serial is selected for them. IT replies, adds internal notes, and sets the status to Open, Pending, On-hold or Solved. The employee confirms the fix, which closes the request, or replies, which reopens it.
- **Routine returns** — Returns & leaving → Return an asset. The IT Asset Manager records the condition (Good, Damaged or Not returned) and any recovery amount.
- **Exit clearance** — The employee lists assets and other items → IT Asset Manager records the handover → IT Manager signs off → Finance signs off and sets the deduction for full and final settlement → a certificate can be downloaded.
- **Sale to employee** — Offer (price, instalments, first salary month) → Finance approval → the employee accepts and authorises deductions → the asset is marked Sold and depreciation stops. Any balance still unpaid when the employee leaves is recovered in full and final settlement.
- **Payroll input** — Sales to employees → Salary deductions: each employee's deductions for a month (sale instalments plus final-settlement deductions), with a CSV export for your payroll team.
- **Asset history** — Search by serial number to see purchase, every allocation and return with date and time, support requests, repairs, and sale.

## API

The browser uses these endpoints. With `DEV_LOGIN=true`, interactive docs are at `/api/docs`.

| Area | Endpoints |
|---|---|
| Session | `GET /api/public-config`, `GET /api/state`, `/auth/login/{provider}`, `/auth/callback/{provider}`, `POST /auth/logout` |
| Assets | `POST /api/assets`, `PATCH /api/assets/{id}`, `DELETE /api/assets/{id}`, `POST /api/assets/{id}/allocate`, `/return`, `/acknowledge`, `POST /api/ocr`, `POST /api/assets/import` |
| Support | `POST /api/tickets`, `GET/POST /api/tickets/{id}/messages`, `PATCH /api/tickets/{id}`, `/confirm`, `/rate`, `/repair`, `/suggest` |
| Returns and exits | `POST /api/returns`, `POST /api/exits`, `/api/returns/{id}/items/{key}/receive`, `/add-asset`, `/withdraw`, `/it-signoff`, `/finance-signoff`, `GET /certificate` |
| Sales and payroll | `POST /api/sales`, `/api/sales/{id}/approve`, `/accept`, `/cancel`, `GET /api/payroll?month=YYYY-MM`, `GET /api/payroll.csv`, `POST /api/payroll/deduct` |
| People and settings | `PUT /api/people/{id}/role`, `POST /api/people`, `PUT /api/config`, `POST /api/files`, `GET /files/{id}` |

State-changing requests must send the header `X-Requested-With: AssetDesk` (CSRF protection).

## Testing

`backend/tests/smoke_test.py` walks through every workflow against a real database. Point `DATABASE_URL` at an **empty test database**, then run it with `DEV_LOGIN=true` and `ADMIN_EMAILS=admin@acme.test`:

```bash
cd backend && python tests/smoke_test.py
```

## Production checklist

- Put it behind HTTPS (nginx, IIS, Azure App Service or a load balancer), set `COOKIE_SECURE=true`, and set `BASE_URL` to the https URL.
- `DEV_LOGIN=false`, and a long random `SECRET_KEY`.
- Back up the MySQL database and the `UPLOAD_DIR` folder.
- Uploaded files are served only to signed-in users, under unguessable IDs. Put `UPLOAD_DIR` on storage that is backed up and not publicly reachable.
- The browser refreshes data every 15 seconds and open chats every 4 seconds. For large teams, run several uvicorn workers (`--workers 4`).
