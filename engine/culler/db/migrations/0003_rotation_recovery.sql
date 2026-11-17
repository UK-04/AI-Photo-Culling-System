-- Rotation applied on top of the camera's own orientation flag, in degrees clockwise.
-- rotation_source: 'auto' (Culler worked it out from faces) or 'user' (set by hand; never overridden).
ALTER TABLE photos ADD COLUMN rotation INTEGER NOT NULL DEFAULT 0;
ALTER TABLE photos ADD COLUMN rotation_source TEXT;

-- How fixable a photo's problems are in editing (0 = not at all, 1 = nothing to fix).
ALTER TABLE scores ADD COLUMN recover_score REAL;
ALTER TABLE scores ADD COLUMN recover_label TEXT;
ALTER TABLE scores ADD COLUMN recover_note TEXT;
