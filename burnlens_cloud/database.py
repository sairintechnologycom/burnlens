import asyncpg
import hashlib
import logging
import os
from .config import settings

logger = logging.getLogger(__name__)

# Global database pool
pool: asyncpg.Pool = None


async def init_db():
    """Initialize database connection pool and create tables."""
    global pool

    # Create connection pool
    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=2,
        max_size=20,
        command_timeout=60,
    )

    # Create tables
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS workspaces (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name TEXT NOT NULL,
                owner_email TEXT NOT NULL,
                stripe_customer_id TEXT,
                paddle_customer_id TEXT,
                paddle_subscription_id TEXT,
                subscription_status TEXT,
                plan TEXT NOT NULL DEFAULT 'free',
                api_key TEXT UNIQUE NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                active BOOLEAN NOT NULL DEFAULT true,
                otel_endpoint TEXT,
                otel_api_key_encrypted TEXT,
                otel_enabled BOOLEAN NOT NULL DEFAULT false,
                otel_last_push TIMESTAMPTZ
            )
        """)

        # Migration: add Paddle columns for existing deployments (post-Stripe)
        await conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'workspaces' AND column_name = 'paddle_customer_id'
                ) THEN
                    ALTER TABLE workspaces ADD COLUMN paddle_customer_id TEXT;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'workspaces' AND column_name = 'paddle_subscription_id'
                ) THEN
                    ALTER TABLE workspaces ADD COLUMN paddle_subscription_id TEXT;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'workspaces' AND column_name = 'subscription_status'
                ) THEN
                    ALTER TABLE workspaces ADD COLUMN subscription_status TEXT;
                END IF;
            END $$;
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_workspaces_paddle_customer
            ON workspaces(paddle_customer_id) WHERE paddle_customer_id IS NOT NULL
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_workspaces_paddle_subscription
            ON workspaces(paddle_subscription_id) WHERE paddle_subscription_id IS NOT NULL
        """)

        # Migration (M-1 from 2026-04 security review): add api_key_hash so
        # lookups can compare hashes instead of plaintext keys. All existing
        # rows are backfilled here; the application thereafter dual-writes
        # both columns on signup and reads exclusively from api_key_hash.
        await conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'workspaces' AND column_name = 'api_key_hash'
                ) THEN
                    ALTER TABLE workspaces ADD COLUMN api_key_hash TEXT;
                END IF;
            END $$;
        """)

        # Backfill any rows that are missing the hash. Computed in Python so
        # we don't require the pgcrypto extension.
        #
        # Post-Phase-2c the plaintext `api_key` column has been DROPPED, so
        # the SELECT below would fail at parse time on every cold boot.
        # Gate the whole block on column existence — once the column is gone
        # there is nothing left to backfill.
        plaintext_api_key_still_present = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='workspaces' AND column_name='api_key'
            )
        """)
        if plaintext_api_key_still_present:
            rows_missing_hash = await conn.fetch(
                "SELECT id, api_key FROM workspaces WHERE api_key_hash IS NULL AND api_key IS NOT NULL"
            )
            if rows_missing_hash:
                logger.info(
                    "Backfilling api_key_hash for %d existing workspace(s)", len(rows_missing_hash)
                )
                for row in rows_missing_hash:
                    digest = hashlib.sha256(row["api_key"].encode("utf-8")).hexdigest()
                    await conn.execute(
                        "UPDATE workspaces SET api_key_hash = $1 WHERE id = $2",
                        digest,
                        row["id"],
                    )

        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_workspaces_api_key_hash
            ON workspaces(api_key_hash) WHERE api_key_hash IS NOT NULL
        """)

        # Phase 2a PII encryption (2026-04): additive encrypt-and-hash columns
        # for workspaces.owner_email, paddle_customer_id, paddle_subscription_id.
        # Mirrors the Phase 1 pattern on the users table. Columns are added
        # unconditionally; backfill + dual-write only run when PII_MASTER_KEY
        # is set, so it is safe to deploy this before provisioning the key.
        await conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='workspaces' AND column_name='owner_email_encrypted') THEN
                    ALTER TABLE workspaces ADD COLUMN owner_email_encrypted TEXT;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='workspaces' AND column_name='owner_email_hash') THEN
                    ALTER TABLE workspaces ADD COLUMN owner_email_hash TEXT;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='workspaces' AND column_name='paddle_customer_id_encrypted') THEN
                    ALTER TABLE workspaces ADD COLUMN paddle_customer_id_encrypted TEXT;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='workspaces' AND column_name='paddle_customer_id_hash') THEN
                    ALTER TABLE workspaces ADD COLUMN paddle_customer_id_hash TEXT;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='workspaces' AND column_name='paddle_subscription_id_encrypted') THEN
                    ALTER TABLE workspaces ADD COLUMN paddle_subscription_id_encrypted TEXT;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='workspaces' AND column_name='paddle_subscription_id_hash') THEN
                    ALTER TABLE workspaces ADD COLUMN paddle_subscription_id_hash TEXT;
                END IF;
            END $$;
        """)
        # Non-unique partial indexes matching the existing plaintext indexes;
        # owner_email has no uniqueness constraint (multi-member workspaces
        # may share an owner_email upstream), and Paddle IDs are looked up
        # by equality but not enforced unique at this layer.
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_workspaces_owner_email_hash
            ON workspaces(owner_email_hash) WHERE owner_email_hash IS NOT NULL
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_workspaces_paddle_customer_hash
            ON workspaces(paddle_customer_id_hash) WHERE paddle_customer_id_hash IS NOT NULL
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_workspaces_paddle_subscription_hash
            ON workspaces(paddle_subscription_id_hash) WHERE paddle_subscription_id_hash IS NOT NULL
        """)

        # Backfill — same shape as the Phase 1 user backfill. Guarded on
        # PII_MASTER_KEY being set AND the plaintext columns still existing
        # (so a cold boot after Phase 2c drops them does not crash).
        plaintext_owner_email_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='workspaces' AND column_name='owner_email'
            )
        """)
        if os.getenv("PII_MASTER_KEY", "").strip() and plaintext_owner_email_exists:
            from .pii_crypto import encrypt_pii, lookup_hash, PIICryptoError
            try:
                rows_to_fill = await conn.fetch(
                    """
                    SELECT id, owner_email, paddle_customer_id, paddle_subscription_id
                    FROM workspaces
                    WHERE owner_email_hash IS NULL
                    """
                )
                if rows_to_fill:
                    logger.info(
                        "PII Phase 2a: backfilling %d workspace row(s)", len(rows_to_fill)
                    )
                for r in rows_to_fill:
                    await conn.execute(
                        """
                        UPDATE workspaces SET
                            owner_email_encrypted = $1, owner_email_hash = $2,
                            paddle_customer_id_encrypted = $3, paddle_customer_id_hash = $4,
                            paddle_subscription_id_encrypted = $5, paddle_subscription_id_hash = $6
                        WHERE id = $7
                        """,
                        encrypt_pii(r["owner_email"]) if r["owner_email"] else None,
                        lookup_hash(r["owner_email"]) if r["owner_email"] else None,
                        encrypt_pii(r["paddle_customer_id"]) if r["paddle_customer_id"] else None,
                        lookup_hash(r["paddle_customer_id"]) if r["paddle_customer_id"] else None,
                        encrypt_pii(r["paddle_subscription_id"]) if r["paddle_subscription_id"] else None,
                        lookup_hash(r["paddle_subscription_id"]) if r["paddle_subscription_id"] else None,
                        r["id"],
                    )
            except PIICryptoError as e:
                logger.error("PII Phase 2a backfill aborted: %s", e)

        # Phase 2c (2026-04): drop plaintext PII columns from workspaces now
        # that reads cut over under ENCRYPTED_WORKSPACE_READS. Also retires
        # the dead stripe_customer_id column (migrated to Paddle) and the
        # plaintext api_key column (hash is authoritative for lookups; last4
        # is persisted separately for the masked-display login response).
        plaintext_owner_email_exists_2c = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='workspaces' AND column_name='owner_email'
            )
        """)
        plaintext_api_key_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='workspaces' AND column_name='api_key'
            )
        """)

        # Add api_key_last4 up-front so the login response can render the
        # masked form without the plaintext column. Additive; safe regardless
        # of where in the rollout we are.
        await conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='workspaces' AND column_name='api_key_last4') THEN
                    ALTER TABLE workspaces ADD COLUMN api_key_last4 TEXT;
                END IF;
            END $$;
        """)

        # Backfill api_key_last4 from the still-present plaintext column.
        # Only runs while plaintext is available; after the drop below this
        # becomes a no-op because plaintext_api_key_exists is false.
        if plaintext_api_key_exists:
            backfilled = await conn.execute("""
                UPDATE workspaces
                SET api_key_last4 = RIGHT(api_key, 4)
                WHERE api_key_last4 IS NULL AND api_key IS NOT NULL
            """)
            if backfilled and not backfilled.endswith(" 0"):
                logger.info("PII Phase 2c: backfilled api_key_last4 (%s)", backfilled)

        # Safety gates — refuse to drop if ANY row would lose data we have
        # not yet migrated to the successor column. Each gate is evaluated
        # independently so we log precisely which condition blocked.
        if plaintext_owner_email_exists_2c or plaintext_api_key_exists:
            bad_owner_email = await conn.fetchval("""
                SELECT COUNT(*) FROM workspaces
                WHERE owner_email IS NOT NULL AND owner_email_hash IS NULL
            """) if plaintext_owner_email_exists_2c else 0
            bad_paddle_customer = await conn.fetchval("""
                SELECT COUNT(*) FROM workspaces
                WHERE paddle_customer_id IS NOT NULL AND paddle_customer_id_hash IS NULL
            """) if plaintext_owner_email_exists_2c else 0
            bad_paddle_sub = await conn.fetchval("""
                SELECT COUNT(*) FROM workspaces
                WHERE paddle_subscription_id IS NOT NULL AND paddle_subscription_id_hash IS NULL
            """) if plaintext_owner_email_exists_2c else 0
            bad_api_key_last4 = await conn.fetchval("""
                SELECT COUNT(*) FROM workspaces
                WHERE api_key IS NOT NULL AND api_key_last4 IS NULL
            """) if plaintext_api_key_exists else 0
            bad_total = (
                (bad_owner_email or 0)
                + (bad_paddle_customer or 0)
                + (bad_paddle_sub or 0)
                + (bad_api_key_last4 or 0)
            )
            if bad_total:
                logger.error(
                    "PII Phase 2c ABORTED: owner_email=%s paddle_customer=%s "
                    "paddle_sub=%s api_key_last4=%s rows missing successor data; "
                    "refusing to drop plaintext columns. Fix the data and restart.",
                    bad_owner_email, bad_paddle_customer, bad_paddle_sub, bad_api_key_last4,
                )
            else:
                logger.info(
                    "PII Phase 2c: dropping plaintext owner_email / paddle_customer_id / "
                    "paddle_subscription_id / stripe_customer_id / api_key columns"
                )
                await conn.execute("ALTER TABLE workspaces DROP COLUMN IF EXISTS owner_email")
                await conn.execute("ALTER TABLE workspaces DROP COLUMN IF EXISTS paddle_customer_id")
                await conn.execute("ALTER TABLE workspaces DROP COLUMN IF EXISTS paddle_subscription_id")
                await conn.execute("ALTER TABLE workspaces DROP COLUMN IF EXISTS stripe_customer_id")
                await conn.execute("ALTER TABLE workspaces DROP COLUMN IF EXISTS api_key")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS request_records (
                id BIGSERIAL PRIMARY KEY,
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                ts TIMESTAMPTZ NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INT NOT NULL DEFAULT 0,
                output_tokens INT NOT NULL DEFAULT 0,
                reasoning_tokens INT NOT NULL DEFAULT 0,
                cache_read_tokens INT NOT NULL DEFAULT 0,
                cache_write_tokens INT NOT NULL DEFAULT 0,
                cost_usd NUMERIC(12, 8) NOT NULL DEFAULT 0,
                duration_ms INT NOT NULL DEFAULT 0,
                status_code INT NOT NULL DEFAULT 200,
                tags JSONB NOT NULL DEFAULT '{}',
                system_prompt_hash TEXT,
                received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        # Create indexes
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_request_records_workspace_ts
            ON request_records(workspace_id, ts DESC)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_request_records_tags
            ON request_records USING GIN(tags)
        """)

        # Teams support tables
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email TEXT UNIQUE NOT NULL,
                name TEXT,
                password_hash TEXT,
                google_id TEXT UNIQUE,
                github_id TEXT UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_login TIMESTAMPTZ
            )
        """)

        # Migration: add password_hash column if missing
        await conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'users' AND column_name = 'password_hash'
                ) THEN
                    ALTER TABLE users ADD COLUMN password_hash TEXT;
                END IF;
            END $$;
        """)

        # Phase 1c dropped the plaintext email / google_id / github_id columns;
        # the legacy CREATE INDEX statements that referenced them lived here
        # and crashed cold boots post-1c. The lookup path now uses the
        # *_hash indexes created further down.

        # Phase 1 PII encryption (2026-04): additive columns for the
        # encrypt-and-hash pattern on email / google_id / github_id.
        # Backfill + dual-write is gated on PII_MASTER_KEY being present so
        # this migration is safe to deploy before the key is provisioned —
        # the columns exist but stay NULL until the app can encrypt.
        await conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='users' AND column_name='email_encrypted') THEN
                    ALTER TABLE users ADD COLUMN email_encrypted TEXT;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='users' AND column_name='email_hash') THEN
                    ALTER TABLE users ADD COLUMN email_hash TEXT;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='users' AND column_name='google_id_encrypted') THEN
                    ALTER TABLE users ADD COLUMN google_id_encrypted TEXT;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='users' AND column_name='google_id_hash') THEN
                    ALTER TABLE users ADD COLUMN google_id_hash TEXT;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='users' AND column_name='github_id_encrypted') THEN
                    ALTER TABLE users ADD COLUMN github_id_encrypted TEXT;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='users' AND column_name='github_id_hash') THEN
                    ALTER TABLE users ADD COLUMN github_id_hash TEXT;
                END IF;
            END $$;
        """)
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_hash
            ON users(email_hash) WHERE email_hash IS NOT NULL
        """)
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_id_hash
            ON users(google_id_hash) WHERE google_id_hash IS NOT NULL
        """)
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_github_id_hash
            ON users(github_id_hash) WHERE github_id_hash IS NOT NULL
        """)

        # Backfill runs only when PII_MASTER_KEY is set AND the plaintext
        # source columns still exist. After Phase 1c drops those columns
        # the SELECT below would fail; guard against it so a cold boot
        # post-1c doesn't crash init_db.
        plaintext_email_col_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='users' AND column_name='email'
            )
        """)
        if os.getenv("PII_MASTER_KEY", "").strip() and plaintext_email_col_exists:
            from .pii_crypto import encrypt_pii, lookup_hash, PIICryptoError
            try:
                rows_to_fill = await conn.fetch(
                    """
                    SELECT id, email, google_id, github_id
                    FROM users
                    WHERE email_hash IS NULL
                    """
                )
                if rows_to_fill:
                    logger.info(
                        "PII Phase 1: backfilling %d user row(s)", len(rows_to_fill)
                    )
                for r in rows_to_fill:
                    await conn.execute(
                        """
                        UPDATE users SET
                            email_encrypted = $1, email_hash = $2,
                            google_id_encrypted = $3, google_id_hash = $4,
                            github_id_encrypted = $5, github_id_hash = $6
                        WHERE id = $7
                        """,
                        encrypt_pii(r["email"]) if r["email"] else None,
                        lookup_hash(r["email"]) if r["email"] else None,
                        encrypt_pii(r["google_id"]) if r["google_id"] else None,
                        lookup_hash(r["google_id"]) if r["google_id"] else None,
                        encrypt_pii(r["github_id"]) if r["github_id"] else None,
                        lookup_hash(r["github_id"]) if r["github_id"] else None,
                        r["id"],
                    )
            except PIICryptoError as e:
                # Log and continue; the app should still boot. The operator
                # fixes the key, next restart resumes the backfill.
                logger.error("PII backfill aborted: %s", e)

        # Phase 1c (2026-04): drop plaintext PII columns once every row has
        # a hash. Guarded by a row-level safety check — if ANY row is
        # missing email_hash we refuse to drop, log loudly, and the
        # operator fixes the data before the next boot retries.
        if plaintext_email_col_exists:
            rows_without_hash = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE email_hash IS NULL"
            )
            total_rows = await conn.fetchval("SELECT COUNT(*) FROM users")
            if total_rows and rows_without_hash:
                logger.error(
                    "PII Phase 1c ABORTED: %d/%d user row(s) still lack email_hash; "
                    "refusing to drop plaintext columns. Fix the data and restart.",
                    rows_without_hash, total_rows,
                )
            else:
                logger.info(
                    "PII Phase 1c: dropping plaintext email / google_id / github_id columns"
                )
                # DROP COLUMN cascades the old unique constraints + indexes.
                await conn.execute("ALTER TABLE users DROP COLUMN IF EXISTS email")
                await conn.execute("ALTER TABLE users DROP COLUMN IF EXISTS google_id")
                await conn.execute("ALTER TABLE users DROP COLUMN IF EXISTS github_id")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS workspace_members (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL DEFAULT 'viewer',
                invited_by UUID REFERENCES users(id) ON DELETE SET NULL,
                joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                active BOOLEAN NOT NULL DEFAULT true
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_workspace_members_workspace_user
            ON workspace_members(workspace_id, user_id)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_workspace_members_user
            ON workspace_members(user_id)
        """)

        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_members_unique
            ON workspace_members(workspace_id, user_id) WHERE active = true
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS invitations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                email TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'viewer',
                token TEXT UNIQUE NOT NULL,
                invited_by UUID REFERENCES users(id) ON DELETE SET NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                accepted_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_invitations_workspace ON invitations(workspace_id)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_invitations_email ON invitations(email)
        """)

        # Phase 4 (2026-04): invitation tokens must not be stored as plaintext.
        # The email-delivered URL still carries the plaintext token; the DB
        # only ever sees its SHA-256 hash. A DB read-only breach now yields
        # no usable invite-acceptance credentials.
        #
        # Migration is three-step (additive, safety-gated, then destructive)
        # so a rollback between deploys is possible if something goes wrong
        # at any intermediate boot.
        await conn.execute("""
            ALTER TABLE invitations ADD COLUMN IF NOT EXISTS token_hash TEXT
        """)

        plaintext_token_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='invitations' AND column_name='token'
            )
        """)

        if plaintext_token_exists:
            backfilled = await conn.execute("""
                UPDATE invitations
                SET token_hash = encode(sha256(token::bytea), 'hex')
                WHERE token_hash IS NULL AND token IS NOT NULL
            """)
            if backfilled and not backfilled.endswith(" 0"):
                logger.info("Phase 4: backfilled invitations.token_hash (%s)", backfilled)

        bad_rows = await conn.fetchval("""
            SELECT COUNT(*) FROM invitations WHERE token_hash IS NULL
        """) or 0
        if bad_rows and plaintext_token_exists:
            # Never drop the plaintext column while rows still need it.
            logger.error(
                "Phase 4 ABORTED: %s invitations rows have NULL token_hash; "
                "refusing to drop invitations.token", bad_rows,
            )
        else:
            await conn.execute("DROP INDEX IF EXISTS idx_invitations_token")
            await conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_invitations_token_hash "
                "ON invitations(token_hash)"
            )
            if plaintext_token_exists:
                logger.info("Phase 4: dropping plaintext invitations.token column")
                await conn.execute("ALTER TABLE invitations DROP COLUMN IF EXISTS token")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS workspace_activity (
                id BIGSERIAL PRIMARY KEY,
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                user_id UUID REFERENCES users(id) ON DELETE SET NULL,
                action TEXT NOT NULL,
                detail JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                ip_address TEXT,
                user_agent TEXT,
                api_key_last4 TEXT
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_workspace_activity_workspace_ts
            ON workspace_activity(workspace_id, created_at DESC)
        """)

        # Enterprise SLA tracking table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS status_checks (
                id BIGSERIAL PRIMARY KEY,
                checked_at TIMESTAMPTZ NOT NULL,
                endpoint TEXT NOT NULL,
                response_ms INT NOT NULL,
                status_code INT NOT NULL,
                ok BOOLEAN NOT NULL
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_status_checks_checked_at
            ON status_checks(checked_at DESC)
        """)

        # Enterprise workspace settings (custom pricing, etc.)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS workspace_settings (
                workspace_id UUID PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
                custom_pricing JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        # Plan limits — single source of truth for per-plan caps (Phase 6)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS plan_limits (
                plan TEXT PRIMARY KEY,
                monthly_request_cap INT,
                seat_count INT,
                retention_days INT,
                api_key_count INT,
                paddle_price_id TEXT,
                paddle_product_id TEXT,
                gated_features JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        # Partial index on Paddle price ID — Phase 7 webhook handler looks up plan by price
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_plan_limits_paddle_price
            ON plan_limits(paddle_price_id) WHERE paddle_price_id IS NOT NULL
        """)

        # Phase 6: seed the three known plans — idempotent, preserves any manual production edits
        await conn.execute("""
            INSERT INTO plan_limits (
                plan, monthly_request_cap, seat_count, retention_days, api_key_count,
                paddle_price_id, paddle_product_id, gated_features
            ) VALUES (
                'free', 10000, 1, 7, 1,
                NULL, NULL,
                '{"custom_signatures": false, "team_seats": false, "otel_export": false}'::jsonb
            )
            ON CONFLICT (plan) DO NOTHING
        """)

        await conn.execute("""
            INSERT INTO plan_limits (
                plan, monthly_request_cap, seat_count, retention_days, api_key_count,
                paddle_price_id, paddle_product_id, gated_features
            ) VALUES (
                'cloud', 1000000, 1, 30, 3,
                'pri_01kpe2gkbz9w85btadnw8ckkyn', 'pro_01kpe2dxvfmnp3xeaj37krsksm',
                '{"custom_signatures": true, "team_seats": false, "otel_export": false}'::jsonb
            )
            ON CONFLICT (plan) DO NOTHING
        """)

        await conn.execute("""
            INSERT INTO plan_limits (
                plan, monthly_request_cap, seat_count, retention_days, api_key_count,
                paddle_price_id, paddle_product_id, gated_features
            ) VALUES (
                'teams', 10000000, 10, 90, 25,
                'pri_01kpe4f0aj537x609d6we7qpg7', 'pro_01kpe4etanc8971v5eesj5npn7',
                '{"custom_signatures": true, "team_seats": true, "otel_export": true}'::jsonb
            )
            ON CONFLICT (plan) DO NOTHING
        """)

        # Phase 6: per-workspace sparse override column (merged over plan defaults by resolve_limits)
        await conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'workspaces' AND column_name = 'limit_overrides'
                ) THEN
                    ALTER TABLE workspaces ADD COLUMN limit_overrides JSONB;
                END IF;
            END $$;
        """)

        # Phase 7 (D-04..D-08): Paddle lifecycle state columns — all nullable except cancel_at_period_end (boolean NOT NULL DEFAULT false)
        await conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'workspaces' AND column_name = 'trial_ends_at'
                ) THEN
                    ALTER TABLE workspaces ADD COLUMN trial_ends_at TIMESTAMPTZ;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'workspaces' AND column_name = 'current_period_ends_at'
                ) THEN
                    ALTER TABLE workspaces ADD COLUMN current_period_ends_at TIMESTAMPTZ;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'workspaces' AND column_name = 'cancel_at_period_end'
                ) THEN
                    ALTER TABLE workspaces ADD COLUMN cancel_at_period_end BOOLEAN NOT NULL DEFAULT false;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'workspaces' AND column_name = 'price_cents'
                ) THEN
                    ALTER TABLE workspaces ADD COLUMN price_cents INTEGER;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'workspaces' AND column_name = 'currency'
                ) THEN
                    ALTER TABLE workspaces ADD COLUMN currency TEXT;
                END IF;
                -- Phase 8 (W1): local mirror of Paddle's scheduled_change for a pending
                -- downgrade. Populated by POST /billing/change-plan after a 2xx Paddle
                -- PATCH (Teams->Cloud). Reconciled by subscription.updated webhook.
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'workspaces' AND column_name = 'scheduled_plan'
                ) THEN
                    ALTER TABLE workspaces ADD COLUMN scheduled_plan TEXT;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'workspaces' AND column_name = 'scheduled_change_at'
                ) THEN
                    ALTER TABLE workspaces ADD COLUMN scheduled_change_at TIMESTAMPTZ;
                END IF;
            END $$;
        """)

        # Phase 7 (D-09): webhook dedup + audit log. event_id is Paddle's event-envelope id;
        # INSERT ... ON CONFLICT (event_id) DO NOTHING gives us idempotency for free (D-10).
        # processed_at / error let production debug stuck events without replays (D-11).
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS paddle_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                payload JSONB NOT NULL,
                processed_at TIMESTAMPTZ,
                error TEXT
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_paddle_events_received_at
            ON paddle_events(received_at DESC)
        """)

        # Phase 8 (D-10): optional cancel-reason capture.
        # Never blocks cancel — best-effort insert from /billing/cancel.
        # workspace_id FK ON DELETE CASCADE so deleting a workspace does not leave orphans.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cancellation_surveys (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                reason_code TEXT,
                reason_text TEXT,
                plan_at_cancel TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_cancellation_surveys_workspace_ts
            ON cancellation_surveys(workspace_id, created_at DESC)
        """)

        # Phase 9 (D-01): per-workspace monthly usage counter anchored to either
        # the Paddle billing period (paid) or the UTC calendar month (free).
        # The UNIQUE (workspace_id, cycle_start) index is the conflict target for
        # Plan 05's ingest UPSERT — do not rename it.
        # notified_80_at / notified_100_at are atomic claim flags for D-06 dedup.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS workspace_usage_cycles (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                cycle_start TIMESTAMPTZ NOT NULL,
                cycle_end TIMESTAMPTZ NOT NULL,
                request_count BIGINT NOT NULL DEFAULT 0,
                notified_80_at TIMESTAMPTZ NULL,
                notified_100_at TIMESTAMPTZ NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_usage_cycles_ws_start
            ON workspace_usage_cycles(workspace_id, cycle_start)
        """)

        # Phase 9 (D-11): per-workspace API keys, hashed-only storage.
        # key_hash UNIQUE makes the (D-12) set-based backfill safe to repeat.
        # created_by_user_id uses ON DELETE SET NULL (not cascade) so the audit
        # trail survives user deletion — a revoked/compromised-key history row
        # MUST NOT disappear when the user who created it is removed.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                key_hash TEXT NOT NULL UNIQUE,
                last4 TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT 'Primary',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                revoked_at TIMESTAMPTZ NULL,
                created_by_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL
            )
        """)

        # Partial index: fast active-count lookups for the D-13/D-14 plan-cap check.
        # Predicate MUST be `WHERE revoked_at IS NULL` (Plan 04 reads rely on it).
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_api_keys_workspace_active
            ON api_keys(workspace_id) WHERE revoked_at IS NULL
        """)

        # Phase 9 (D-12): backfill existing workspaces.api_key_hash rows into api_keys.
        # Set-based INSERT ... SELECT ... WHERE NOT EXISTS so second run inserts zero rows
        # (UNIQUE(key_hash) + the NOT EXISTS guard make this idempotent by construction).
        # The dual-read in auth.get_workspace_by_api_key will look at api_keys first and
        # fall back to workspaces.api_key_hash until the latter is dropped in v1.1.1+.
        await conn.execute("""
            INSERT INTO api_keys (id, workspace_id, key_hash, last4, name, created_at)
            SELECT gen_random_uuid(), w.id, w.api_key_hash, COALESCE(w.api_key_last4, '****'), 'Primary', w.created_at
            FROM workspaces w
            WHERE w.api_key_hash IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM api_keys ak WHERE ak.key_hash = w.api_key_hash)
        """)

        # Phase 9 (D-19): seed supplement — add teams_view / customers_view flags
        # to plan_limits.gated_features per plan. JSONB `||` is an additive merge:
        # Phase 6 keys (custom_signatures, team_seats, otel_export) are preserved.
        # Idempotent by construction: re-applying the same `||` right-hand side is
        # a no-op once the keys already exist with the target values.
        #   - Free  → teams_view=false, customers_view=false
        #   - Cloud → teams_view=false, customers_view=false
        #   - Teams → teams_view=true,  customers_view=true
        await conn.execute("""
            UPDATE plan_limits
            SET gated_features = gated_features || '{"teams_view": false, "customers_view": false}'::jsonb
            WHERE plan IN ('free', 'cloud')
        """)
        await conn.execute("""
            UPDATE plan_limits
            SET gated_features = gated_features || '{"teams_view": true, "customers_view": true}'::jsonb
            WHERE plan = 'teams'
        """)

        # Phase 6: resolver function — merges workspace overrides over plan defaults
        # in a single Postgres round-trip. Called by burnlens_cloud/plans.py.
        #
        # Merge rules:
        #   - Scalar fields: COALESCE(override, plan_default). NULL = unlimited.
        #   - gated_features: plan.gated_features || override.gated_features
        #     (JSONB shallow merge, right side wins per key — D-04).
        #
        # Returns a single row (or no rows if workspace_id does not exist).
        await conn.execute("""
            CREATE OR REPLACE FUNCTION resolve_limits(ws_id UUID)
            RETURNS TABLE (
                plan TEXT,
                monthly_request_cap INT,
                seat_count INT,
                retention_days INT,
                api_key_count INT,
                gated_features JSONB
            )
            LANGUAGE SQL
            STABLE
            AS $$
                SELECT
                    pl.plan,
                    COALESCE((w.limit_overrides->>'monthly_request_cap')::int, pl.monthly_request_cap) AS monthly_request_cap,
                    COALESCE((w.limit_overrides->>'seat_count')::int,          pl.seat_count)          AS seat_count,
                    COALESCE((w.limit_overrides->>'retention_days')::int,      pl.retention_days)      AS retention_days,
                    COALESCE((w.limit_overrides->>'api_key_count')::int,       pl.api_key_count)       AS api_key_count,
                    (
                        pl.gated_features
                        || COALESCE(w.limit_overrides->'gated_features', '{}'::jsonb)
                    ) AS gated_features
                FROM workspaces w
                JOIN plan_limits pl ON pl.plan = w.plan
                WHERE w.id = ws_id
            $$;
        """)

        logger.info("Database tables created/verified")


async def close_db():
    """Close database connection pool."""
    global pool
    if pool:
        await pool.close()
        logger.info("Database pool closed")


async def get_db():
    """Get a connection from the pool."""
    if not pool:
        raise RuntimeError("Database pool not initialized")
    return await pool.acquire()


async def execute_query(query: str, *args):
    """Execute a query and return results."""
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def execute_insert(query: str, *args):
    """Execute an insert query and return the number of rows affected."""
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)


async def execute_bulk_insert(query: str, args_list: list):
    """Execute bulk insert using executemany."""
    async with pool.acquire() as conn:
        return await conn.executemany(query, args_list)
