"""Sorgu ve SQLite sütunları için ortak metin katlama ve LIKE kaçışı."""
import re
import sqlite3
import unicodedata

from sqlalchemy import event, func
from sqlalchemy.engine import Engine

_EXTRA_FOLD = (("ł", "l"), ("ø", "o"), ("æ", "ae"), ("œ", "oe"), ("đ", "d"))
_MARKS = re.compile(r"[\u0300-\u036f]")


def search_fold(value):
    if value is None:
        return ""
    value = str(value)
    if value.isascii():
        return value.lower().strip()
    value = _MARKS.sub("", unicodedata.normalize("NFKD", value.casefold().replace("ı", "i")))
    for source, target in _EXTRA_FOLD:
        value = value.replace(source, target)
    # Noktalama ve boşluklar iki tarafta da korunur; LIKE kaçışı contains()'ta yapılır.
    return value.strip()


def folded_column(column):
    return func.jobapp_search_fold(column)


def contains(column, value):
    value = search_fold(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return folded_column(column).like("%" + value + "%", escape="\\")


def _register(connection, record):
    if isinstance(connection, sqlite3.Connection):
        connection.create_function("jobapp_search_fold", 1, search_fold, deterministic=True)


def install_sqlite_search():
    # Üretim ve geçici test engine'leri aynı fonksiyonu kullanır; şema değişmez.
    if not event.contains(Engine, "connect", _register):
        event.listen(Engine, "connect", _register)
