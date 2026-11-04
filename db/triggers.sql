-- City ICU Bed Allocation System
-- triggers.sql: the database writes its own audit trail and guards its own rules.
--
-- Session variables set by the application on each connection:
--   @app_user_id  the user acting (NULL for the MySQL event scheduler = "system")
--   @skip_audit   set to 1 only while seed.sql loads demo data

USE icu_beds;

DELIMITER $$

-- ---------------------------------------------------------------------------
-- Bed-blocking guard: one account may hold at most 5 live beds at a time.
-- SIGNAL aborts the INSERT with SQLSTATE 45000 (MySQL error 1644).
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_reservation_hold_limit
BEFORE INSERT ON reservation
FOR EACH ROW
BEGIN
  DECLARE v_user   INT;
  DECLARE v_active INT;
  IF NEW.status = 'HELD' THEN
    SELECT raised_by INTO v_user FROM bed_request WHERE request_id = NEW.request_id;
    SELECT COUNT(*) INTO v_active
      FROM reservation r
      JOIN bed_request q ON q.request_id = r.request_id
     WHERE q.raised_by = v_user AND r.status = 'HELD';
    IF v_active >= 5 THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Hold limit reached: this account already has 5 active holds';
    END IF;
  END IF;
END$$

-- ---------------------------------------------------------------------------
-- New reservation: write to audit_log.
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_reservation_after_insert
AFTER INSERT ON reservation
FOR EACH ROW
BEGIN
  IF COALESCE(@skip_audit, 0) = 0 THEN
    INSERT INTO audit_log (user_id, action, entity_name, entity_id, details)
    SELECT q.raised_by,
           CONCAT('RESERVATION_', NEW.status),
           'reservation',
           NEW.reservation_id,
           JSON_OBJECT('bed_id', NEW.bed_id,
                       'request_id', NEW.request_id,
                       'hold_expires_at', NEW.hold_expires_at)
      FROM bed_request q
     WHERE q.request_id = NEW.request_id;
  END IF;
END$$

-- ---------------------------------------------------------------------------
-- Reservation status change: audit it, and when a live hold ends without
-- admission (EXPIRED or CANCELLED) give the bed back.
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_reservation_after_update
AFTER UPDATE ON reservation
FOR EACH ROW
BEGIN
  IF NEW.status <> OLD.status THEN
    IF COALESCE(@skip_audit, 0) = 0 THEN
      INSERT INTO audit_log (user_id, action, entity_name, entity_id, details)
      VALUES (@app_user_id,
              CONCAT('RESERVATION_', NEW.status),
              'reservation',
              NEW.reservation_id,
              JSON_OBJECT('bed_id', NEW.bed_id,
                          'old_status', OLD.status,
                          'new_status', NEW.status,
                          'by', IF(@app_user_id IS NULL, 'mysql event scheduler', 'application')));
    END IF;

    IF OLD.status = 'HELD' AND NEW.status IN ('EXPIRED', 'CANCELLED') THEN
      UPDATE bed SET status = 'FREE' WHERE bed_id = NEW.bed_id AND status = 'HELD';
    END IF;
  END IF;
END$$

-- ---------------------------------------------------------------------------
-- Bed status or occupant change: audit it. The application tails audit_log
-- to refresh Redis counters, so this trigger is also the change feed.
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_bed_after_update
AFTER UPDATE ON bed
FOR EACH ROW
BEGIN
  IF COALESCE(@skip_audit, 0) = 0
     AND (NEW.status <> OLD.status OR NOT (NEW.patient_id <=> OLD.patient_id)) THEN
    INSERT INTO audit_log (user_id, action, entity_name, entity_id, details)
    VALUES (@app_user_id,
            CONCAT('BED_', NEW.status),
            'bed',
            NEW.bed_id,
            JSON_OBJECT('old_status', OLD.status,
                        'new_status', NEW.status,
                        'old_patient', OLD.patient_id,
                        'new_patient', NEW.patient_id,
                        'hospital_id', NEW.hospital_id,
                        'bed_type_id', NEW.bed_type_id));
  END IF;
END$$

-- ---------------------------------------------------------------------------
-- Transfer outcome: audit it.
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_transfer_after_update
AFTER UPDATE ON transfer
FOR EACH ROW
BEGIN
  IF NEW.status <> OLD.status AND COALESCE(@skip_audit, 0) = 0 THEN
    INSERT INTO audit_log (user_id, action, entity_name, entity_id, details)
    VALUES (@app_user_id,
            CONCAT('TRANSFER_', NEW.status),
            'transfer',
            NEW.transfer_id,
            JSON_OBJECT('patient_id', NEW.patient_id,
                        'from_bed_id', NEW.from_bed_id,
                        'to_bed_id', NEW.to_bed_id,
                        'note', NEW.note));
  END IF;
END$$

DELIMITER ;
