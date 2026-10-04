#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username postgres --dbname postgres \
  --set=remote_password="$REMOTE_DB_PASSWORD" --set=keycloak_password="$KEYCLOAK_DB_PASSWORD" <<'SQL'
CREATE ROLE remote LOGIN PASSWORD :'remote_password';
CREATE DATABASE remote OWNER remote;
CREATE ROLE keycloak LOGIN PASSWORD :'keycloak_password';
CREATE DATABASE keycloak OWNER keycloak;
SQL
