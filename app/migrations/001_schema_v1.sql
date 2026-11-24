-- Task 2.3 · schema v1 (RFC §8, file 03 §3). Deviations and assumptions: DECISIONS.md D-010.
-- Not here yet: conversation tables (task 6.2), alert tables (alerts task), usage_event (first task that writes usage).

-- Reference ---------------------------------------------------------------

CREATE TABLE crop (
    crop_id             text PRIMARY KEY,                -- ONION, TOMATO, POTATO, WHEAT…
    name_en             text NOT NULL,
    name_ur             text NOT NULL,
    perishability_class text NOT NULL CHECK (perishability_class IN ('HIGH', 'MED', 'LOW')),
    default_unit        text NOT NULL,
    default_bag_kg      numeric CHECK (default_bag_kg > 0),  -- file 03 §5: NULL → always ask "bori kitne kilo ki hai?"
    covered             boolean NOT NULL DEFAULT false
);

CREATE TABLE crop_alias (
    alias_norm text NOT NULL,
    crop_id    text NOT NULL REFERENCES crop,
    kind       text NOT NULL CHECK (kind IN ('OFFICIAL', 'COMMON', 'MISSPELLING', 'URDU_SCRIPT', 'VOICE_STT', 'PUNJABI')),
    PRIMARY KEY (alias_norm, crop_id)                    -- one alias may name several crops → AMBIGUOUS
);

CREATE TABLE mandi (
    mandi_id   text PRIMARY KEY,
    name_en    text NOT NULL,
    name_ur    text NOT NULL,
    city       text NOT NULL,
    district   text NOT NULL,
    province   text NOT NULL,
    lat        double precision NOT NULL,
    lon        double precision NOT NULL,
    source_ids jsonb NOT NULL DEFAULT '{}',              -- {"AMIS": "...", "ZM": "..."}
    covered    boolean NOT NULL DEFAULT false
);

CREATE TABLE place (
    place_id            text PRIMARY KEY,
    name_en             text NOT NULL,
    name_ur             text NOT NULL,
    kind                text NOT NULL CHECK (kind IN ('DISTRICT', 'CITY')),
    district            text NOT NULL,
    lat                 double precision NOT NULL,       -- centroid
    lon                 double precision NOT NULL,
    candidate_mandi_ids text[] NOT NULL DEFAULT '{}'     -- shortcut: no FK on array elements; a gazetteer load test must check them
);

CREATE TABLE place_alias (
    alias_norm text NOT NULL,
    place_id   text NOT NULL REFERENCES place,
    PRIMARY KEY (alias_norm, place_id)                   -- designed-ambiguous aliases (task 4.3)
);

CREATE TABLE distance (
    origin_key  text NOT NULL,                           -- district or rounded pin
    mandi_id    text NOT NULL REFERENCES mandi,
    road_km     numeric NOT NULL CHECK (road_km >= 0),
    drive_min   numeric CHECK (drive_min >= 0),
    computed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (origin_key, mandi_id)
);

-- Prices and inputs ---------------------------------------------------------

CREATE TABLE price_obs (
    obs_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source         text NOT NULL CHECK (source IN ('SYN', 'SYN-NULL', 'AMIS', 'ZM')),
    mandi_id       text NOT NULL REFERENCES mandi,
    crop_id        text NOT NULL REFERENCES crop,
    grade          text,
    market_date    date NOT NULL,
    reported_at    timestamptz NOT NULL,                 -- when the price became knowable (leakage tests L1–L6)
    min_pkr100kg   numeric,
    max_pkr100kg   numeric,
    avg_pkr100kg   numeric,
    unit_raw       text NOT NULL,
    value_raw      numeric NOT NULL,
    arrivals_qty   numeric,
    arrivals_unit  text,
    outlier_flag   text NOT NULL DEFAULT 'OK' CHECK (outlier_flag IN ('OK', 'SUSPECT', 'REJECTED')),
    raw_ref        text NOT NULL,
    raw_sha256     text NOT NULL,
    CHECK (num_nonnulls(min_pkr100kg, max_pkr100kg, avg_pkr100kg) >= 1),
    -- min > max is NOT rejected here: the generator injects it and QC must flag it (file 03 §6, §9.1)
    UNIQUE NULLS NOT DISTINCT (source, mandi_id, crop_id, grade, market_date)
);
CREATE INDEX price_obs_series ON price_obs (crop_id, mandi_id, market_date);

CREATE TABLE weather_daily (
    district    text NOT NULL,
    date        date NOT NULL,
    rain_mm     numeric,
    tmax        numeric,
    tmin        numeric,
    is_forecast boolean NOT NULL,
    issued_at   timestamptz,                             -- NULL for observed rows
    UNIQUE NULLS NOT DISTINCT (district, date, is_forecast, issued_at)
);

CREATE TABLE macro_monthly (
    month            date PRIMARY KEY,                     -- first day of the month
    cpi_index        numeric,
    diesel_pkr_litre numeric
);

CREATE TABLE data_health (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_date           date NOT NULL,
    source             text NOT NULL,
    rows_loaded        integer NOT NULL,
    rows_rejected      integer NOT NULL,
    latest_market_date date,
    status             text NOT NULL,                    -- values defined by the batch pipeline (task 12.1)
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX data_health_latest ON data_health (source, run_date DESC);

-- Model outputs (append-only per run_id; replies reference the run_id they used) ---

CREATE TABLE model_registry (
    model_version text PRIMARY KEY,
    ps_id         text NOT NULL,
    file_sha256   text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE forecast (
    run_id        text NOT NULL,
    crop_id       text NOT NULL REFERENCES crop,
    mandi_id      text NOT NULL REFERENCES mandi,
    issue_date    date NOT NULL,
    target_date   date NOT NULL,
    p10           numeric NOT NULL,
    p50           numeric NOT NULL,
    p90           numeric NOT NULL,
    reasons       text[] NOT NULL DEFAULT '{}',
    model_version text NOT NULL REFERENCES model_registry,
    ps_id         text NOT NULL,
    PRIMARY KEY (run_id, crop_id, mandi_id, target_date)
);

CREATE TABLE outlook (
    run_id        text NOT NULL,
    crop_id       text NOT NULL REFERENCES crop,
    region        text NOT NULL,
    issue_month   date NOT NULL,
    target_month  date NOT NULL,
    p10           numeric NOT NULL,
    p50           numeric NOT NULL,
    p90           numeric NOT NULL,
    prob_below    numeric NOT NULL,
    prob_near     numeric NOT NULL,
    prob_above    numeric NOT NULL,
    model_version text NOT NULL REFERENCES model_registry,
    ps_id         text NOT NULL,
    PRIMARY KEY (run_id, crop_id, region, target_month)
);

CREATE TABLE series_coverage (
    crop_id     text NOT NULL REFERENCES crop,
    mandi_id    text NOT NULL REFERENCES mandi,
    window_days integer NOT NULL CHECK (window_days > 0),  -- file 03 calls it "window", a reserved word in Postgres
    pct_days    numeric NOT NULL,
    eligible_f1 boolean NOT NULL,                        -- the coverage gate (file 09 §D #3)
    live_mae    numeric,
    PRIMARY KEY (crop_id, mandi_id, window_days)
);

-- Infrastructure (column sets are ASSUMPTION: RFC §8 names the tables, tasks 3.1/4.1 use them) ---

CREATE TABLE inbound_event (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dedup_key   text NOT NULL UNIQUE,                    -- WAMID for messages, status key for statuses
    kind        text NOT NULL CHECK (kind IN ('message', 'status')),
    user_key    text,                                    -- BSUID ("US.…") or hashed number; never a plain phone number
    wa_ts       timestamptz,                             -- WhatsApp timestamp: turn order (RFC §3)
    payload     jsonb NOT NULL,                          -- task 3.1 strips/hashes phone numbers first (file 07 §3)
    received_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz
);
CREATE INDEX inbound_event_pending ON inbound_event (user_key, wa_ts) WHERE processed_at IS NULL;
CREATE INDEX inbound_event_received ON inbound_event (received_at);  -- 90-day retention delete

CREATE TABLE job (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind         text NOT NULL,                          -- turn, send, status, alert…
    user_key     text,                                   -- per-farmer serialisation (advisory lock in task 4.1)
    payload      jsonb NOT NULL DEFAULT '{}',
    priority     smallint NOT NULL DEFAULT 0,            -- lower runs first
    run_at       timestamptz NOT NULL DEFAULT now(),
    status       text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'dead')),
    attempts     integer NOT NULL DEFAULT 0,
    locked_until timestamptz,                            -- lease: running past this → re-claimed
    last_error   text,
    created_at   timestamptz NOT NULL DEFAULT now()
);
-- claim: WHERE status = 'queued' AND run_at <= now() ORDER BY priority, run_at LIMIT n FOR UPDATE SKIP LOCKED
CREATE INDEX job_claim ON job (priority, run_at) WHERE status = 'queued';
CREATE INDEX job_lease ON job (locked_until) WHERE status = 'running';

CREATE TABLE outbound_message (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id     bigint NOT NULL REFERENCES job,
    seq        smallint NOT NULL,                        -- n-th message the job sends; checked before any send after a crash
    user_key   text NOT NULL,
    wamid      text UNIQUE,                              -- set once Meta accepts it
    body       jsonb NOT NULL,
    run_id     text,                                     -- the forecast run the numbers came from
    status     text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'delivered', 'read', 'failed')),
    status_at  timestamptz,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, seq)
);
