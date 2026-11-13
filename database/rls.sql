-- KhetLoop row-level security (Master Contract v2.0, section 7.2)
-- RLS on every table and NO policies: the anon key reads and writes nothing.
-- The backend uses SUPABASE_SERVICE_KEY, which bypasses RLS.
-- The report-images bucket is private (created in the Supabase dashboard).

alter table farmers         enable row level security;
alter table farms           enable row level security;
alter table reports         enable row level security;
alter table report_events   enable row level security;
alter table expert_reviews  enable row level security;
alter table clusters        enable row level security;
alter table cluster_reports enable row level security;
alter table alerts          enable row level security;
alter table reminders       enable row level security;