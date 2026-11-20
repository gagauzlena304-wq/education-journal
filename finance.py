"""Payment history, outstanding charges and tuition calculator."""

import sqlite3
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from academic import options, positive_id, valid_date
from database import calculate_tuition, decimal_value
from views import amount, date_text, field, form, h, link, money, named_section, page, select, table


def student_options(db):
    return [(row["id"], f'{row["full_name"]} · {row["group_name"]}')
            for row in db.execute("""
                SELECT s.id, s.full_name, sg.name AS group_name
                FROM students s JOIN student_groups sg ON sg.id = s.group_id
                ORDER BY s.full_name, s.id
            """)]


def money_minor(raw, label, minimum=0):
    return int(decimal_value(raw, label, minimum=minimum, maximum=1_000_000_000) * 100)


def query_id(query, field_name, label):
    raw = query.get(field_name, "")
    return positive_id(raw, label) if raw else None


def payment_history(db, query):
    filters = form(
        select("student_id", "Студент", query, student_options(db), prompt="Все студенты")
        + select("payment_type_id", "Тип оплаты", query, options(db, "payment_types"), prompt="Все типы")
        + field("from", "Дата с", query, "date") + field("to", "Дата по", query, "date")
        + field("min_amount", "Сумма от, лей", query, attrs='inputmode="decimal" maxlength="20"')
        + field("max_amount", "Сумма до, лей", query, attrs='inputmode="decimal" maxlength="20"'),
        "Применить", ("/payments", "Сбросить"), method="get", extra_class="filter payment-filters",
    )
    body, error = filters, ""
    try:
        student = query_id(query, "student_id", "Студент")
        payment_type = query_id(query, "payment_type_id", "Тип оплаты")
        start = valid_date(query["from"], "Дата с") if query.get("from") else None
        end = valid_date(query["to"], "Дата по") if query.get("to") else None
        low = money_minor(query["min_amount"], "Сумма от") if query.get("min_amount") else None
        high = money_minor(query["max_amount"], "Сумма до") if query.get("max_amount") else None
        if start and end and start > end:
            raise ValueError("Начало периода должно быть раньше окончания или совпадать с ним.")
        if low is not None and high is not None and low > high:
            raise ValueError("Минимальная сумма должна быть меньше максимальной или равна ей.")

        payments = db.execute("""
            SELECT s.id AS student_id, s.full_name, c.name, t.name AS type_name, p.paid_at, p.amount_minor
            FROM payments p JOIN charges c ON c.id = p.charge_id
            JOIN students s ON s.id = c.student_id JOIN payment_types t ON t.id = c.payment_type_id
            WHERE (? IS NULL OR c.student_id = ?) AND (? IS NULL OR c.payment_type_id = ?)
              AND (? IS NULL OR p.paid_at >= ?) AND (? IS NULL OR p.paid_at <= ?)
              AND (? IS NULL OR p.amount_minor >= ?) AND (? IS NULL OR p.amount_minor <= ?)
            ORDER BY p.paid_at DESC, p.id DESC
        """, (student, student, payment_type, payment_type, start, start, end, end, low, low, high, high))
        rows = [
            (f'<a class="record" href="/students/{r["student_id"]}">{h(r["full_name"])}</a>',
             h(r["name"]), h(r["type_name"]), date_text(r["paid_at"]), money(r["amount_minor"]))
            for r in payments
        ]
        body += table(("Студент", "Наименование платежа", "Тип", "Дата оплаты", "Сумма"), rows,
                      "Платежи по заданным условиям не найдены.")

        balances = db.execute("""
            SELECT c.id, c.name, s.full_name, t.name AS type_name, c.due_date, b.balance_minor,
                   pa.name AS partner_name
            FROM charges c JOIN charge_balances b ON b.charge_id = c.id
            JOIN students s ON s.id = c.student_id JOIN payment_types t ON t.id = c.payment_type_id
            LEFT JOIN partners pa ON pa.id = c.partner_id
            WHERE b.balance_minor > 0 AND (? IS NULL OR c.student_id = ?)
              AND (? IS NULL OR c.payment_type_id = ?)
            ORDER BY c.due_date, c.id
        """, (student, student, payment_type, payment_type))
        today = date.today().isoformat()
        balance_rows = [
            (h(r["full_name"]), h(r["name"]), h(r["type_name"]), h(r["partner_name"] or "—"),
             date_text(r["due_date"]),
             '<span class="outstanding">Просрочено</span>' if r["due_date"] < today else "К оплате",
             f'<strong>{money(r["balance_minor"])}</strong>',
             f'<a href="/payments/new?charge_id={r["id"]}">Внести оплату</a>')
            for r in balances
        ]
        body += named_section(
            "Задолженность",
            table(("Студент", "Начисление", "Тип", "Партнёр", "Срок оплаты", "Статус", "Остаток", "Действия"),
                  balance_rows, "Открытых начислений по выбранным условиям нет."),
            "Остатки по начислениям на сегодня. Фильтры по датам и суммам применяются к истории оплат.",
        )
    except ValueError as invalid:
        error = str(invalid)

    partners = [
        (h(r["name"]), h(r["agreement"]), f'{r["adjustment_bps"] / 100:+g}%')
        for r in db.execute("SELECT * FROM partners ORDER BY name")
    ]
    body += named_section("Партнёрские организации", table(("Организация", "Договорённость", "Корректировка"), partners))
    actions = link("/tuition", "Рассчитать стоимость") + link("/charges/new", "Добавить начисление")
    actions += link("/payments/new", "Внести оплату", True)
    notes = {"payment": "Оплата сохранена.", "charge": "Начисление сохранено."}
    return page("История оплат", "payments", body, actions, error=error, note=notes.get(query.get("saved"), ""))


def charge_form(db, submitted=None):
    values = submitted if submitted is not None else {}
    error = ""
    if submitted is not None:
        try:
            name = values.get("name", "").strip()
            if not name or len(name) > 150:
                raise ValueError("Введите наименование начисления длиной от 1 до 150 символов.")
            with db:
                db.execute("""
                    INSERT INTO charges (student_id, payment_type_id, course_id, partner_id, name, amount_minor, due_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (positive_id(values.get("student_id"), "Студент"),
                      positive_id(values.get("payment_type_id"), "Тип оплаты"),
                      query_id(values, "course_id", "Курс"), query_id(values, "partner_id", "Партнёр"), name,
                      money_minor(values.get("amount", ""), "Сумма", minimum=Decimal("0.01")),
                      valid_date(values.get("due_date", ""), "Срок оплаты")))
            return None, "/payments?saved=charge"
        except ValueError as invalid:
            error = str(invalid)
        except sqlite3.IntegrityError:
            error = "Выберите существующие записи из списков и проверьте сумму и дату."

    fields = select("student_id", "Студент *", values, student_options(db), required=True)
    fields += select("payment_type_id", "Тип оплаты *", values, options(db, "payment_types"), required=True)
    fields += field("name", "Наименование *", values, attrs='required maxlength="150"', wide=True)
    fields += field("amount", "Сумма, лей *", values, attrs='required inputmode="decimal" maxlength="20"')
    fields += field("due_date", "Срок оплаты *", values, "date", "required")
    fields += select("course_id", "Курс", values, options(db, "courses"), prompt="Без курса")
    fields += select("partner_id", "Партнёр", values, options(db, "partners"), prompt="Без партнёра")
    return page("Добавить начисление", "payments", form(fields, "Сохранить", ("/payments", "Отмена"), extra_class="editor"),
                error=error, back=("/payments", "История оплат")), None


def payment_form(db, query, submitted=None):
    values = submitted if submitted is not None else {
        "charge_id": query.get("charge_id"), "paid_at": date.today().isoformat()
    }
    error = ""
    if submitted is not None:
        try:
            charge_id = positive_id(values.get("charge_id"), "Начисление")
            paid_at = valid_date(values.get("paid_at", ""), "Дата оплаты")
            paid_amount = money_minor(values.get("amount", ""), "Сумма", minimum=Decimal("0.01"))
            with db:
                db.execute("BEGIN IMMEDIATE")
                charge = db.execute("""
                    SELECT c.student_id, b.balance_minor FROM charges c
                    JOIN charge_balances b ON b.charge_id = c.id WHERE c.id = ?
                """, (charge_id,)).fetchone()
                if charge is None or charge["balance_minor"] <= 0:
                    raise ValueError("Выберите открытое начисление.")
                if paid_amount > charge["balance_minor"]:
                    raise ValueError(f'Сумма превышает остаток по начислению ({money(charge["balance_minor"])}).')
                db.execute("INSERT INTO payments (charge_id, paid_at, amount_minor) VALUES (?, ?, ?)",
                           (charge_id, paid_at, paid_amount))
            return None, f'/payments?student_id={charge["student_id"]}&saved=payment'
        except ValueError as invalid:
            error = str(invalid)
        except sqlite3.IntegrityError:
            error = "Проверьте начисление, сумму и дату оплаты."

    charges = [
        (r["id"], f'{r["full_name"]} · {r["name"]} · {money(r["balance_minor"])}')
        for r in db.execute("""
            SELECT c.id, c.name, s.full_name, b.balance_minor FROM charges c
            JOIN charge_balances b ON b.charge_id = c.id JOIN students s ON s.id = c.student_id
            WHERE b.balance_minor > 0 ORDER BY s.full_name, c.due_date, c.id
        """)
    ]
    if charges:
        fields = select("charge_id", "Начисление *", values, charges, required=True)
        fields += field("paid_at", "Дата оплаты *", values, "date", "required")
        fields += field("amount", "Сумма, лей *", values, attrs='required inputmode="decimal" maxlength="20"')
        content = form(fields, "Сохранить", ("/payments", "Отмена"), extra_class="editor")
    else:
        content = '<p class="empty">Открытых начислений нет.</p>' + link("/charges/new", "Добавить начисление", True)
    return page("Внести оплату", "payments", content, error=error, back=("/payments", "История оплат")), None


def tuition(db, submitted=None):
    values = submitted if submitted is not None else {}
    error, result = "", ""
    if submitted is not None:
        try:
            course, material, subtotal, percent, total = calculate_tuition(
                db, positive_id(values.get("course_id"), "Курс"),
                positive_id(values.get("material_type_id"), "Тип материала"), values.get("hours", ""),
                values.get("unit_price", ""), query_id(values, "partner_id", "Партнёр"),
                values.get("adjustment", "").strip(),
            )
            result = (f'<section class="result" role="status"><h2>Стоимость обучения</h2>'
                      f'<p>{h(course)} · {h(material)}</p><dl class="facts">'
                      f'<div><dt>Базовая стоимость</dt><dd>{amount(subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))}</dd></div>'
                      f'<div><dt>Скидка или наценка</dt><dd>{h(f"{percent:+.2f}".replace(".", ","))}%</dd></div>'
                      f'<div><dt>Итого</dt><dd>{amount(total)}</dd></div></dl></section>')
        except ValueError as invalid:
            error = str(invalid)

    fields = select("course_id", "Курс *", values, options(db, "courses"), required=True)
    fields += select("material_type_id", "Тип материала *", values, options(db, "material_types"), required=True)
    fields += field("hours", "Количество часов *", values, attrs='required inputmode="decimal" maxlength="20"')
    fields += field("unit_price", "Цена за час, лей *", values, attrs='required inputmode="decimal" maxlength="20"')
    fields += select("partner_id", "Партнёр", values, options(db, "partners"), prompt="Без партнёра")
    fields += field("adjustment", "Скидка или наценка, %", values, attrs='inputmode="decimal" maxlength="20"',
                    hint="Например, -15 для скидки. Если поле пустое, используется ставка партнёра.")
    content = form(fields, "Рассчитать", ("/payments", "Назад"), extra_class="editor") + result
    return page("Расчёт стоимости обучения", "payments", content, error=error, back=("/payments", "История оплат")), None
