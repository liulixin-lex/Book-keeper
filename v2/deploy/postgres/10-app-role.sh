#!/bin/sh
# Creates the application role (DML only). Grants are applied by `bookkeeper migrate`.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bk_app') THEN
    CREATE ROLE bk_app LOGIN PASSWORD '${BK_APP_DB_PASSWORD}';
  END IF;
END
\$\$;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
