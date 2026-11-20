PRAGMA foreign_keys = ON;

BEGIN;
CREATE TABLE IF NOT EXISTS student_groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE CHECK (length(trim(name)) > 0)
) STRICT;

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES student_groups(id),
    full_name TEXT NOT NULL CHECK (length(trim(full_name)) > 0),
    admission_date TEXT NOT NULL CHECK (date(admission_date, '+0 days') IS admission_date),
    email TEXT,
    phone TEXT,
    initial_average_hundredths INTEGER CHECK (initial_average_hundredths BETWEEN 100 AND 500)
) STRICT;

CREATE TABLE IF NOT EXISTS teachers (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL CHECK (length(trim(full_name)) > 0),
    email TEXT,
    phone TEXT
) STRICT;

CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    bonus_priority INTEGER UNIQUE CHECK (bonus_priority > 0)
) STRICT;

CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY,
    course_id INTEGER NOT NULL REFERENCES courses(id),
    teacher_id INTEGER NOT NULL REFERENCES teachers(id),
    group_id INTEGER NOT NULL REFERENCES student_groups(id),
    starts_at TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M', starts_at, '+0 days') IS starts_at),
    room TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS attendance (
    student_id INTEGER NOT NULL REFERENCES students(id),
    lesson_id INTEGER NOT NULL REFERENCES lessons(id),
    status TEXT NOT NULL CHECK (status IN ('present', 'absent', 'excused')),
    PRIMARY KEY (student_id, lesson_id)
) STRICT;

CREATE TABLE IF NOT EXISTS grades (
    student_id INTEGER NOT NULL REFERENCES students(id),
    lesson_id INTEGER NOT NULL REFERENCES lessons(id),
    score INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
    PRIMARY KEY (student_id, lesson_id)
) STRICT;

CREATE TABLE IF NOT EXISTS partners (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    agreement TEXT NOT NULL,
    adjustment_bps INTEGER NOT NULL CHECK (adjustment_bps >= -10000)
) STRICT;

CREATE TABLE IF NOT EXISTS payment_types (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
) STRICT;

CREATE TABLE IF NOT EXISTS charges (
    id INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(id),
    payment_type_id INTEGER NOT NULL REFERENCES payment_types(id),
    course_id INTEGER REFERENCES courses(id),
    partner_id INTEGER REFERENCES partners(id),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    due_date TEXT NOT NULL CHECK (date(due_date, '+0 days') IS due_date)
) STRICT;

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY,
    charge_id INTEGER NOT NULL REFERENCES charges(id),
    paid_at TEXT NOT NULL CHECK (date(paid_at, '+0 days') IS paid_at),
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0)
) STRICT;

CREATE TABLE IF NOT EXISTS material_types (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
) STRICT;

CREATE INDEX IF NOT EXISTS idx_students_group ON students(group_id);
CREATE INDEX IF NOT EXISTS idx_lessons_schedule ON lessons(starts_at);
CREATE INDEX IF NOT EXISTS idx_grades_lesson ON grades(lesson_id);
CREATE INDEX IF NOT EXISTS idx_attendance_lesson ON attendance(lesson_id);
CREATE INDEX IF NOT EXISTS idx_charges_student ON charges(student_id);
CREATE INDEX IF NOT EXISTS idx_payments_charge ON payments(charge_id);
CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(paid_at);

CREATE TRIGGER IF NOT EXISTS payment_limit_insert
BEFORE INSERT ON payments
WHEN NEW.amount_minor + (SELECT COALESCE(SUM(amount_minor), 0) FROM payments WHERE charge_id = NEW.charge_id)
     > (SELECT amount_minor FROM charges WHERE id = NEW.charge_id)
BEGIN
    SELECT RAISE(ABORT, 'payment exceeds outstanding balance');
END;

CREATE TRIGGER IF NOT EXISTS payment_limit_update
BEFORE UPDATE OF amount_minor, charge_id ON payments
WHEN NEW.amount_minor + (SELECT COALESCE(SUM(amount_minor), 0) FROM payments
                        WHERE charge_id = NEW.charge_id AND id <> OLD.id)
     > (SELECT amount_minor FROM charges WHERE id = NEW.charge_id)
BEGIN
    SELECT RAISE(ABORT, 'payment exceeds outstanding balance');
END;

CREATE TRIGGER IF NOT EXISTS charge_minimum
BEFORE UPDATE OF amount_minor ON charges
WHEN NEW.amount_minor < (SELECT COALESCE(SUM(amount_minor), 0) FROM payments WHERE charge_id = OLD.id)
BEGIN
    SELECT RAISE(ABORT, 'charge below payments total');
END;

CREATE VIEW IF NOT EXISTS student_performance AS
SELECT s.id AS student_id, COUNT(g.score) AS grade_count, SUM(g.score) AS grade_total,
       COALESCE(AVG(g.score), s.initial_average_hundredths / 100.0) AS average_score
FROM students AS s LEFT JOIN grades AS g ON g.student_id = s.id
GROUP BY s.id;

CREATE VIEW IF NOT EXISTS charge_balances AS
SELECT c.id AS charge_id, c.amount_minor - COALESCE(SUM(p.amount_minor), 0) AS balance_minor
FROM charges AS c LEFT JOIN payments AS p ON p.charge_id = c.id
GROUP BY c.id;
COMMIT;
