-- Culler schema v1. All data lives in one SQLite file on the user's Mac.

CREATE TABLE shoots (
    id           INTEGER PRIMARY KEY,
    folder_path  TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    photo_count  INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'new',   -- new | scanning | paused | ready | error
    finished_at  TEXT,                          -- set when the photographer marks the cull done
    archived     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE photos (
    id             INTEGER PRIMARY KEY,
    shoot_id       INTEGER NOT NULL REFERENCES shoots(id),
    path           TEXT NOT NULL,
    companion_path TEXT,                        -- JPEG shot alongside a RAW
    file_hash      TEXT,
    file_size      INTEGER,
    captured_at    TEXT,
    capture_ts     REAL,
    camera         TEXT,
    lens           TEXT,
    iso            INTEGER,
    shutter        REAL,
    aperture       REAL,
    focal          REAL,
    width          INTEGER,
    height         INTEGER,
    burst_id       INTEGER,
    burst_rank     INTEGER,                     -- 0 = best frame of its burst
    user_label     TEXT,                        -- KEEP | REJECT | NULL (current state; history is in decisions)
    user_rating    INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'new', -- new | done | error | missing
    error          TEXT,
    UNIQUE (shoot_id, path)
);
CREATE INDEX photos_shoot ON photos (shoot_id, capture_ts);
CREATE INDEX photos_hash ON photos (file_hash);

CREATE TABLE analysis (
    photo_id            INTEGER PRIMARY KEY REFERENCES photos(id),
    sharpness           REAL,
    subject_sharpness   REAL,
    face_sharpness      REAL,
    tile_max_sharpness  REAL,
    blur_score          REAL,
    blur_kind           TEXT,
    motion_anisotropy   REAL,
    motion_direction    REAL,
    exposure_mean       REAL,
    clip_high_pct       REAL,
    clip_low_pct        REAL,
    face_clip_high_pct  REAL,
    face_count          INTEGER,
    eyes_closed_count   INTEGER,
    main_eyes_closed    INTEGER,
    main_eye_open       REAL,
    faces_json          TEXT,
    face_backend        TEXT,
    analyzer_version    INTEGER NOT NULL
);

CREATE TABLE embeddings (
    photo_id    INTEGER NOT NULL REFERENCES photos(id),
    model_name  TEXT NOT NULL,
    vector      BLOB NOT NULL,                  -- float16
    PRIMARY KEY (photo_id, model_name)
);

CREATE TABLE bursts (
    id             INTEGER PRIMARY KEY,
    shoot_id       INTEGER NOT NULL REFERENCES shoots(id),
    photo_ids      TEXT NOT NULL,               -- JSON array, best first
    best_photo_id  INTEGER
);
CREATE INDEX bursts_shoot ON bursts (shoot_id);

-- The engine's current recommendation for each photo (replaced on every re-score).
CREATE TABLE scores (
    photo_id         INTEGER PRIMARY KEY REFERENCES photos(id),
    rule_score       REAL,
    personal_score   REAL,
    final_score      REAL,
    label            TEXT,
    confidence       REAL,
    reason_primary   TEXT,
    reason_secondary TEXT,
    reason_codes     TEXT,                      -- JSON array
    sharp_pct        REAL,
    model_version    TEXT,
    scored_at        TEXT
);

-- Every decision the photographer makes, next to what the engine said at that moment.
-- This is the training data. It is append-only: the triggers below refuse edits and deletes.
CREATE TABLE decisions (
    id            INTEGER PRIMARY KEY,
    photo_id      INTEGER NOT NULL REFERENCES photos(id),
    ai_label      TEXT,
    ai_confidence REAL,
    ai_reason     TEXT,
    user_label    TEXT,                         -- KEEP | REJECT | NULL (unflagged)
    user_rating   INTEGER,
    user_reason   TEXT,
    decided_at    TEXT NOT NULL,
    model_version TEXT
);
CREATE INDEX decisions_photo ON decisions (photo_id, id);

CREATE TRIGGER decisions_no_delete BEFORE DELETE ON decisions
BEGIN SELECT RAISE(ABORT, 'decisions are append-only'); END;
CREATE TRIGGER decisions_no_update BEFORE UPDATE ON decisions
BEGIN SELECT RAISE(ABORT, 'decisions are append-only'); END;

CREATE TABLE models (
    version       TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,                -- logistic | boosting
    embedder      TEXT NOT NULL,
    n_decisions   INTEGER NOT NULL,
    n_shoots      INTEGER NOT NULL,
    metrics_json  TEXT,
    path          TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 0
);
