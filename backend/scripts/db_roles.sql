-- Quyền database tối thiểu (L5.2): role riêng cho agent service và kg-worker, không có quyền trên bảng nghiệp vụ.
-- Chạy lại nhiều lần không lỗi (role có sẵn thì đặt lại mật khẩu, quyền cấp lại). Bảng agent chưa tồn tại (database
-- mới, migration agent chưa chạy) được bỏ qua: chạy lại script sau khi migration agent tạo bảng.
--
-- Áp vào database dev (chạy với role chủ sở hữu, ví dụ hercfit):
--   docker exec -i hercfit-postgres psql -U hercfit -d hercfit_db -v ON_ERROR_STOP=1 \
--     -v agent_password='...' -v kg_password='...' < backend/scripts/db_roles.sql
-- Tuỳ chọn: -v agent_role=... -v kg_role=... (mặc định hercfit_agent, hercfit_kg).
--
-- Danh sách bảng lấy từ code (agentic/migrations/*.sql, services/memory/store.py, services/consent_purge.py,
-- knowledge_graph/worker.py, knowledge_graph/context/templates.py, saver của LangGraph):
--   hercfit_agent: đọc/ghi agent_*, checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_migrations,
--                  kg_outbox, kg_query_templates, domain_event_deliveries; chỉ đọc domain_events (cộng UPDATE trên
--                  cột id: consent_purge khoá dòng bằng FOR UPDATE ... SKIP LOCKED, PostgreSQL đòi quyền UPDATE).
--   hercfit_kg:    đọc/ghi kg_outbox; chỉ đọc kg_source_versions.

\if :{?agent_role}
\else
\set agent_role hercfit_agent
\endif
\if :{?kg_role}
\else
\set kg_role hercfit_kg
\endif

-- Biến psql không được thay bên trong khối $$: chuyển qua cấu hình của phiên (chỉ in 'ok', không in mật khẩu).
SELECT 'ok' AS session_config FROM (
    SELECT set_config('hercfit.agent_role', :'agent_role', false),
           set_config('hercfit.kg_role', :'kg_role', false),
           set_config('hercfit.agent_password', :'agent_password', false),
           set_config('hercfit.kg_password', :'kg_password', false)
) AS applied;

DO $roles$
DECLARE
    agent text := current_setting('hercfit.agent_role');
    kg text := current_setting('hercfit.kg_role');
    -- Bảng ngoài tiền tố agent_ mà agent service đọc/ghi.
    agent_tables text[] := ARRAY['checkpoints', 'checkpoint_blobs', 'checkpoint_writes', 'checkpoint_migrations',
                                 'kg_outbox', 'kg_query_templates', 'domain_event_deliveries'];
    agent_read_only text[] := ARRAY['domain_events'];
    kg_tables text[] := ARRAY['kg_outbox'];
    kg_read_only text[] := ARRAY['kg_source_versions'];
    item record;
    granted text[] := '{}';
BEGIN
    IF coalesce(current_setting('hercfit.agent_password'), '') = ''
       OR coalesce(current_setting('hercfit.kg_password'), '') = '' THEN
        RAISE EXCEPTION 'agent_password and kg_password must be set (psql -v agent_password=... -v kg_password=...)';
    END IF;
    FOR item IN SELECT * FROM (VALUES (agent, 'hercfit.agent_password'), (kg, 'hercfit.kg_password')) AS r(name, secret)
    LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = item.name) THEN
            EXECUTE format('ALTER ROLE %I LOGIN PASSWORD %L', item.name, current_setting(item.secret));
        ELSE
            EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', item.name, current_setting(item.secret));
        END IF;
        EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), item.name);
        EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', item.name);
    END LOOP;

    -- Agent service: mọi bảng agent_* hiện có và các bảng liệt kê ở trên.
    FOR item IN
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
          AND (c.relname LIKE 'agent\_%' OR c.relname = ANY (agent_tables))
    LOOP
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.%I TO %I', item.relname, agent);
        granted := granted || item.relname::text;
    END LOOP;
    FOR item IN SELECT unnest(agent_read_only) AS relname LOOP
        IF to_regclass('public.' || quote_ident(item.relname)) IS NOT NULL THEN
            EXECUTE format('GRANT SELECT ON TABLE public.%I TO %I', item.relname, agent);
        END IF;
    END LOOP;
    -- consent_purge đọc sự kiện bằng FOR UPDATE OF e SKIP LOCKED: khoá dòng cần quyền UPDATE trên ít nhất một cột.
    -- Chỉ cấp trên id, cột ít rủi ro nhất (đổi topic, payload hay occurred_at có thể làm sự kiện thu hồi bị bỏ qua).
    IF to_regclass('public.domain_events') IS NOT NULL THEN
        EXECUTE format('GRANT UPDATE (id) ON TABLE public.domain_events TO %I', agent);
    END IF;

    -- kg-worker (database backend): hàng đợi chiếu và phiên bản nguồn.
    FOR item IN SELECT unnest(kg_tables) AS relname LOOP
        IF to_regclass('public.' || quote_ident(item.relname)) IS NOT NULL THEN
            EXECUTE format('GRANT SELECT, UPDATE ON TABLE public.%I TO %I', item.relname, kg);
        END IF;
    END LOOP;
    FOR item IN SELECT unnest(kg_read_only) AS relname LOOP
        IF to_regclass('public.' || quote_ident(item.relname)) IS NOT NULL THEN
            EXECUTE format('GRANT SELECT ON TABLE public.%I TO %I', item.relname, kg);
        END IF;
    END LOOP;

    -- Sequence thuộc các bảng agent được ghi (cột serial/identity).
    FOR item IN
        SELECT DISTINCT s.relname FROM pg_depend d
        JOIN pg_class s ON s.oid = d.objid AND s.relkind = 'S'
        JOIN pg_class t ON t.oid = d.refobjid
        JOIN pg_namespace n ON n.oid = s.relnamespace
        WHERE n.nspname = 'public' AND d.deptype IN ('a', 'i') AND t.relname = ANY (granted)
    LOOP
        EXECUTE format('GRANT USAGE, SELECT, UPDATE ON SEQUENCE public.%I TO %I', item.relname, agent);
    END LOOP;
END
$roles$;
