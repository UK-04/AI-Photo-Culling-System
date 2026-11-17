-- A shoot can be limited to hand-picked files inside its folder ("Select photos…").
-- NULL means the whole folder. Otherwise a JSON array of absolute paths.
ALTER TABLE shoots ADD COLUMN only_files TEXT;
