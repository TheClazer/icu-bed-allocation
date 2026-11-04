-- City ICU Bed Allocation System
-- events.sql: MySQL expires stale holds by itself, no application code involved.

USE icu_beds;

SET GLOBAL event_scheduler = ON;

DROP EVENT IF EXISTS expire_holds;

DELIMITER $$

-- Every 5 seconds: any HELD reservation past its expiry becomes EXPIRED.
-- The AFTER UPDATE trigger on reservation then sets the bed back to FREE
-- and writes the audit_log row (user_id NULL = done by the scheduler).
CREATE EVENT expire_holds
ON SCHEDULE EVERY 5 SECOND
DO
BEGIN
  DECLARE v_now DATETIME;
  SET v_now = sim_now();          -- evaluate the simulated clock once
  UPDATE reservation
     SET status = 'EXPIRED'
   WHERE status = 'HELD'
     AND hold_expires_at < v_now; -- uses idx_hold_expiry (status, hold_expires_at)
END$$

DELIMITER ;
