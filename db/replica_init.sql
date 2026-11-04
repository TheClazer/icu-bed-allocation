-- City ICU Bed Allocation System
-- replica_init.sql (runs on the REPLICA once, when its data volume is empty).
--
-- GTID auto-positioning: the replica asks the primary for every transaction
-- whose GTID it has not executed yet, so it replays the whole history
-- (schema, triggers, events, seed data) and then follows new writes.
-- Asynchronous: the primary commits without waiting for the replica.

CHANGE REPLICATION SOURCE TO
  SOURCE_HOST = 'mysql',
  SOURCE_PORT = 3306,
  SOURCE_USER = 'repl',
  SOURCE_PASSWORD = 'replpass',
  SOURCE_AUTO_POSITION = 1,
  GET_SOURCE_PUBLIC_KEY = 1,
  SOURCE_CONNECT_RETRY = 2,
  SOURCE_RETRY_COUNT = 100000,
  SOURCE_HEARTBEAT_PERIOD = 1;

START REPLICA;

-- Nobody but the replication threads may write here.
SET PERSIST read_only = ON;
SET PERSIST super_read_only = ON;
