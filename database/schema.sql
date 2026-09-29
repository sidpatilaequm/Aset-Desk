-- Asset Desk — MySQL 8 schema
-- All timestamps are stored in UTC.
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS users (
  id                VARCHAR(36)  NOT NULL PRIMARY KEY,
  email             VARCHAR(255) NOT NULL,
  name              VARCHAR(255) NOT NULL DEFAULT '',
  provider          VARCHAR(16)  NULL COMMENT 'microsoft | google | dev; NULL = added by IT, not signed in yet',
  provider_subject  VARCHAR(255) NULL,
  role              VARCHAR(32)  NULL COMMENT 'explicit role; NULL = provider default',
  department        VARCHAR(120) NULL,
  first_seen_at     DATETIME     NULL,
  last_sign_in_at   DATETIME     NULL,
  created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS settings (
  `key`       VARCHAR(64) NOT NULL PRIMARY KEY,
  value       JSON        NOT NULL,
  updated_at  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by  VARCHAR(36) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Sequential reference numbers (AST-, TKT-, RET-, EXT-, SAL-), incremented under a row lock
CREATE TABLE IF NOT EXISTS counters (
  name   VARCHAR(16) NOT NULL PRIMARY KEY,
  value  INT         NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS files (
  id            CHAR(32)     NOT NULL PRIMARY KEY,
  filename      VARCHAR(255) NOT NULL,
  content_type  VARCHAR(100) NOT NULL,
  size_bytes    INT          NOT NULL,
  storage_path  VARCHAR(500) NOT NULL,
  uploaded_by   VARCHAR(36)  NULL,
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_files_user FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS assets (
  id                 VARCHAR(16)   NOT NULL PRIMARY KEY COMMENT 'AST-00001',
  name               VARCHAR(255)  NOT NULL,
  category           VARCHAR(64)   NOT NULL DEFAULT 'Other',
  status             VARCHAR(24)   NOT NULL DEFAULT 'In stock',
  serial             VARCHAR(120)  NULL,
  model              VARCHAR(160)  NULL,
  vendor             VARCHAR(200)  NULL,
  vendor_tax_id      VARCHAR(40)   NULL,
  invoice_number     VARCHAR(80)   NULL,
  invoice_file_id    CHAR(32)      NULL,
  location           VARCHAR(160)  NULL,
  department         VARCHAR(120)  NULL,
  notes              TEXT          NULL,
  purchase_date      DATE          NULL,
  in_service_date    DATE          NULL,
  cost               DECIMAL(14,2) NOT NULL DEFAULT 0,
  salvage            DECIMAL(14,2) NOT NULL DEFAULT 0,
  life_years         INT           NOT NULL DEFAULT 3,
  method             VARCHAR(4)    NOT NULL DEFAULT 'SL' COMMENT 'SL | WDV | DDB | SYD',
  wdv_rate           DECIMAL(6,2)  NULL,
  source             VARCHAR(16)   NOT NULL DEFAULT 'manual',
  assigned_to        VARCHAR(36)   NULL,
  allocated_at       DATETIME      NULL,
  allocated_by       VARCHAR(36)   NULL,
  acknowledged_at    DATETIME      NULL,
  acknowledged_by    VARCHAR(36)   NULL,
  acknowledged_name  VARCHAR(255)  NULL,
  disposed_at        DATETIME      NULL,
  sold_to            VARCHAR(36)   NULL,
  sale_price         DECIMAL(14,2) NULL,
  sale_id            VARCHAR(16)   NULL,
  created_at         DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by         VARCHAR(36)   NULL,
  updated_at         DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ix_assets_serial (serial),
  KEY ix_assets_assigned (assigned_to),
  KEY ix_assets_status (status),
  CONSTRAINT fk_assets_assigned FOREIGN KEY (assigned_to) REFERENCES users(id),
  CONSTRAINT fk_assets_invoice  FOREIGN KEY (invoice_file_id) REFERENCES files(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Every hand-over: who had the asset, from when (date & time) until when, and how it came back
CREATE TABLE IF NOT EXISTS asset_allocations (
  id                BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
  asset_id          VARCHAR(16)  NOT NULL,
  employee_id       VARCHAR(36)  NOT NULL,
  from_at           DATETIME     NOT NULL,
  until_at          DATETIME     NULL,
  allocated_by      VARCHAR(36)  NULL,
  note              VARCHAR(500) NULL,
  return_condition  VARCHAR(40)  NULL,
  return_note       VARCHAR(500) NULL,
  KEY ix_alloc_asset (asset_id, from_at),
  KEY ix_alloc_employee (employee_id),
  CONSTRAINT fk_alloc_asset FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE,
  CONSTRAINT fk_alloc_employee FOREIGN KEY (employee_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS asset_log (
  id        BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
  asset_id  VARCHAR(16)   NOT NULL,
  at        DATETIME(3)   NOT NULL,
  by_user   VARCHAR(36)   NULL,
  text      VARCHAR(1000) NOT NULL,
  KEY ix_log_asset (asset_id, at),
  CONSTRAINT fk_log_asset FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS tickets (
  id                 VARCHAR(16)   NOT NULL PRIMARY KEY COMMENT 'TKT-00001',
  subject            VARCHAR(200)  NOT NULL,
  asset_id           VARCHAR(16)   NULL,
  asset_tag          VARCHAR(16)   NULL,
  asset_name         VARCHAR(255)  NULL,
  asset_serial       VARCHAR(120)  NULL COMMENT 'serial at the time the request was raised',
  category           VARCHAR(64)   NULL,
  priority           VARCHAR(16)   NOT NULL DEFAULT 'Medium',
  status             VARCHAR(16)   NOT NULL DEFAULT 'New',
  requester_id       VARCHAR(36)   NOT NULL,
  assignee_id        VARCHAR(36)   NULL,
  created_at         DATETIME      NOT NULL,
  updated_at         DATETIME      NOT NULL,
  due_at             DATETIME      NULL,
  first_response_at  DATETIME      NULL,
  solved_at          DATETIME      NULL,
  closed_at          DATETIME      NULL,
  resolution         TEXT          NULL,
  rating             VARCHAR(8)    NULL,
  last_message_at    DATETIME(3)   NULL,
  last_message_by    VARCHAR(36)   NULL,
  last_public_at     DATETIME(3)   NULL,
  last_preview       VARCHAR(200)  NULL,
  KEY ix_tickets_asset (asset_id),
  KEY ix_tickets_requester (requester_id),
  KEY ix_tickets_status (status),
  CONSTRAINT fk_tickets_asset FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE SET NULL,
  CONSTRAINT fk_tickets_requester FOREIGN KEY (requester_id) REFERENCES users(id),
  CONSTRAINT fk_tickets_assignee FOREIGN KEY (assignee_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ticket_messages (
  id                  BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
  ticket_id           VARCHAR(16)  NOT NULL,
  at                  DATETIME(3)  NOT NULL,
  by_user             VARCHAR(36)  NULL,
  kind                VARCHAR(10)  NOT NULL COMMENT 'public | internal | system',
  body                TEXT         NOT NULL,
  attachment_file_id  CHAR(32)     NULL,
  KEY ix_msg_ticket (ticket_id, at),
  CONSTRAINT fk_msg_ticket FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE,
  CONSTRAINT fk_msg_file FOREIGN KEY (attachment_file_id) REFERENCES files(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Routine returns (RET-) and exit clearances (EXT-)
CREATE TABLE IF NOT EXISTS asset_returns (
  id              VARCHAR(16)   NOT NULL PRIMARY KEY,
  type            VARCHAR(8)    NOT NULL COMMENT 'return | exit',
  employee_id     VARCHAR(36)   NOT NULL,
  reason          VARCHAR(80)   NULL,
  note            TEXT          NULL,
  planned_at      DATETIME      NULL,
  last_day        DATE          NULL,
  department      VARCHAR(120)  NULL,
  personal_email  VARCHAR(255)  NULL,
  stage           VARCHAR(24)   NOT NULL,
  created_at      DATETIME      NOT NULL,
  updated_at      DATETIME      NOT NULL,
  cleared_at      DATETIME      NULL,
  it_signoff_by   VARCHAR(36)   NULL,
  it_signoff_at   DATETIME      NULL,
  it_comment      TEXT          NULL,
  fin_signoff_by  VARCHAR(36)   NULL,
  fin_signoff_at  DATETIME      NULL,
  fin_comment     TEXT          NULL,
  fin_deduction   DECIMAL(14,2) NULL,
  ff_status       VARCHAR(16)   NULL,
  ff_deducted_at  DATETIME      NULL,
  KEY ix_returns_employee (employee_id),
  KEY ix_returns_stage (stage),
  CONSTRAINT fk_returns_employee FOREIGN KEY (employee_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS return_items (
  id           BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
  return_id    VARCHAR(16)   NOT NULL,
  item_key     VARCHAR(40)   NOT NULL,
  kind         VARCHAR(8)    NOT NULL COMMENT 'asset | other',
  asset_id     VARCHAR(16)   NULL,
  tag          VARCHAR(16)   NULL,
  name         VARCHAR(255)  NOT NULL,
  serial       VARCHAR(120)  NULL,
  cost         DECIMAL(14,2) NULL,
  book_value   DECIMAL(14,2) NULL,
  state        VARCHAR(12)   NOT NULL DEFAULT 'Pending' COMMENT 'Pending | Received | Missing',
  `condition`  VARCHAR(12)   NULL,
  recovery     DECIMAL(14,2) NOT NULL DEFAULT 0,
  note         VARCHAR(500)  NULL,
  by_user      VARCHAR(36)   NULL,
  at           DATETIME      NULL,
  UNIQUE KEY uq_item (return_id, item_key),
  CONSTRAINT fk_items_return FOREIGN KEY (return_id) REFERENCES asset_returns(id) ON DELETE CASCADE,
  CONSTRAINT fk_items_asset FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS return_history (
  id         BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
  return_id  VARCHAR(16)   NOT NULL,
  at         DATETIME(3)   NOT NULL,
  by_user    VARCHAR(36)   NULL,
  text       VARCHAR(1000) NOT NULL,
  KEY ix_rh (return_id, at),
  CONSTRAINT fk_rh_return FOREIGN KEY (return_id) REFERENCES asset_returns(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Sale of a company asset to an employee, recovered from salary
CREATE TABLE IF NOT EXISTS sales (
  id                  VARCHAR(16)   NOT NULL PRIMARY KEY COMMENT 'SAL-00001',
  asset_id            VARCHAR(16)   NULL,
  tag                 VARCHAR(16)   NOT NULL,
  name                VARCHAR(255)  NOT NULL,
  serial              VARCHAR(120)  NULL,
  employee_id         VARCHAR(36)   NOT NULL,
  price               DECIMAL(14,2) NOT NULL,
  cost_at_offer       DECIMAL(14,2) NULL,
  book_value_at_offer DECIMAL(14,2) NULL,
  book_value_at_sale  DECIMAL(14,2) NULL,
  instalments         INT           NOT NULL,
  start_month         CHAR(7)       NOT NULL COMMENT 'YYYY-MM',
  note                VARCHAR(500)  NULL,
  stage               VARCHAR(24)   NOT NULL,
  created_by          VARCHAR(36)   NOT NULL,
  created_at          DATETIME      NOT NULL,
  updated_at          DATETIME      NOT NULL,
  fin_by              VARCHAR(36)   NULL,
  fin_at              DATETIME      NULL,
  fin_comment         VARCHAR(500)  NULL,
  accepted_name       VARCHAR(255)  NULL,
  accepted_at         DATETIME      NULL,
  sold_at             DATETIME      NULL,
  KEY ix_sales_employee (employee_id),
  KEY ix_sales_asset (asset_id),
  CONSTRAINT fk_sales_asset FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE SET NULL,
  CONSTRAINT fk_sales_employee FOREIGN KEY (employee_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sale_instalments (
  id       BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
  sale_id  VARCHAR(16)   NOT NULL,
  no       INT           NOT NULL,
  month    CHAR(7)       NOT NULL,
  amount   DECIMAL(14,2) NOT NULL,
  status   VARCHAR(24)   NOT NULL DEFAULT 'Scheduled' COMMENT 'Scheduled | Deducted | Recovered in F&F',
  at       DATETIME      NULL,
  by_user  VARCHAR(36)   NULL,
  UNIQUE KEY uq_inst (sale_id, no),
  KEY ix_inst_month (month),
  CONSTRAINT fk_inst_sale FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sale_history (
  id       BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
  sale_id  VARCHAR(16)   NOT NULL,
  at       DATETIME(3)   NOT NULL,
  by_user  VARCHAR(36)   NULL,
  text     VARCHAR(1000) NOT NULL,
  KEY ix_sh (sale_id, at),
  CONSTRAINT fk_sh_sale FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
