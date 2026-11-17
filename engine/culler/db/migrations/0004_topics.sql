-- What kind of shoot this is (wedding, travel, ...). Decides which topic categories are used.
ALTER TABLE shoots ADD COLUMN shoot_type TEXT NOT NULL DEFAULT 'general';

-- Topic category and relevance for each photo. Rebuilt whenever a shoot is scanned or its type changes.
CREATE TABLE topics (
    photo_id            INTEGER PRIMARY KEY REFERENCES photos(id),
    category            TEXT,
    category_confidence REAL,
    relevance           REAL,               -- 0-1: how much the photo belongs with the rest of the shoot
    off_topic           INTEGER NOT NULL DEFAULT 0,
    method              TEXT                -- 'vision' (CLIP, understands content) or 'faces' (people count only)
);
