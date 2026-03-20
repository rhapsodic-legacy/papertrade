-- Add reasoning column to transactions table
-- Run this in Supabase SQL Editor before deploying
ALTER TABLE public.transactions ADD COLUMN IF NOT EXISTS reasoning text;
