import streamlit as st
from utils.db import db_cursor
from datetime import date

st.set_page_config(page_title="Dashboard - Ponto Smart", layout="wide")
st.markdown("""
<style>
[data-testid="stStatusWidget"] { display: none !important; }
.block-container { padding-top: 1rem !important; }
h1, h2, h3 { margin-bottom: 0.5rem !important; }
hr { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
header[data-testid="stHeader"] { height: 2.5rem !important; min-height: 2.5rem !important; }
</style>
""", unsafe_allow_html=True)


def require_login():
    if "company_email" not in st.session_state:
        st.warning("Acesse a pagina inicial e informe o email da empresa.")
        st.stop()


require_login()

email = st.session_state["company_email"]
company_name = st.session_state.get("company_name", email)

st.title(f"Dashboard — {company_name}")
st.markdown(f"Data de hoje: **{date.today().strftime('%d/%m/%Y')}**")
st.markdown("---")

# --- KPIs ---
with db_cursor() as (_, cur):
    cur.execute(
        """
        SELECT COUNT(*) AS total
        FROM employee e
        JOIN company c ON c.id = e.company
        WHERE c.email = %s AND e.status = 1
        """,
        (email,),
    )
    total_ativos = cur.fetchone()["total"]

    cur.execute(
        """
        SELECT COUNT(DISTINCT a.employee) AS open_today
        FROM attendance a
        JOIN employee e ON e.id = a.employee
        JOIN company c ON c.id = e.company
        WHERE c.email = %s AND a.status = 3 AND a.work_day = CURRENT_DATE
        """,
        (email,),
    )
    open_today = cur.fetchone()["open_today"]

    cur.execute(
        """
        SELECT COUNT(DISTINCT a.employee) AS registros_hoje
        FROM attendance a
        JOIN employee e ON e.id = a.employee
        JOIN company c ON c.id = e.company
        WHERE c.email = %s AND a.work_day = CURRENT_DATE AND a.status IN (1, 3)
        """,
        (email,),
    )
    registros_hoje = cur.fetchone()["registros_hoje"]

    cur.execute(
        """
        SELECT COALESCE(
            TO_CHAR(SUM(a.check_out_time - a.check_in_time), 'HH24"h"MI"m"'), '-'
        ) AS total_horas
        FROM attendance a
        JOIN employee e ON e.id = a.employee
        JOIN company c ON c.id = e.company
        WHERE c.email = %s AND a.work_day = CURRENT_DATE AND a.status = 1
        """,
        (email,),
    )
    total_horas = cur.fetchone()["total_horas"]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Funcionarios Ativos", total_ativos)
col2.metric("Com Ponto Aberto Agora", open_today)
col3.metric("Registros Hoje", registros_hoje)
col4.metric("Total Horas Fechadas Hoje", total_horas or "-")

st.markdown("---")

# --- Proximos Aniversarios ---
st.subheader("Proximos Aniversarios")

with db_cursor() as (_, cur):
    cur.execute(
        """
        SELECT
            e.first_name || ' ' || e.last_name AS nome,
            TO_CHAR(e.birth_date, 'DD/MM') AS dia_mes,
            CASE
                WHEN TO_DATE(TO_CHAR(CURRENT_DATE, 'YYYY') || '-' || TO_CHAR(e.birth_date, 'MM-DD'), 'YYYY-MM-DD') >= CURRENT_DATE
                THEN TO_DATE(TO_CHAR(CURRENT_DATE, 'YYYY') || '-' || TO_CHAR(e.birth_date, 'MM-DD'), 'YYYY-MM-DD')
                ELSE TO_DATE(TO_CHAR(CURRENT_DATE + INTERVAL '1 year', 'YYYY') || '-' || TO_CHAR(e.birth_date, 'MM-DD'), 'YYYY-MM-DD')
            END AS prox_aniversario,
            DATE_PART('year', AGE(e.birth_date)) + 1 AS prox_idade
        FROM employee e
        JOIN company c ON c.id = e.company
        WHERE c.email = %s AND e.status = 1 AND e.birth_date IS NOT NULL
        ORDER BY prox_aniversario ASC
        LIMIT 5
        """,
        (email,),
    )
    aniversarios = cur.fetchall()

if aniversarios:
    cols = st.columns(len(aniversarios))
    for i, row in enumerate(aniversarios):
        delta_days = (row["prox_aniversario"] - date.today()).days
        delta_str = "Hoje!" if delta_days == 0 else f"em {delta_days} dia(s)"
        cols[i].metric(
            label=row["nome"],
            value=row["dia_mes"],
            delta=delta_str,
        )
else:
    st.info("Nenhum aniversario proximo encontrado.")

st.markdown("---")

# --- Funcionarios com Ponto Aberto ---
st.subheader("Funcionarios com Ponto Aberto Agora")

with db_cursor() as (_, cur):
    cur.execute(
        """
        SELECT
            e.first_name || ' ' || e.last_name AS funcionario,
            TO_CHAR(a.check_in_time, 'HH24:MI') AS entrada,
            TO_CHAR(NOW() - a.check_in_time, 'HH24"h"MI"m"') AS tempo_trabalhado,
            COALESCE(a.observation, '') AS observacao
        FROM attendance a
        JOIN employee e ON e.id = a.employee
        JOIN company c ON c.id = e.company
        WHERE c.email = %s AND a.status = 3 AND a.work_day = CURRENT_DATE
        ORDER BY e.first_name ASC
        """,
        (email,),
    )
    em_servico = cur.fetchall()

if em_servico:
    st.dataframe(
        [dict(r) for r in em_servico],
        column_config={
            "funcionario": "Funcionario",
            "entrada": "Entrada",
            "tempo_trabalhado": "Tempo Trabalhado",
            "observacao": "Observacao",
        },
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("Nenhum funcionario com ponto aberto no momento.")

st.markdown("---")

# --- Resumo Semanal ---
st.subheader("Resumo da Semana (Seg a Dom)")

with db_cursor() as (_, cur):
    cur.execute(
        """
        SELECT
            a.work_day AS dia,
            COUNT(DISTINCT a.employee) AS funcionarios,
            COALESCE(TO_CHAR(SUM(a.check_out_time - a.check_in_time), 'HH24:MI'), '-') AS horas_totais
        FROM attendance a
        JOIN employee e ON e.id = a.employee
        JOIN company c ON c.id = e.company
        WHERE c.email = %s
          AND a.status = 1
          AND a.work_day >= DATE_TRUNC('week', CURRENT_DATE)
          AND a.work_day <= CURRENT_DATE
        GROUP BY a.work_day
        ORDER BY a.work_day ASC
        """,
        (email,),
    )
    semana = cur.fetchall()

if semana:
    import pandas as pd

    df = pd.DataFrame([dict(r) for r in semana])
    df["dia"] = pd.to_datetime(df["dia"]).dt.strftime("%d/%m (%a)")
    st.dataframe(
        df,
        column_config={
            "dia": "Dia",
            "funcionarios": "Funcionarios com Registro",
            "horas_totais": "Horas Totais Fechadas",
        },
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("Sem registros fechados esta semana.")
