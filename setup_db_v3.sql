-- ============================================================
-- Nils Sjöberg v3: Subscriptions, Daily Counts, Discount Codes
-- Run in Supabase SQL Editor
-- ============================================================

-- Subscriptions table (if not exists)
CREATE TABLE IF NOT EXISTS subscriptions (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
    tier text NOT NULL DEFAULT 'free',
    status text NOT NULL DEFAULT 'none',
    trial_ends_at timestamptz,
    discount_code text,
    stripe_customer_id text,
    stripe_subscription_id text,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    UNIQUE(user_id)
);

-- Daily message counts
CREATE TABLE IF NOT EXISTS daily_message_counts (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
    message_date date NOT NULL DEFAULT CURRENT_DATE,
    count integer NOT NULL DEFAULT 0,
    UNIQUE(user_id, message_date)
);

-- Discount codes
CREATE TABLE IF NOT EXISTS discount_codes (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    code text NOT NULL UNIQUE,
    discount_percent integer NOT NULL DEFAULT 100,
    max_uses integer NOT NULL DEFAULT 1,
    times_used integer NOT NULL DEFAULT 0,
    description text DEFAULT '',
    active boolean DEFAULT true,
    created_at timestamptz DEFAULT now()
);

-- RLS policies
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_message_counts ENABLE ROW LEVEL SECURITY;
ALTER TABLE discount_codes ENABLE ROW LEVEL SECURITY;

-- Subscriptions: users can read own, service key can write
CREATE POLICY IF NOT EXISTS "Users read own subscription"
    ON subscriptions FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY IF NOT EXISTS "Service role manages subscriptions"
    ON subscriptions FOR ALL
    USING (auth.role() = 'service_role');

-- Daily message counts: users can read/write own
CREATE POLICY IF NOT EXISTS "Users manage own message counts"
    ON daily_message_counts FOR ALL
    USING (auth.uid() = user_id);

-- Discount codes: readable by all authenticated, writable by service role
CREATE POLICY IF NOT EXISTS "Authenticated read discount codes"
    ON discount_codes FOR SELECT
    USING (auth.role() = 'authenticated');

CREATE POLICY IF NOT EXISTS "Service role manages discount codes"
    ON discount_codes FOR ALL
    USING (auth.role() = 'service_role');

-- Auto-update timestamps
CREATE OR REPLACE FUNCTION update_subscription_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_subscriptions_updated_at ON subscriptions;
CREATE TRIGGER update_subscriptions_updated_at
    BEFORE UPDATE ON subscriptions
    FOR EACH ROW
    EXECUTE FUNCTION update_subscription_updated_at();

-- Add email column to profiles if missing (needed for admin user list)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'profiles' AND column_name = 'email'
    ) THEN
        ALTER TABLE profiles ADD COLUMN email text;
    END IF;
END $$;

-- Trigger: copy email to profiles on user creation
CREATE OR REPLACE FUNCTION copy_email_to_profile()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE profiles SET email = NEW.email WHERE id = NEW.id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS copy_email_on_signup ON auth.users;
CREATE TRIGGER copy_email_on_signup
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION copy_email_to_profile();

-- Backfill emails for existing users
UPDATE profiles p
SET email = u.email
FROM auth.users u
WHERE p.id = u.id AND (p.email IS NULL OR p.email = '');
