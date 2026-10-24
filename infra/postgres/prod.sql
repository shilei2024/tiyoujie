-- 生产库初始化：只有在数据目录为空时由 postgres 入口脚本执行一次。
--
-- 与 dev.sql 的区别：dev.sql 把角色名和库名写死成 tiyoujie_dev，
-- 生产库名/角色来自 .env.prod，必须参数化，否则会出现
-- “role "tiyoujie" does not exist”，而 PostgreSQL 对此报的错是
-- password authentication failed（防止用户名枚举），极易误判成密码错误。
\getenv app_password APP_DB_PASSWORD
\getenv app_user APP_DB_USER
\getenv app_db APP_DB_NAME

-- :"var" 按标识符引用，:'var' 按字面量引用。
CREATE ROLE :"app_user" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
CREATE DATABASE :"app_db" OWNER :"app_user";
