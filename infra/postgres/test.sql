\getenv app_password APP_DB_PASSWORD
CREATE ROLE tiyoujie_test LOGIN NOSUPERUSER CREATEDB NOCREATEROLE PASSWORD :'app_password';
CREATE DATABASE tiyoujie_test OWNER tiyoujie_test;
