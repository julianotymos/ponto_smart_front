import psycopg2
from psycopg2.extras import RealDictCursor
import streamlit as st
from contextlib import contextmanager


def get_db_connection():
    db = st.secrets["database"]
    return psycopg2.connect(
        host=db["host"],
        port=int(db["port"]),
        user=db["user"],
        password=db["password"],
        dbname=db["dbname"],
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
