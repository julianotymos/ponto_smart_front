import os
import psycopg2
from psycopg2.extras import RealDictCursor
import streamlit as st
from contextlib import contextmanager


def _cfg(section, key, env_key):
    try:
        return st.secrets[section][key]
    except Exception:
        return os.environ[env_key]


def get_db_connection():
    return psycopg2.connect(
        host=_cfg("database", "host", "DB_HOST"),
        port=int(_cfg("database", "port", "DB_PORT")),
        user=_cfg("database", "user", "DB_USER"),
        password=_cfg("database", "password", "DB_PASSWORD"),
        dbname=_cfg("database", "dbname", "DB_NAME"),
        cursor_factory=RealDictCursor,
    )


@contextmanager
def db_cursor():
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        yield conn, cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
