"""Student, teacher and timetable screens."""

import re
import sqlite3
from datetime import date

from database import calculate_rating, decimal_value
from views import average_text, date_text, field, form, h, link, named_section, page, select, table


def options(db, table_name):
    return [(row["id"], row["name"]) for row in db.execute(f"SELECT id, name FROM {table_name} ORDER BY name")]


def valid_date(raw, label):
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as error:
        raise ValueError(f"Укажите корректную дату в поле «{label}».") from error


def positive_id(raw, label):
    if not re.fullmatch(r"[1-9][0-9]{0,17}", raw or ""):
        raise ValueError(f"Выберите значение в поле «{label}».")
    return int(raw)


def students(db, query):
    search = query.get("q", "").strip().casefold()
    group_id = query.get("group_id", "")
    records = [
        record for record in calculate_rating(db)
        if search in record["full_name"].casefold()
        and (not group_id or group_id == str(record["group_id"]))
    ]
    rows = []
    for student in records:
        student_id = student["id"]
        rows.append((
            f'<a class="record" href="/students/{student_id}">{h(student["full_name"])}</a>',
            h(student["group_name"]), average_text(student["average"]),
            f'<span class="rating" data-rating="{student["percent"]}">{student["percent"]}%</span>',
            h(", ".join(student["bonus_courses"]) or "—"),
            f'<a href="/students/{student_id}/edit" aria-label="Редактировать: {h(student["full_name"])}">Изменить</a>',
        ))
    filters = form(
        field("q", "Поиск по ФИО", query, "search", 'placeholder="Введите имя или фамилию" maxlength="150"')
        + select("group_id", "Группа", query, options(db, "student_groups"), prompt="Все группы"),
        "Найти", ("/", "Сбросить"), method="get", action="/", extra_class="filter",
    )
    registry = table(("ФИО", "Группа", "Средний балл", "Рейтинг", "Доступные бонусные курсы", "Действия"),
                     rows, "По заданным условиям студенты не найдены.")
    return page("Список студентов", "students",
                filters + f'<p class="table-label">Студентов в списке <strong>{len(rows)}</strong></p>' + registry,
                link("/students/new", "Добавить студента", True),
                note="Данные студента сохранены." if query.get("saved") == "1" else "")


def student_details(db, student_id):
    records = calculate_rating(db, student_id)
    if not records:
        raise LookupError
    student = records[0]
    attendance = db.execute("""
        SELECT l.starts_at, c.name, a.status FROM attendance a
        JOIN lessons l ON l.id = a.lesson_id JOIN courses c ON c.id = l.course_id
        WHERE a.student_id = ? ORDER BY l.starts_at DESC, l.id DESC
    """, (student_id,))
    grades = db.execute("""
        SELECT l.starts_at, c.name, g.score FROM grades g
        JOIN lessons l ON l.id = g.lesson_id JOIN courses c ON c.id = l.course_id
        WHERE g.student_id = ? ORDER BY l.starts_at DESC, l.id DESC
    """, (student_id,))
    attendance_labels = {"present": "Присутствовал(а)", "absent": "Отсутствовал(а)", "excused": "Уважительная причина"}
    facts = (
        ("Группа", student["group_name"]), ("Дата поступления", date_text(student["admission_date"])),
        ("Email", student["email"] or "—"), ("Телефон", student["phone"] or "—"),
        ("Средний балл", average_text(student["average"])), ("Рейтинг", f'{student["percent"]}%'),
        ("Бонусные курсы", ", ".join(student["bonus_courses"]) or "—"),
    )
    details = '<dl class="facts">' + "".join(
        f"<div><dt>{h(label)}</dt><dd>{h(value)}</dd></div>" for label, value in facts
    ) + "</dl>"
    body = details + '<div class="history">'
    body += named_section("Посещаемость", table(
        ("Дата", "Курс", "Статус"),
        [(date_text(row["starts_at"]), h(row["name"]), attendance_labels[row["status"]]) for row in attendance],
        "Посещения ещё не отмечены.",
    ))
    body += named_section("Оценки", table(
        ("Дата", "Курс", "Оценка"),
        [(date_text(row["starts_at"]), h(row["name"]), h(row["score"])) for row in grades],
        "Оценок в журнале пока нет.",
    )) + "</div>"
    return page(student["full_name"], "students", body,
                link(f"/payments?student_id={student_id}", "История оплат")
                + link(f"/students/{student_id}/edit", "Редактировать", True),
                back=("/", "Список студентов"))


def people_form(db, entity, person_id=None, submitted=None):
    is_student = entity == "students"
    base = "/" if is_student else "/teachers"
    back_text = "Список студентов" if is_student else "Список преподавателей"
    noun = "студента" if is_student else "преподавателя"
    title = ("Редактировать " if person_id else "Добавить ") + noun
    initial = {}
    computed_average = None
    has_grades = False
    if person_id:
        row = db.execute(f"SELECT * FROM {entity} WHERE id = ?", (person_id,)).fetchone()
        if row is None:
            raise LookupError
        initial = dict(row)
        if is_student:
            record = calculate_rating(db, person_id)[0]
            has_grades = bool(record["grade_count"])
            computed_average = record["average"]
            initial["average"] = format(computed_average, ".2f") if computed_average is not None else ""

    values = dict(initial if submitted is None else submitted)
    if has_grades:
        values["average"] = format(computed_average, ".2f")
    error = ""
    if submitted is not None:
        try:
            name = values.get("full_name", "").strip()
            if not name or len(name) > 150:
                raise ValueError("Введите ФИО длиной от 1 до 150 символов.")
            email = values.get("email", "").strip()
            if email and (len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+", email)):
                raise ValueError("Введите email в формате name@example.com.")
            phone = values.get("phone", "").strip()
            if phone and (not re.fullmatch(r"\+?[\d ()-]{7,24}", phone)
                          or not 7 <= sum(character.isdecimal() for character in phone) <= 15):
                raise ValueError("Введите телефон с 7–15 цифрами. Допустимы пробелы, скобки, дефис и начальный «+».")

            columns = ["full_name", "email", "phone"]
            params = [name, email or None, phone or None]
            with db:
                db.execute("BEGIN IMMEDIATE")
                if is_student:
                    group_id = positive_id(values.get("group_id"), "Группа")
                    if not db.execute("SELECT 1 FROM student_groups WHERE id = ?", (group_id,)).fetchone():
                        raise ValueError("Выберите существующую группу.")
                    admission_date = valid_date(values.get("admission_date", ""), "Дата поступления")
                    columns.extend(("group_id", "admission_date"))
                    params.extend((group_id, admission_date))
                    has_grades_now = person_id and db.execute(
                        "SELECT 1 FROM grades WHERE student_id = ? LIMIT 1", (person_id,)
                    ).fetchone()
                    if not has_grades_now:
                        raw = values.get("average", "").strip()
                        initial_average = int(decimal_value(raw, "Средний балл", minimum=1, maximum=5) * 100) if raw else None
                        columns.append("initial_average_hundredths")
                        params.append(initial_average)

                if person_id:
                    assignments = ", ".join(f"{column} = ?" for column in columns)
                    db.execute(f"UPDATE {entity} SET {assignments} WHERE id = ?", (*params, person_id))
                else:
                    placeholders = ", ".join("?" for _ in columns)
                    db.execute(f"INSERT INTO {entity} ({', '.join(columns)}) VALUES ({placeholders})", params)
            return None, base + "?saved=1"
        except (ValueError, sqlite3.IntegrityError) as invalid:
            error = str(invalid) if isinstance(invalid, ValueError) else "Проверьте заполнение формы."

    fields = field("full_name", "ФИО *", values, attrs='required maxlength="150" autocomplete="name"', wide=True)
    if is_student:
        fields += select("group_id", "Группа *", values, options(db, "student_groups"), required=True)
        fields += field("admission_date", "Дата поступления *", values, "date", "required",
                        "Выберите дату в календаре или введите её с клавиатуры.")
        fields += field("average", "Средний балл", values,
                        attrs='readonly' if has_grades else 'inputmode="decimal" maxlength="12" placeholder="4,25"',
                        hint="Рассчитан по оценкам из журнала." if has_grades else "От 1 до 5. Используется, пока в журнале нет оценок.")
    fields += field("email", "Email", values, "email", 'maxlength="254" autocomplete="email" placeholder="name@example.com"')
    fields += field("phone", "Телефон", values, "tel", 'maxlength="24" autocomplete="tel" placeholder="+373 …"')
    content = form(fields, "Сохранить", (base, "Отмена"), extra_class="editor")
    return page(title, entity, content, error=error, back=(base, back_text)), None


def teachers(db, query):
    records = db.execute("SELECT * FROM teachers ORDER BY full_name, id")
    rows = [
        (h(r["full_name"]), h(r["email"] or "—"), h(r["phone"] or "—"),
         f'<a href="/teachers/{r["id"]}/edit">Изменить</a>')
        for r in records
    ]
    return page("Список преподавателей", "teachers", table(("ФИО", "Email", "Телефон", "Действия"), rows),
                link("/teachers/new", "Добавить преподавателя", True),
                note="Данные преподавателя сохранены." if query.get("saved") == "1" else "")


def schedule(db, query):
    group = query.get("group_id", "")
    rows = db.execute("""
        SELECT l.starts_at, l.room, c.name, t.full_name, sg.name AS group_name FROM lessons l
        JOIN courses c ON c.id = l.course_id JOIN teachers t ON t.id = l.teacher_id
        JOIN student_groups sg ON sg.id = l.group_id
        WHERE (? = '' OR CAST(l.group_id AS TEXT) = ?)
        ORDER BY l.starts_at, l.id
    """, (group, group))
    filters = form(select("group_id", "Группа", query, options(db, "student_groups"), prompt="Все группы"),
                   "Применить", ("/schedule", "Сбросить"), method="get", extra_class="filter")
    timetable = table(("Дата", "Время", "Курс", "Группа", "Преподаватель", "Аудитория"), [
        (date_text(r["starts_at"]), h(r["starts_at"][11:]), h(r["name"]), h(r["group_name"]),
         h(r["full_name"]), h(r["room"])) for r in rows
    ], "Для выбранной группы занятий нет.")
    return page("Расписание занятий", "schedule", filters + timetable)
