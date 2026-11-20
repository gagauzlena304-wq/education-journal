"""SQLite schema, imports and rules for ratings and tuition."""

import csv
import sqlite3
from contextlib import closing
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "education.sqlite3"
TABLES = (
    "student_groups", "students", "teachers", "courses", "lessons",
    "attendance", "grades", "partners", "payment_types", "charges",
    "payments", "material_types",
)


def connect(path=DATABASE):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def import_csv(db, directory):
    with db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("PRAGMA user_version").fetchone()[0]:
            return False

        for table in TABLES:
            columns = [row["name"] for row in db.execute(f"PRAGMA table_info({table})")]
            filename = directory / f"{table}.csv"
            with filename.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.reader(stream, strict=True)
                if next(reader, None) != columns:
                    raise ValueError(f"{filename.name}: неверный заголовок.")
                placeholders = ", ".join("?" for _ in columns)
                for values in reader:
                    if len(values) != len(columns):
                        raise ValueError(f"{filename.name}, строка {reader.line_num}: неверное число полей.")
                    try:
                        db.execute(
                            f"INSERT INTO {table} VALUES ({placeholders})",
                            tuple(None if value == "" else value for value in values),
                        )
                    except sqlite3.IntegrityError as error:
                        raise ValueError(f"{filename.name}, строка {reader.line_num}: {error}") from error

        db.execute("PRAGMA user_version = 1")
        return True


def initialize(path=DATABASE, directory=ROOT / "data"):
    with closing(connect(path)) as db:
        db.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        if directory is not None:
            import_csv(db, directory)


def rating_percent(average):
    if average is None or average < Decimal("3.5"):
        return 0
    if average < Decimal("4.0"):
        return 25
    if average < Decimal("4.5"):
        return 50
    return 100


def calculate_rating(db, student_id=None):
    query = """
        SELECT s.*, sg.name AS group_name, sp.grade_count, sp.grade_total
        FROM students s
        JOIN student_groups sg ON sg.id = s.group_id
        JOIN student_performance sp ON sp.student_id = s.id
    """
    if student_id is None:
        students = db.execute(query + " ORDER BY s.full_name, s.id")
    else:
        students = db.execute(query + " WHERE s.id = ?", (student_id,))
    bonus_courses = [row["name"] for row in db.execute(
        "SELECT name FROM courses WHERE bonus_priority IS NOT NULL ORDER BY bonus_priority"
    )]
    result = []
    for student in students:
        average = None
        if student["grade_count"]:
            average = Decimal(student["grade_total"]) / student["grade_count"]
        elif student["initial_average_hundredths"] is not None:
            average = Decimal(student["initial_average_hundredths"]) / 100
        percent = rating_percent(average)
        limit = len(bonus_courses) * percent // 100
        result.append(dict(student, average=average, percent=percent, bonus_courses=bonus_courses[:limit]))
    return result


def decimal_value(raw, label, *, minimum, maximum, places=2):
    try:
        value = Decimal(raw.strip().replace(",", "."))
    except InvalidOperation as error:
        raise ValueError(f"Поле «{label}» должно содержать число.") from error
    scale = Decimal(10) ** places
    if (not value.is_finite() or not minimum <= value <= maximum
            or value * scale != (value * scale).to_integral_value()):
        raise ValueError(f"Поле «{label}» принимает значения от {minimum} до {maximum}, до {places} знаков после запятой.")
    return value


def calculate_tuition(db, course_id, material_type_id, hours, unit_price,
                      partner_id=None, adjustment=None):
    course = db.execute("SELECT name FROM courses WHERE id = ?", (course_id,)).fetchone()
    material = db.execute("SELECT name FROM material_types WHERE id = ?", (material_type_id,)).fetchone()
    if course is None or material is None:
        raise ValueError("Выберите курс и тип материала из списка.")

    hours = decimal_value(hours, "Часы", minimum=Decimal("0.01"), maximum=10000)
    unit_price = decimal_value(unit_price, "Цена за час", minimum=0, maximum=1_000_000)
    partner = None
    if partner_id:
        partner = db.execute("SELECT * FROM partners WHERE id = ?", (partner_id,)).fetchone()
        if partner is None:
            raise ValueError("Выберите партнёра из списка.")
    percent = Decimal(partner["adjustment_bps"]) / 100 if partner else Decimal(0)
    if adjustment:
        percent = decimal_value(adjustment, "Корректировка", minimum=-100, maximum=1000)

    subtotal = hours * unit_price
    total = (subtotal * (1 + percent / 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return course["name"], material["name"], subtotal, percent, total
