-- Task 4.3 (D-019): a place's province, so names outside Punjab ("Hyderabad") resolve to OUT_OF_COVERAGE (file 03 §4.3 step 5).
-- No default: nothing writes place before the 4.3 gazetteer load, so the table is empty everywhere.
ALTER TABLE place ADD COLUMN province text NOT NULL;
