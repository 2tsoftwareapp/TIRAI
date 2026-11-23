CREATE TABLE users (
  id serial PRIMARY KEY,
  email text UNIQUE NOT NULL,
  full_name text,
  status text NOT NULL DEFAULT 'ACTIVE',
  failed_logins int NOT NULL DEFAULT 0,
  last_login_at timestamptz
);
INSERT INTO users (email, full_name, status, failed_logins) VALUES
  ('alice@demo.local', 'Alice Nguyen', 'ACTIVE', 0),
  ('bob@demo.local', 'Bob Tran', 'LOCKED', 5),
  ('carol@demo.local', 'Carol Le', 'ACTIVE', 1);

-- Evidence runs only ever read: DBX and `expect: db` both use this role.
CREATE ROLE evidence_ro LOGIN PASSWORD 'ro_demo_pw';
GRANT SELECT ON ALL TABLES IN SCHEMA public TO evidence_ro;
