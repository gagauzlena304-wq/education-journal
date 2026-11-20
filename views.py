"""Shared HTML components for the student administration interface."""

from html import escape
from decimal import Decimal


def h(value):
    return escape(str(value if value is not None else ""), quote=True)


def money(minor):
    return amount(Decimal(minor) / 100)


def amount(number):
    return f"{number:,.2f}".replace(",", " ").replace(".", ",") + " лей"


def date_text(value):
    return value[8:10] + "." + value[5:7] + "." + value[:4]


def average_text(value):
    return f"{value:.2f}".replace(".", ",") if value is not None else "—"


def page(title, active, body, actions="", note="", error="", back=""):
    links = (
        ("students", "/", "Студенты"), ("teachers", "/teachers", "Преподаватели"),
        ("schedule", "/schedule", "Расписание"), ("payments", "/payments", "Оплаты"),
    )
    nav = "".join(
        f'<a href="{url}"' + (' aria-current="page"' if active == key else "") + f'>{label}</a>'
        for key, url, label in links
    )
    breadcrumb = f'<a class="back" href="{back[0]}">← {h(back[1])}</a>' if back else ""
    error_html = f'<p class="message error" role="alert">{h(error)}</p>' if error else ""
    note_html = f'<p class="message success" role="status">{h(note)}</p>' if note else ""
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{h(title)} · Учебный журнал</title>
<link rel="stylesheet" href="/style.css">
</head>
<body>
<a class="skip" href="#main">Перейти к содержимому</a>
<header class="header"><div class="shell header-inner">
<a class="brand" href="/"><span class="mark" aria-hidden="true"></span>Учебный журнал</a>
<nav aria-label="Разделы">{nav}</nav>
</div></header>
<main class="shell" id="main">
{breadcrumb}
<div class="page-heading"><h1>{h(title)}</h1><div class="actions">{actions}</div></div>
{error_html}{note_html}{body}
</main>
</body></html>"""


def link(url, label, primary=False):
    cls = "button primary" if primary else "button"
    return f'<a class="{cls}" href="{h(url)}">{h(label)}</a>'


def table(headers, rows, empty="Записей пока нет."):
    if not rows:
        return f'<p class="empty">{h(empty)}</p>'
    head = "".join(f'<th scope="col">{h(item)}</th>' for item in headers)
    body = "".join("<tr>" + "".join(f"<td>{item}</td>" for item in row) + "</tr>" for row in rows)
    return f'<div class="table-wrap" role="region" aria-label="{h(headers[0])} — таблица" tabindex="0"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def field(name, label, values, kind="text", attrs="", hint="", wide=False):
    cls = ' class="field wide"' if wide else ' class="field"'
    hint_html = f'<small id="{name}-hint">{h(hint)}</small>' if hint else ""
    described = f' aria-describedby="{name}-hint"' if hint else ""
    return (f'<label{cls}><span id="{name}-label">{h(label)}</span>'
            f'<input aria-labelledby="{name}-label" name="{name}" type="{kind}" value="{h(values.get(name))}" {attrs}{described}>'
            f'{hint_html}</label>')


def select(name, label, values, options, *, prompt="Выберите", required=False):
    current = str(values.get(name) or "")
    choices = [("", prompt)] + [(str(key), text) for key, text in options]
    tags = "".join(
        f'<option value="{h(key)}"{" selected" if key == current else ""}>{h(text)}</option>'
        for key, text in choices
    )
    required_attr = " required" if required else ""
    return f'<label class="field"><span id="{name}-label">{h(label)}</span><select aria-labelledby="{name}-label" name="{name}"{required_attr}>{tags}</select></label>'


def form(fields, label, cancel=None, method="post", action="", extra_class=""):
    target = f' action="{h(action)}"' if action else ""
    back = link(*cancel) if cancel else ""
    return (f'<form method="{method}"{target} class="{extra_class}">'
            f'<div class="fields">{fields}</div><div class="actions form-actions">'
            f'<button class="button primary" type="submit">{h(label)}</button>{back}</div></form>')


def named_section(title, content, description=""):
    desc = f'<p class="muted">{h(description)}</p>' if description else ""
    return f'<section class="section"><h2>{h(title)}</h2>{desc}{content}</section>'
