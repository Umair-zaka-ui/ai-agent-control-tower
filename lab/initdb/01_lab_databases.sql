-- Runs once at container init (disposable). act_lab is created by POSTGRES_DB;
-- lab_payroll is the canary target. Both owned by the synthetic lab role.
CREATE DATABASE lab_payroll OWNER actlab;
