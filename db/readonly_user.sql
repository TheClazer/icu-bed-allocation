-- City ICU Bed Allocation System
-- readonly_user.sql: the account behind the Query tab.
-- It can read every table and view but cannot change anything, so an evaluator
-- typing DELETE or UPDATE gets refused by MySQL itself (error 1142).

CREATE USER IF NOT EXISTS 'icu_readonly'@'%' IDENTIFIED BY 'readonly';
GRANT SELECT, SHOW VIEW ON icu_beds.* TO 'icu_readonly'@'%';
FLUSH PRIVILEGES;
