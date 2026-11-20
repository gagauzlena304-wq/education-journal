"""Run with python -m unittest -v."""

import shutil
import sqlite3
import unittest
from contextlib import closing
from decimal import Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.parse import urlencode
from urllib.request import urlopen

from app import Handler
from database import ROOT, calculate_rating, calculate_tuition, connect, import_csv, initialize, rating_percent


class AppTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "test.sqlite3"
        initialize(self.path)
        self.db = connect(self.path)
        self.addCleanup(self.db.close)

    def test_import_and_foreign_keys(self):
        self.assertEqual(self.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertFalse(import_csv(self.db, ROOT / "data"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM students").fetchone()[0], 6)
        with self.assertRaises(sqlite3.IntegrityError), self.db:
            self.db.execute("INSERT INTO grades VALUES (999, 1, 5)")

    def test_import_rolls_back_invalid_input(self):
        copied = self.path.parent / "data"
        shutil.copytree(ROOT / "data", copied)
        with (copied / "grades.csv").open("a", encoding="utf-8") as stream:
            stream.write("999,1,5\n")
        empty = self.path.parent / "empty.sqlite3"
        initialize(empty, None)
        with closing(connect(empty)) as db:
            with self.assertRaisesRegex(ValueError, "grades.csv"):
                import_csv(db, copied)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM students").fetchone()[0], 0)
            self.assertTrue(import_csv(db, ROOT / "data"))

    def test_ratings_from_database(self):
        expected = {1: ("4.5", 100), 2: ("3.5", 25), 3: ("4", 50), 4: ("3", 0), 5: ("4", 50), 6: (None, 0)}
        for student in calculate_rating(self.db):
            average, percent = expected[student["id"]]
            with self.subTest(student=student["id"]):
                self.assertEqual(student["average"], Decimal(average) if average else None)
                self.assertEqual(student["percent"], percent)
                self.assertEqual(len(student["bonus_courses"]), 4 * percent // 100)

    def test_rating_boundaries(self):
        cases = {"3.4999": 0, "3.5": 25, "3.9999": 25, "4.0": 50, "4.4999": 50, "4.5": 100, "5.0": 100}
        for average, percent in cases.items():
            with self.subTest(average=average):
                self.assertEqual(rating_percent(Decimal(average)), percent)

    def test_tuition_discount_surcharge_and_override(self):
        self.assertEqual(calculate_tuition(self.db, 1, 2, "10", "100", 1)[-1], Decimal("850.00"))
        self.assertEqual(calculate_tuition(self.db, 1, 2, "10", "100", 2)[-1], Decimal("1050.00"))
        self.assertEqual(calculate_tuition(self.db, 1, 2, "10", "100", 1, "0")[-1], Decimal("1000.00"))
        with self.assertRaises(ValueError):
            calculate_tuition(self.db, 1, 2, "-3", "100")

    def test_payment_limits(self):
        with self.assertRaises(sqlite3.IntegrityError), self.db:
            self.db.execute("INSERT INTO payments (charge_id, paid_at, amount_minor) VALUES (2, '2026-11-18', 350001)")
        with self.db:
            self.db.execute("INSERT INTO payments (charge_id, paid_at, amount_minor) VALUES (2, '2026-11-18', 350000)")
        self.assertEqual(self.db.execute("SELECT balance_minor FROM charge_balances WHERE charge_id=2").fetchone()[0], 0)
        with self.assertRaises(sqlite3.IntegrityError), self.db:
            self.db.execute("UPDATE charges SET amount_minor = 1 WHERE id=2")

    def test_http_workflow(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.database_path = self.path
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"

        def request(path, fields=None):
            data = urlencode(fields).encode() if fields is not None else None
            with urlopen(base + path, data=data, timeout=5) as response:
                return response.read().decode(), response.url

        for path, heading in (("/", "Список студентов"), ("/students/1", "Посещаемость"),
                              ("/teachers", "Список преподавателей"), ("/schedule", "Расписание занятий"),
                              ("/payments", "Задолженность")):
            self.assertIn(heading, request(path)[0])

        student = {"full_name": "Проверка Имя Отчество", "group_id": "1", "admission_date": "2026-09-01",
                   "average": "4,50", "email": "test@example.com", "phone": "+373 00000000"}
        self.assertIn("Введите ФИО", request("/students/new", dict(student, full_name=""))[0])
        self.assertIn("Выберите значение", request("/students/new", dict(student, group_id=""))[0])
        self.assertIn("email в формате", request("/students/new", dict(student, email="invalid"))[0])
        self.assertIn("корректную дату", request("/students/new", dict(student, admission_date="2026-02-30"))[0])
        content, location = request("/students/new", student)
        self.assertIn(student["full_name"], content)
        self.assertTrue(location.endswith("/?saved=1"))
        person_id = self.db.execute("SELECT MAX(id) FROM students").fetchone()[0]
        edit = f"/students/{person_id}/edit"
        self.assertIn('value="test@example.com"', request(edit)[0])
        self.assertIn("Новая фамилия", request(edit, dict(student, full_name="Новая фамилия"))[0])

        teacher = {"full_name": "Новый Преподаватель", "email": "teacher@example.com"}
        self.assertIn(teacher["full_name"], request("/teachers/new", teacher)[0])
        teacher_id = self.db.execute("SELECT MAX(id) FROM teachers").fetchone()[0]
        self.assertIn("Данные обновлены", request(f"/teachers/{teacher_id}/edit",
                                                  dict(teacher, full_name="Данные обновлены"))[0])

        self.assertIn("3 000,00 лей", request("/payments?student_id=2&payment_type_id=1&from=2026-11-10"
                                             "&to=2026-11-10&min_amount=3000&max_amount=3000")[0])
        self.assertIn("Платежи по заданным условиям не найдены",
                      request("/payments?student_id=2&min_amount=3001")[0])
        charge = {"name": "Тестовое начисление", "student_id": str(person_id), "payment_type_id": "1",
                  "amount": "0,01", "due_date": "2026-12-01", "course_id": "1", "partner_id": "1"}
        self.assertIn("Тестовое начисление", request("/charges/new", charge)[0])
        charge_id = self.db.execute("SELECT MAX(id) FROM charges").fetchone()[0]
        payment = {"charge_id": str(charge_id), "paid_at": "2026-11-18", "amount": "0,02"}
        self.assertIn("Сумма превышает остаток", request("/payments/new", payment)[0])
        content, location = request("/payments/new", dict(payment, amount="0,01"))
        self.assertIn("Оплата сохранена", content)
        self.assertIn(f"student_id={person_id}", location)
        self.assertEqual(self.db.execute("SELECT balance_minor FROM charge_balances WHERE charge_id=?",
                                         (charge_id,)).fetchone()[0], 0)

        result, _ = request("/tuition", {"course_id": "1", "material_type_id": "2", "hours": "10",
                                         "unit_price": "100", "partner_id": "1"})
        self.assertIn("850,00 лей", result)


if __name__ == "__main__":
    unittest.main()
