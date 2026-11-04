-- City ICU Bed Allocation System
-- replication_user.sql (runs on the PRIMARY): account the read replica uses to pull the binary log.

CREATE USER IF NOT EXISTS 'repl'@'%' IDENTIFIED BY 'replpass';
GRANT REPLICATION SLAVE ON *.* TO 'repl'@'%';
