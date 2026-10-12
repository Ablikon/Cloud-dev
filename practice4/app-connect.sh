#!/bin/bash
# The application's database connection. Note what is NOT in this file:
#   - no password          (fetched from Secrets Manager at runtime)
#   - no IP address        (the endpoint is a DNS name that survives failover)
#   - no master user       (see the least-privilege app user created below)
set -uo pipefail
DB_ENDPOINT="cad-p4-db.c7wu206i6tdu.eu-north-1.rds.amazonaws.com"
DB_SECRET_ARN="arn:aws:secretsmanager:eu-north-1:412004015750:secret:rds!db-cbd6f149-4bd5-4f3f-ae5a-e4c6c885c382-hth61O"

echo "== 1. fetch the credential at runtime, never from the repository =="
SECRET_JSON=$(aws secretsmanager get-secret-value --secret-id "$DB_SECRET_ARN" \
                --query SecretString --output text --region eu-north-1)
DB_USER=$(echo "$SECRET_JSON" | python3 -c 'import json,sys;print(json.load(sys.stdin)["username"])')
export PGPASSWORD=$(echo "$SECRET_JSON" | python3 -c 'import json,sys;print(json.load(sys.stdin)["password"])')
echo "   secret fetched; username = $DB_USER ; password length = ${#PGPASSWORD} chars (value never printed)"
unset SECRET_JSON

echo
echo "== 2. what the endpoint resolves to right now =="
echo "   endpoint : $DB_ENDPOINT"
getent hosts "$DB_ENDPOINT" | awk '{print "   resolves : "$1"   <- a private address inside the VPC, and it will change on failover"}'

echo
echo "== 3. connect by name, with TLS required =="
export PGCONNECT_TIMEOUT=15
PSQL="psql --host=$DB_ENDPOINT --port=5432 --username=$DB_USER --dbname=shop --set=sslmode=require -qtAX"
$PSQL -c "SELECT 'connected to ' || current_database() || ' on ' || inet_server_addr() || ' as ' || current_user;" \
  | sed 's/^/   /'
$PSQL -c "SELECT 'postgres ' || version();" | cut -c1-96 | sed 's/^/   /'
$PSQL -c "SELECT 'TLS in use: ' || ssl || '  cipher: ' || coalesce(cipher,'-') FROM pg_stat_ssl WHERE pid = pg_backend_pid();" | sed 's/^/   /'

echo
echo "== 4. the application does real work =="
$PSQL <<'SQL' | sed 's/^/   /'
CREATE TABLE IF NOT EXISTS orders (
  order_id    text PRIMARY KEY,
  customer_id text NOT NULL,
  status      text NOT NULL,
  total_kzt   integer NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
TRUNCATE orders;
INSERT INTO orders (order_id, customer_id, status, total_kzt) VALUES
  ('o-0001','c-1001','PLACED',1750), ('o-0002','c-1001','SHIPPED',2000),
  ('o-0003','c-1002','DELIVERED',2250), ('o-0004','c-1002','PLACED',2500),
  ('o-0005','c-1003','SHIPPED',2750);
SELECT 'rows: ' || count(*) FROM orders;
SELECT status || ' -> ' || count(*) || ' orders, ' || sum(total_kzt) || ' KZT'
  FROM orders GROUP BY status ORDER BY status;
SQL

echo
echo "== 5. least privilege: the app gets its own user, not the master account =="
$PSQL -v ON_ERROR_STOP=0 <<'SQL' 2>&1 | sed 's/^/   /'
DROP ROLE IF EXISTS app_reader;
CREATE ROLE app_reader LOGIN PASSWORD NULL;
GRANT CONNECT ON DATABASE shop TO app_reader;
GRANT USAGE ON SCHEMA public TO app_reader;
GRANT SELECT ON orders TO app_reader;
SELECT 'app_reader may: ' || string_agg(privilege_type, ', ')
  FROM information_schema.role_table_grants
  WHERE grantee='app_reader' AND table_name='orders';
SQL
echo
echo "   the master user cadadmin is for migrations; app_reader is what the application would use"
