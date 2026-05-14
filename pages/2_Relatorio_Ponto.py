import streamlit as st
from utils.db import db_cursor
from datetime import date, timedelta
import pandas as pd

st.set_page_config(page_title="Relatorio de Ponto - Ponto Smart", layout="wide")
st.markdown("""
<style>
[data-testid="stStatusWidget"] { display: none !important; }
[data-testid="stToolbar"] { display: none !important; }
</style>
""", unsafe_allow_html=True)


def require_login():
    if "company_email" not in st.session_state:
        st.warning("Acesse a pagina inicial e informe o email da empresa.")
        st.stop()


require_login()

email = st.session_state["company_email"]

st.title("Relatorio de Ponto")
st.markdown("---")

# --- Filtros (compartilhados entre as abas) ---
col_de, col_ate, col_func = st.columns(3)

with col_de:
    data_de = st.date_input("De", value=date.today() - timedelta(days=30))

with col_ate:
    data_ate = st.date_input("Ate", value=date.today())

with col_func:
    with db_cursor() as (_, cur):
        cur.execute(
            """
            SELECT e.id, e.first_name || ' ' || e.last_name AS nome
            FROM employee e
            JOIN company c ON c.id = e.company
            WHERE c.email = %s AND e.status = 1
            ORDER BY e.first_name ASC
            """,
            (email,),
        )
        funcionarios = cur.fetchall()

    opcoes = {"Todos": 0}
    for f in funcionarios:
        opcoes[f["nome"]] = f["id"]

    func_selecionado = st.selectbox("Funcionario", list(opcoes.keys()))

if data_de > data_ate:
    st.error("A data inicial nao pode ser maior que a data final.")
    st.stop()

employee_id = opcoes[func_selecionado]
params: dict = {
    "email": email,
    "date_from": data_de.strftime("%Y-%m-%d"),
    "date_to": data_ate.strftime("%Y-%m-%d"),
}
employee_filter = ""
if employee_id != 0:
    employee_filter = "AND a.employee = %(employee_id)s"
    params["employee_id"] = employee_id

st.markdown("---")

tab_diario, tab_semanal = st.tabs(["Registros Diarios", "Horas por Semana"])


# =============================================================================
# ABA: REGISTROS DIARIOS
# =============================================================================
with tab_diario:
    query_diario = f"""
    WITH intervals AS (
        SELECT
            a.work_day,
            a.employee,
            e.first_name || ' ' || e.last_name AS funcionario,
            a.check_in_time,
            a.check_out_time,
            a.status,
            LEAD(a.check_in_time) OVER (PARTITION BY a.employee, a.work_day ORDER BY a.check_in_time) AS prox_entrada
        FROM attendance a
        JOIN employee e ON a.employee = e.id
        JOIN company c ON c.id = e.company
        WHERE c.email = %(email)s
          AND a.status IN (1, 3)
          AND a.work_day BETWEEN DATE(%(date_from)s) AND DATE(%(date_to)s)
          {employee_filter}
    )
    SELECT
        employee,
        funcionario,
        work_day AS data,
        TO_CHAR(work_day, 'Day DD/MM/YYYY') AS data_str,
        TO_CHAR(MIN(check_in_time), 'HH24:MI') AS entrada,
        TO_CHAR(MAX(check_out_time), 'HH24:MI') AS saida,
        COALESCE(TO_CHAR(SUM(check_out_time - check_in_time), 'HH24:MI'), '-') AS horas_trabalhadas,
        COALESCE(TO_CHAR(SUM(prox_entrada - check_out_time), 'HH24:MI'), '-') AS intervalo,
        COUNT(1) AS registros,
        MAX(status) AS status_max
    FROM intervals
    GROUP BY employee, funcionario, work_day
    ORDER BY work_day DESC, funcionario ASC
    """

    with db_cursor() as (_, cur):
        cur.execute(query_diario, params)
        rows = cur.fetchall()

    st.markdown(f"**{len(rows)} registro(s)** entre {data_de.strftime('%d/%m/%Y')} e {data_ate.strftime('%d/%m/%Y')}")

    if rows:
        df = pd.DataFrame([dict(r) for r in rows])
        df["status_label"] = df["status_max"].apply(lambda s: "Aberto" if s == 3 else "Fechado")

        st.dataframe(
            df[["funcionario", "data_str", "entrada", "saida", "horas_trabalhadas", "intervalo", "registros", "status_label"]].rename(columns={
                "funcionario": "Funcionario",
                "data_str": "Data",
                "entrada": "Entrada",
                "saida": "Saida",
                "horas_trabalhadas": "Horas Trabalhadas",
                "intervalo": "Intervalo",
                "registros": "Qtd Registros",
                "status_label": "Status",
            }),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("---")
        st.subheader("Totais do Periodo")

        with db_cursor() as (_, cur):
            cur.execute(
                f"""
                SELECT
                    e.first_name || ' ' || e.last_name AS funcionario,
                    COUNT(DISTINCT a.work_day) AS dias_trabalhados,
                    TO_CHAR(SUM(a.check_out_time - a.check_in_time), 'HH24:MI') AS total_horas
                FROM attendance a
                JOIN employee e ON a.employee = e.id
                JOIN company c ON c.id = e.company
                WHERE c.email = %(email)s
                  AND a.status = 1
                  AND a.work_day BETWEEN DATE(%(date_from)s) AND DATE(%(date_to)s)
                  {employee_filter}
                GROUP BY e.first_name, e.last_name
                ORDER BY funcionario ASC
                """,
                params,
            )
            totais = cur.fetchall()

        if totais:
            st.dataframe(
                [dict(r) for r in totais],
                column_config={
                    "funcionario": "Funcionario",
                    "dias_trabalhados": "Dias Trabalhados",
                    "total_horas": "Total de Horas",
                },
                use_container_width=True,
                hide_index=True,
            )
    else:
        st.info("Nenhum registro encontrado para os filtros selecionados.")


# =============================================================================
# ABA: HORAS POR SEMANA
# =============================================================================
with tab_semanal:
    query_semanal = f"""
    WITH agrupado AS (
        SELECT
            e.first_name || ' ' || e.last_name          AS funcionario,
            DATE_TRUNC('week', a.work_day)::date         AS semana_inicio,
            COUNT(DISTINCT a.work_day)                   AS dias_trabalhados,
            COALESCE(TO_CHAR(SUM(CASE WHEN EXTRACT(ISODOW FROM a.work_day) = 1
                THEN a.check_out_time - a.check_in_time END), 'HH24:MI'), '-') AS seg,
            COALESCE(TO_CHAR(SUM(CASE WHEN EXTRACT(ISODOW FROM a.work_day) = 2
                THEN a.check_out_time - a.check_in_time END), 'HH24:MI'), '-') AS ter,
            COALESCE(TO_CHAR(SUM(CASE WHEN EXTRACT(ISODOW FROM a.work_day) = 3
                THEN a.check_out_time - a.check_in_time END), 'HH24:MI'), '-') AS qua,
            COALESCE(TO_CHAR(SUM(CASE WHEN EXTRACT(ISODOW FROM a.work_day) = 4
                THEN a.check_out_time - a.check_in_time END), 'HH24:MI'), '-') AS qui,
            COALESCE(TO_CHAR(SUM(CASE WHEN EXTRACT(ISODOW FROM a.work_day) = 5
                THEN a.check_out_time - a.check_in_time END), 'HH24:MI'), '-') AS sex,
            COALESCE(TO_CHAR(SUM(CASE WHEN EXTRACT(ISODOW FROM a.work_day) = 6
                THEN a.check_out_time - a.check_in_time END), 'HH24:MI'), '-') AS sab,
            COALESCE(TO_CHAR(SUM(CASE WHEN EXTRACT(ISODOW FROM a.work_day) = 7
                THEN a.check_out_time - a.check_in_time END), 'HH24:MI'), '-') AS dom,
            COALESCE(TO_CHAR(SUM(a.check_out_time - a.check_in_time), 'HH24:MI'), '-') AS total_semana
        FROM attendance a
        JOIN employee e ON a.employee = e.id
        JOIN company c ON c.id = e.company
        WHERE c.email = %(email)s
          AND a.status = 1
          AND a.work_day BETWEEN DATE(%(date_from)s) AND DATE(%(date_to)s)
          {employee_filter}
        GROUP BY funcionario, DATE_TRUNC('week', a.work_day)
    )
    SELECT
        funcionario,
        semana_inicio,
        (semana_inicio + INTERVAL '6 days')::date AS semana_fim,
        seg, ter, qua, qui, sex, sab, dom,
        total_semana,
        dias_trabalhados
    FROM agrupado
    ORDER BY semana_inicio DESC, funcionario ASC
    """

    with db_cursor() as (_, cur):
        cur.execute(query_semanal, params)
        rows_sem = cur.fetchall()

    if rows_sem:
        df_sem = pd.DataFrame([dict(r) for r in rows_sem])
        df_sem["semana"] = df_sem.apply(
            lambda r: f"{r['semana_inicio'].strftime('%d/%m')} - {r['semana_fim'].strftime('%d/%m/%Y')}",
            axis=1,
        )

        st.markdown(f"**{len(df_sem)} semana(s)** encontrada(s) no periodo")

        st.dataframe(
            df_sem[["funcionario", "semana", "seg", "ter", "qua", "qui", "sex", "sab", "dom", "total_semana", "dias_trabalhados"]].rename(columns={
                "funcionario":     "Funcionario",
                "semana":          "Semana (Seg - Dom)",
                "seg":             "Seg",
                "ter":             "Ter",
                "qua":             "Qua",
                "qui":             "Qui",
                "sex":             "Sex",
                "sab":             "Sab",
                "dom":             "Dom",
                "total_semana":    "Total Semana",
                "dias_trabalhados": "Dias",
            }),
            use_container_width=True,
            hide_index=True,
        )

        # --- Resumo por funcionario ---
        st.markdown("---")
        st.subheader("Resumo por Funcionario")

        with db_cursor() as (_, cur):
            cur.execute(
                f"""
                SELECT
                    e.first_name || ' ' || e.last_name AS funcionario,
                    COUNT(DISTINCT DATE_TRUNC('week', a.work_day)) AS semanas,
                    COUNT(DISTINCT a.work_day)          AS dias_trabalhados,
                    TO_CHAR(SUM(a.check_out_time - a.check_in_time), 'HH24:MI') AS total_horas,
                    TO_CHAR(
                        SUM(a.check_out_time - a.check_in_time) / NULLIF(COUNT(DISTINCT DATE_TRUNC('week', a.work_day)), 0),
                        'HH24:MI'
                    ) AS media_semanal
                FROM attendance a
                JOIN employee e ON a.employee = e.id
                JOIN company c ON c.id = e.company
                WHERE c.email = %(email)s
                  AND a.status = 1
                  AND a.work_day BETWEEN DATE(%(date_from)s) AND DATE(%(date_to)s)
                  {employee_filter}
                GROUP BY e.first_name, e.last_name
                ORDER BY funcionario ASC
                """,
                params,
            )
            resumo = cur.fetchall()

        if resumo:
            st.dataframe(
                [dict(r) for r in resumo],
                column_config={
                    "funcionario":      "Funcionario",
                    "semanas":          "Semanas",
                    "dias_trabalhados": "Dias Trabalhados",
                    "total_horas":      "Total de Horas",
                    "media_semanal":    "Media Semanal",
                },
                use_container_width=True,
                hide_index=True,
            )
    else:
        st.info("Nenhum registro fechado encontrado para os filtros selecionados.")
