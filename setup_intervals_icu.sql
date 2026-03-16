-- Add Intervals.icu fields to profiles table
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS intervals_api_key TEXT;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS intervals_athlete_id TEXT;
