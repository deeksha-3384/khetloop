create or replace function new_id(prefix text) returns text language sql as
$$ select prefix || substr(md5(random()::text || clock_timestamp()::text), 1, 8) $$;

create table farmers (
 id text primary key default new_id('fmr_'),
 name text not null,
 language text not null check (language in ('kn','hi','en')),
 telegram_chat_id bigint unique,
 created_at timestamptz not null default now());

create table farms (
 id text primary key default new_id('farm_'),
 farmer_id text not null references farmers(id) on delete cascade,
 crop text not null check (crop in ('tomato','potato','chilli','other')),
 sowing_date date,
 area_label text,
 lat numeric(6,2), lng numeric(6,2),            -- already rounded
 data_source text not null default 'live'
 check (data_source in ('live','cached','simulated','unverified')),
 created_at timestamptz not null default now());

create table reports (
 id text primary key default new_id('rep_'),
 farm_id text not null references farms(id) on delete cascade,
 image_path text not null,
 voice_transcript text,
 voice_language text check (voice_language in ('kn','hi','en')),
 decision text not null check (decision in
 ('preliminary_assessment','abstain_request_better_image','escalate_to_expert')),
 suspected_issue text not null default 'unknown',
 confidence_band text not null check (confidence_band in ('high','medium','low')),
 image_quality text not null check (image_quality in ('good','poor')),
 visible_symptoms jsonb not null default '[]',
 escalation_reason text,
 why jsonb not null default '[]',
 weather jsonb, risk jsonb,
 reply_language text, reply_text text, reply_audio_path text,
 status text not null check (status in
 ('submitted','ai_assessed','expert_review_pending','expert_reviewed','follow_up')),
 data_source text not null default 'live'
 check (data_source in ('live','cached','simulated','unverified')),
 created_at timestamptz not null default now());

create table report_events (                       -- status timeline AND audit trail
 id bigint generated always as identity primary key,
 report_id text not null references reports(id) on delete cascade,
 status text not null check (status in
 ('submitted','ai_assessed','expert_review_pending','expert_reviewed','follow_up')),
 actor text not null check (actor in ('farmer','ai','rules','expert','system')),
 note text,
 created_at timestamptz not null default now());

create table expert_reviews (
 id text primary key default new_id('rev_'),
 report_id text not null unique references reports(id) on delete cascade,
 expert_name text not null, guidance text not null, confirmed_issue text,
 created_at timestamptz not null default now());

create table clusters (
 id text primary key default new_id('clu_'),
 crop text not null, suspected_issue text not null, area_label text,
 centroid_lat numeric(6,2), centroid_lng numeric(6,2),
 severity text not null check (severity in ('watch','elevated')),
 report_count int not null, window_hours int not null,
 data_source text not null default 'live'
 check (data_source in ('live','cached','simulated','unverified')),
 created_at timestamptz not null default now());

create table cluster_reports (
 cluster_id text references clusters(id) on delete cascade,
 report_id text references reports(id) on delete cascade,
 primary key (cluster_id, report_id));

create table alerts (
 id text primary key default new_id('alt_'),
 cluster_id text not null references clusters(id) on delete cascade,
 farm_id text not null references farms(id) on delete cascade,
 message text not null, channel text not null default 'telegram',
 delivered boolean not null default false, sent_at timestamptz,
 data_source text not null default 'live'
 check (data_source in ('live','cached','simulated','unverified')),
 unique (cluster_id, farm_id));                   -- one alert per farm per cluster

create table reminders (
 id text primary key default new_id('rem_'),
 report_id text not null references reports(id) on delete cascade,
 due_at timestamptz not null, message text not null,
 sent boolean not null default false, sent_at timestamptz);

create index on reports (farm_id, created_at desc);
create index on reports (status);
create index on reports (suspected_issue, created_at desc);
create index on report_events (report_id, created_at);
create index on reminders (due_at) where sent = false;