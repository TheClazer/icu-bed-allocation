-- City ICU Bed Allocation System
-- schema.sql: tables, constraints, indexes, simulated clock, views
-- Engine: InnoDB (row locks, MVCC, crash recovery). Default isolation: REPEATABLE READ.

CREATE DATABASE IF NOT EXISTS icu_beds;
USE icu_beds;

-- ---------------------------------------------------------------------------
-- 1. hospital: every hospital in the city network
-- ---------------------------------------------------------------------------
CREATE TABLE hospital (
  hospital_id  INT PRIMARY KEY,
  name         VARCHAR(80)  NOT NULL,
  zone         VARCHAR(20)  NOT NULL,
  latitude     DECIMAL(9,6) NOT NULL,
  longitude    DECIMAL(9,6) NOT NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- 2. bed_type: ICU, ICU_VENTILATOR, OXYGEN
-- ---------------------------------------------------------------------------
CREATE TABLE bed_type (
  bed_type_id    INT PRIMARY KEY,
  name           VARCHAR(30) NOT NULL UNIQUE,
  has_ventilator BOOLEAN     NOT NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- 3. patient (all simulated, no real data)
-- ---------------------------------------------------------------------------
CREATE TABLE patient (
  patient_id    INT AUTO_INCREMENT PRIMARY KEY,
  name          VARCHAR(60) NOT NULL,
  age           INT,
  gender        CHAR(1),
  contact_phone VARCHAR(15),
  CONSTRAINT chk_patient_age    CHECK (age IS NULL OR age BETWEEN 0 AND 120),
  CONSTRAINT chk_patient_gender CHECK (gender IS NULL OR gender IN ('M','F','O'))
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- 4. bed: the scarce resource. status is what every booking fights over.
--    patient_id = current occupant, present only while OCCUPIED (enforced by CHECK).
-- ---------------------------------------------------------------------------
CREATE TABLE bed (
  bed_id       INT PRIMARY KEY,
  hospital_id  INT NOT NULL,
  bed_type_id  INT NOT NULL,
  ward         VARCHAR(20) NOT NULL,
  status       VARCHAR(12) NOT NULL DEFAULT 'FREE',
  patient_id   INT NULL,
  updated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT chk_bed_status   CHECK (status IN ('FREE','HELD','OCCUPIED','MAINTENANCE')),
  CONSTRAINT chk_bed_occupant CHECK ((status = 'OCCUPIED') = (patient_id IS NOT NULL)),
  CONSTRAINT fk_bed_hospital  FOREIGN KEY (hospital_id) REFERENCES hospital(hospital_id),
  CONSTRAINT fk_bed_type      FOREIGN KEY (bed_type_id) REFERENCES bed_type(bed_type_id),
  CONSTRAINT fk_bed_patient   FOREIGN KEY (patient_id)  REFERENCES patient(patient_id),
  -- composite index used by the booking search: type + status + hospital, ordered by bed_id
  INDEX idx_bed_search (bed_type_id, status, hospital_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- 5. user_account: helpline, ambulance, hospital staff, control room
-- ---------------------------------------------------------------------------
CREATE TABLE user_account (
  user_id      INT PRIMARY KEY,
  hospital_id  INT NULL,
  name         VARCHAR(60) NOT NULL,
  phone        VARCHAR(15),
  role         VARCHAR(20) NOT NULL,
  CONSTRAINT chk_user_role CHECK (role IN ('HELPLINE','AMBULANCE','HOSPITAL_STAFF','CONTROL_ROOM')),
  CONSTRAINT fk_user_hospital FOREIGN KEY (hospital_id) REFERENCES hospital(hospital_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- 6. bed_request: one request raised by a user for a patient
-- ---------------------------------------------------------------------------
CREATE TABLE bed_request (
  request_id   INT AUTO_INCREMENT PRIMARY KEY,
  patient_id   INT NOT NULL,
  raised_by    INT NOT NULL,
  bed_type_id  INT NOT NULL,
  severity     TINYINT NOT NULL,
  pickup_lat   DECIMAL(9,6) NOT NULL,
  pickup_lon   DECIMAL(9,6) NOT NULL,
  raw_text     VARCHAR(255),
  status       VARCHAR(12) NOT NULL DEFAULT 'OPEN',
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT chk_request_status   CHECK (status IN ('OPEN','FULFILLED','CANCELLED')),
  CONSTRAINT chk_request_severity CHECK (severity BETWEEN 1 AND 5),
  CONSTRAINT fk_request_patient FOREIGN KEY (patient_id)  REFERENCES patient(patient_id),
  CONSTRAINT fk_request_user    FOREIGN KEY (raised_by)   REFERENCES user_account(user_id),
  CONSTRAINT fk_request_type    FOREIGN KEY (bed_type_id) REFERENCES bed_type(bed_type_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- 7. reservation: a HOLD on one bed for one request.
--    HELD -> ADMITTED (patient arrived) | EXPIRED (30 min passed) | CANCELLED
--
--    active_bed_id is a STORED generated column: it equals bed_id while the hold is
--    live (HELD) and NULL otherwise. A UNIQUE index ignores NULLs, so the index
--    allows any number of finished reservations per bed but at most ONE live hold.
--    This is the last line of defence against double booking, even if the
--    application forgets to lock (see "No lock" mode).
-- ---------------------------------------------------------------------------
CREATE TABLE reservation (
  reservation_id  INT AUTO_INCREMENT PRIMARY KEY,
  request_id      INT NOT NULL,
  bed_id          INT NOT NULL,
  status          VARCHAR(10) NOT NULL,
  hold_expires_at DATETIME NOT NULL,
  admitted_at     DATETIME NULL,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  active_bed_id   INT GENERATED ALWAYS AS
                  (CASE WHEN status = 'HELD' THEN bed_id END) STORED,
  UNIQUE KEY one_active_booking_per_bed (active_bed_id),
  CONSTRAINT chk_reservation_status CHECK (status IN ('HELD','ADMITTED','EXPIRED','CANCELLED')),
  CONSTRAINT fk_reservation_request FOREIGN KEY (request_id) REFERENCES bed_request(request_id),
  CONSTRAINT fk_reservation_bed     FOREIGN KEY (bed_id)     REFERENCES bed(bed_id),
  INDEX idx_hold_expiry (status, hold_expires_at)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- 8. transfer: moving a patient from one bed to another
-- ---------------------------------------------------------------------------
CREATE TABLE transfer (
  transfer_id  INT AUTO_INCREMENT PRIMARY KEY,
  patient_id   INT NOT NULL,
  from_bed_id  INT NOT NULL,
  to_bed_id    INT NOT NULL,
  status       VARCHAR(12) NOT NULL DEFAULT 'PENDING',
  note         VARCHAR(120) NULL,
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT chk_transfer_status CHECK (status IN ('PENDING','DONE','ROLLED_BACK')),
  CONSTRAINT chk_transfer_beds   CHECK (from_bed_id <> to_bed_id),
  CONSTRAINT fk_transfer_patient FOREIGN KEY (patient_id)  REFERENCES patient(patient_id),
  CONSTRAINT fk_transfer_from    FOREIGN KEY (from_bed_id) REFERENCES bed(bed_id),
  CONSTRAINT fk_transfer_to      FOREIGN KEY (to_bed_id)   REFERENCES bed(bed_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- 9. audit_log: written by triggers, never by hand
-- ---------------------------------------------------------------------------
CREATE TABLE audit_log (
  log_id      BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id     INT NULL,
  action      VARCHAR(40) NOT NULL,
  entity_name VARCHAR(30) NOT NULL,
  entity_id   INT,
  details     JSON,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_audit_user FOREIGN KEY (user_id) REFERENCES user_account(user_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------------
-- Simulated clock: all hold-expiry logic reads sim_now() instead of NOW(),
-- so "Fast-forward 30 min" only has to bump offset_minutes.
-- ---------------------------------------------------------------------------
CREATE TABLE sim_clock (
  id             TINYINT PRIMARY KEY DEFAULT 1,
  offset_minutes INT NOT NULL DEFAULT 0,
  CONSTRAINT chk_sim_clock_single_row CHECK (id = 1)
) ENGINE=InnoDB;

INSERT INTO sim_clock (id, offset_minutes) VALUES (1, 0);

CREATE FUNCTION sim_now() RETURNS DATETIME
  NOT DETERMINISTIC READS SQL DATA
  RETURN TIMESTAMPADD(MINUTE, COALESCE((SELECT offset_minutes FROM sim_clock WHERE id = 1), 0), NOW());

-- Replication probe: the app rewrites this row on the primary every second.
-- Comparing it with the replica's copy gives the replication lag in milliseconds.
CREATE TABLE replication_probe (
  id         TINYINT PRIMARY KEY,
  written_at DATETIME(6) NOT NULL
) ENGINE=InnoDB;

INSERT INTO replication_probe (id, written_at) VALUES (1, NOW(6));

-- ---------------------------------------------------------------------------
-- Views
-- ---------------------------------------------------------------------------

-- Hold-to-admit conversion per account. Used by the bed-blocking audit.
CREATE VIEW v_hold_conversion AS
SELECT u.user_id,
       u.name,
       u.role,
       COUNT(*)                                     AS total_holds,
       SUM(r.status = 'ADMITTED')                   AS admitted,
       SUM(r.status = 'HELD')                       AS active,
       SUM(r.status IN ('EXPIRED','CANCELLED'))     AS not_converted,
       ROUND(100 * SUM(r.status IN ('EXPIRED','CANCELLED')) / COUNT(*), 1) AS failure_pct
FROM reservation r
JOIN bed_request  q ON q.request_id = r.request_id
JOIN user_account u ON u.user_id    = q.raised_by
GROUP BY u.user_id, u.name, u.role;

-- Readable bed board: joins names onto the raw bed table.
CREATE VIEW v_bed_board AS
SELECT b.bed_id,
       h.name  AS hospital,
       t.name  AS bed_type,
       b.ward,
       b.status,
       p.name  AS patient,
       b.updated_at
FROM bed b
JOIN hospital h ON h.hospital_id = b.hospital_id
JOIN bed_type t ON t.bed_type_id = b.bed_type_id
LEFT JOIN patient p ON p.patient_id = b.patient_id;
