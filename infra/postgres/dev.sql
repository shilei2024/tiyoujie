\getenv app_password APP_DB_PASSWORD
CREATE ROLE tiyoujie_dev LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
CREATE DATABASE tiyoujie_dev OWNER tiyoujie_dev;
