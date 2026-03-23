-- Add modules_used column to track which RAG toolkit modules informed each trade
ALTER TABLE public.transactions ADD COLUMN IF NOT EXISTS modules_used text;
