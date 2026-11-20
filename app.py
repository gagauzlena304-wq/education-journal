"""Start a local student administration server."""

import argparse
import re
import webbrowser
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Timer
from urllib.parse import parse_qs, urlsplit

import academic
import finance
from database import DATABASE, ROOT, connect, initialize
from views import link, page

RECORD_PATH = re.compile(r"/(students|teachers)/([1-9][0-9]{0,17})(/edit)?")
FORMS = {
    "/charges/new": lambda db, query, submitted: finance.charge_form(db, submitted),
    "/payments/new": finance.payment_form,
    "/tuition": lambda db, query, submitted: finance.tuition(db, submitted),
}
DIRECTORIES = {
    "/": academic.students,
    "/teachers": academic.teachers,
    "/schedule": academic.schedule,
    "/payments": finance.payment_history,
}


def route(db, path, query, submitted):
    if path in DIRECTORIES and submitted is None:
        return DIRECTORIES[path](db, query), None
    if path in FORMS:
        return FORMS[path](db, query, submitted)
    if path in ("/students/new", "/teachers/new"):
        return academic.people_form(db, path.split("/")[1], submitted=submitted)
    match = RECORD_PATH.fullmatch(path)
    if match:
        entity, record_id, edit = match.groups()
        if edit:
            return academic.people_form(db, entity, int(record_id), submitted)
        if entity == "students" and submitted is None:
            return academic.student_details(db, int(record_id)), None
    raise LookupError


class Handler(BaseHTTPRequestHandler):
    def respond(self, content, status=200, content_type="text/html; charset=utf-8"):
        encoded = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def dispatch(self):
        port = self.server.server_port
        hosts = (f"127.0.0.1:{port}", f"localhost:{port}")
        if self.headers.get("Host") not in hosts:
            self.send_error(403)
            return
        submitted = None
        try:
            url = urlsplit(self.path)
            query = {key: values[-1] for key, values in parse_qs(
                url.query, keep_blank_values=True, max_num_fields=30
            ).items()}
            if self.command == "POST":
                origin = self.headers.get("Origin")
                if origin and origin not in {f"http://{host}" for host in hosts}:
                    self.send_error(403)
                    return
                if self.headers.get_content_type() != "application/x-www-form-urlencoded":
                    self.send_error(415)
                    return
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16000:
                    self.send_error(400)
                    return
                submitted = {key: values[-1] for key, values in parse_qs(
                    self.rfile.read(size).decode("utf-8"), keep_blank_values=True, max_num_fields=30
                ).items()}
            if url.path == "/style.css" and submitted is None:
                self.respond((ROOT / "style.css").read_text(encoding="utf-8"),
                             content_type="text/css; charset=utf-8")
                return

            with closing(connect(self.server.database_path)) as db:
                content, redirect = route(db, url.path, query, submitted)
            if redirect:
                self.send_response(303)
                self.send_header("Location", redirect)
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self.respond(content)
        except LookupError:
            self.respond(page("Страница не найдена", "", link("/", "Список студентов", True)), 404)
        except ValueError:
            self.respond(page("Некорректный запрос", "", link("/", "Список студентов", True)), 400)


def main():
    parser = argparse.ArgumentParser(description="Локальный учебный журнал")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, default=DATABASE)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--init-only", action="store_true", help="Создать и заполнить БД без запуска сервера")
    parser.add_argument("--open", action="store_true", help="Открыть журнал в браузере")
    args = parser.parse_args()
    initialize(args.db, args.data_dir)
    if args.init_only:
        print(args.db.resolve())
        return

    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.database_path = args.db
        url = f"http://127.0.0.1:{server.server_port}/"
        print(url, flush=True)
        if args.open:
            Timer(0.2, webbrowser.open, args=(url,)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
