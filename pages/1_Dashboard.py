import streamlit as st
from utils.db import db_cursor
from datetime import date, timedelta
import pandas as pd

st.set_page_config(page_title="Dashboard - Ponto Smart", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
[data-testid="stStatusWidget"] { display: none !important; }
.block-container { padding-top: 1rem !important; }
h1 { margin-bottom: 0 !important; }
h2, h3 { margin-top: 0 !important; margin-bottom: 0.5rem !important; }
hr { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
</style>
""", unsafe_allow_html=True)

from utils.auth import require_login

require_login()

email       = st.session_state["company_email"]
company_id  = st.session_state["company_id"]
company_name = st.session_state.get("company_name", email)
hoje        = date.today()

col_title, col_refresh = st.columns([6, 1])
with col_title:
    st.title(f"Dashboard — {company_name}")
    st.markdown(f"Data de hoje: **{hoje.strftime('%d/%m/%Y')}**")
with col_refresh:
    st.markdown("&nbsp;")
    if st.button("🔄 Atualizar", use_container_width=True):
        st.rerun()

st.markdown("---")

# =============================================================================
# DADOS BASE
# =============================================================================
with db_cursor() as (_, cur):

    # Funcionários ativos
    cur.execute("""
        SELECT COUNT(*) AS total FROM employee e
        JOIN company c ON c.id = e.company
        WHERE c.email = %s AND e.status = 1
    """, (email,))
    total_ativos = cur.fetchone()["total"]

    # Com ponto aberto agora (check_in real — não zerado)
    cur.execute("""
        SELECT COUNT(DISTINCT a.employee) AS n
        FROM attendance a
        JOIN employee e ON e.id = a.employee
        JOIN company c ON c.id = e.company
        WHERE c.email = %s AND a.status = 3 AND a.work_day = %s
          AND a.check_in_time IS NOT NULL
          AND a.check_in_time::time != '00:00:00'
    """, (email, hoje))
    open_today = cur.fetchone()["n"]

    # Escalados hoje sem ponto válido (falta do dia)
    cur.execute("""
        SELECT COUNT(*) AS n
        FROM schedule s
        JOIN employee e ON e.id = s.employee
        JOIN company c ON c.id = e.company
        WHERE c.email = %s
          AND s.work_date = %s
          AND s.is_day_off = FALSE
          AND s.start_time IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM attendance a
              WHERE a.employee = s.employee
                AND a.work_day = %s
                AND a.status IN (1, 3)
                AND (
                    (a.check_out_time IS NOT NULL AND a.check_out_time > a.check_in_time)
                    OR (a.status = 3 AND a.check_in_time IS NOT NULL AND a.check_in_time::time != '00:00:00')
                )
          )
    """, (email, hoje, hoje))
    sem_ponto_hoje = cur.fetchone()["n"]

    # Aprovações pendentes
    cur.execute("""
        SELECT COUNT(*) AS n FROM attendance_pending_request
        WHERE company = %s AND status = 'pending'
    """, (company_id,))
    pendentes = cur.fetchone()["n"]

    # Feriado hoje
    cur.execute("""
        SELECT name, holiday_type FROM holidays
        WHERE holiday_date = %s LIMIT 1
    """, (hoje,))
    feriado_hoje = cur.fetchone()

    # Próximo feriado
    cur.execute("""
        SELECT name, holiday_date, holiday_type FROM holidays
        WHERE holiday_date > %s
        ORDER BY holiday_date ASC LIMIT 1
    """, (hoje,))
    prox_feriado = cur.fetchone()

    # Total horas fechadas hoje (válidas)
    cur.execute("""
        SELECT COALESCE(TO_CHAR(SUM(a.check_out_time - a.check_in_time), 'HH24"h"MI"m"'), '-') AS total
        FROM attendance a
        JOIN employee e ON e.id = a.employee
        JOIN company c ON c.id = e.company
        WHERE c.email = %s AND a.work_day = %s AND a.status = 1
          AND a.check_out_time IS NOT NULL AND a.check_out_time > a.check_in_time
    """, (email, hoje))
    total_horas = cur.fetchone()["total"]

# =============================================================================
# ALERTA DE FERIADO
# =============================================================================
if feriado_hoje:
    st.info(f"🎉 Hoje é feriado: **{feriado_hoje['name']}** ({feriado_hoje['holiday_type']})")

# =============================================================================
# KPIs
# =============================================================================
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Funcionários Ativos",       total_ativos)
c2.metric("Com Ponto Aberto Agora",    open_today)
c3.metric("Sem Registro Hoje",         sem_ponto_hoje,
          delta=f"escalados sem ponto" if sem_ponto_hoje else None,
          delta_color="inverse" if sem_ponto_hoje else "off")
c4.metric("Aprovações Pendentes",      pendentes,
          delta="aguardando revisão" if pendentes else None,
          delta_color="inverse" if pendentes else "off")
c5.metric("Horas Fechadas Hoje",       total_horas or "-")

if prox_feriado:
    dias_ate = (prox_feriado["holiday_date"] - hoje).days
    st.caption(
        f"📅 Próximo feriado: **{prox_feriado['name']}** — "
        f"{prox_feriado['holiday_date'].strftime('%d/%m/%Y')} "
        f"({'amanhã' if dias_ate == 1 else f'em {dias_ate} dias'})"
    )

st.markdown("---")

# =============================================================================
# ESCALA DE HOJE
# =============================================================================
st.subheader("Escala de Hoje")

with db_cursor() as (_, cur):
    cur.execute("""
        SELECT
            e.first_name || ' ' || e.last_name AS funcionario,
            CASE
                WHEN s.is_day_off THEN COALESCE(s.day_off_type, 'dsr')
                ELSE NULL
            END AS tipo_folga,
            TO_CHAR(s.start_time, 'HH24:MI') AS entrada_prevista,
            TO_CHAR(s.end_time,   'HH24:MI') AS saida_prevista,
            CASE
                WHEN s.is_day_off THEN 'Folga'
                WHEN a.has_open  THEN 'Em serviço'
                WHEN a.has_closed THEN 'Encerrado'
                WHEN a.employee IS NOT NULL THEN 'Em serviço'
                ELSE 'Sem registro'
            END AS situacao,
            TO_CHAR(a.primeiro_checkin, 'HH24:MI') AS check_in
        FROM schedule s
        JOIN employee e ON e.id = s.employee
        JOIN company c ON c.id = e.company
        LEFT JOIN (
            SELECT
                employee,
                MIN(check_in_time)  AS primeiro_checkin,
                BOOL_OR(status = 3) AS has_open,
                BOOL_OR(check_out_time IS NOT NULL AND check_out_time > check_in_time) AS has_closed
            FROM attendance
            WHERE work_day = %s AND status IN (1, 3)
            GROUP BY employee
        ) a ON a.employee = s.employee
        WHERE c.email = %s AND s.work_date = %s
        ORDER BY s.is_day_off ASC, s.start_time ASC, e.first_name ASC
    """, (hoje, email, hoje))
    escala_hoje = cur.fetchall()

if escala_hoje:
    TYPE_LABEL = {
        "dsr": "Folga", "ferias": "Férias", "feriado": "Feriado",
        "atestado": "Atestado", "banco_horas": "BH", "licenca": "Licença",
        "dispensa": "Dispensa", "rotacao": "🔄 Rotação",
    }
    SITUACAO_COR = {
        "Encerrado":   "🟢",
        "Em serviço":  "🟡",
        "Sem registro":"🔴",
        "Folga":       "⚪",
    }
    rows_esc = []
    for r in escala_hoje:
        sit = r["situacao"]
        rows_esc.append({
            "Funcionário":      r["funcionario"],
            "Entrada Prevista": r["entrada_prevista"] or (TYPE_LABEL.get(r["tipo_folga"], r["tipo_folga"]) if r["tipo_folga"] else "-"),
            "Saída Prevista":   r["saida_prevista"] or "-",
            "Check-in":         r["check_in"] or "-",
            "Situação":         f"{SITUACAO_COR.get(sit, '')} {sit}",
        })
    st.dataframe(pd.DataFrame(rows_esc), use_container_width=True, hide_index=True)
    st.caption("🟢 Encerrado  🟡 Em serviço  🔴 Sem registro  ⚪ Folga/Ausência")
else:
    st.info("Nenhuma escala cadastrada para hoje.")

st.markdown("---")

# =============================================================================
# PRÓXIMOS ANIVERSÁRIOS
# =============================================================================
st.subheader("Próximos Aniversários")

with db_cursor() as (_, cur):
    cur.execute("""
        SELECT
            e.first_name || ' ' || e.last_name AS nome,
            TO_CHAR(e.birth_date, 'DD/MM') AS dia_mes,
            CASE
                WHEN TO_DATE(TO_CHAR(%s::date, 'YYYY') || '-' || TO_CHAR(e.birth_date, 'MM-DD'), 'YYYY-MM-DD') >= %s::date
                THEN TO_DATE(TO_CHAR(%s::date, 'YYYY') || '-' || TO_CHAR(e.birth_date, 'MM-DD'), 'YYYY-MM-DD')
                ELSE TO_DATE(TO_CHAR((%s::date + INTERVAL '1 year'), 'YYYY') || '-' || TO_CHAR(e.birth_date, 'MM-DD'), 'YYYY-MM-DD')
            END AS prox_aniversario,
            DATE_PART('year', AGE(e.birth_date)) + 1 AS prox_idade
        FROM employee e
        JOIN company c ON c.id = e.company
        WHERE c.email = %s AND e.status = 1 AND e.birth_date IS NOT NULL
        ORDER BY prox_aniversario ASC
        LIMIT 5
    """, (hoje, hoje, hoje, hoje, email))
    aniversarios = cur.fetchall()

if aniversarios:
    cols = st.columns(len(aniversarios))
    for i, row in enumerate(aniversarios):
        delta_days = (row["prox_aniversario"] - hoje).days
        delta_str = "Hoje! 🎂" if delta_days == 0 else f"em {delta_days} dia(s)"
        cols[i].metric(label=row["nome"], value=row["dia_mes"], delta=delta_str)
else:
    st.info("Nenhum aniversário próximo encontrado.")

st.markdown("---")

# =============================================================================
# ESCALA DA SEMANA
# =============================================================================
DIAS_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
DAY_OFF_DISPLAY = {
    "dsr": "Folga", "ferias": "Férias", "feriado": "Feriado",
    "atestado": "Atestado", "banco_horas": "BH", "licenca": "Licença",
    "dispensa": "Dispensa", "rotacao": "🔄 Folga", "sab_rotacao": "🔄 Folga",
    "pos_rotacao": "🔄 Folga",
}

week_start = hoje - timedelta(days=hoje.weekday())
week_end   = week_start + timedelta(days=6)
week_label = f"{week_start.strftime('%d/%m')} – {week_end.strftime('%d/%m/%Y')}"
st.subheader(f"Escala da Semana — {week_label}")

with db_cursor() as (_, cur):
    cur.execute("""
        SELECT e.first_name || ' ' || e.last_name AS nome,
               s.work_date, s.start_time, s.is_day_off, s.day_off_type
        FROM schedule s
        JOIN employee e ON e.id = s.employee
        JOIN company c ON c.id = e.company
        WHERE c.email = %s AND s.work_date BETWEEN %s AND %s
        ORDER BY e.first_name, s.work_date
    """, (email, week_start, week_end))
    escala_semana = cur.fetchall()

    cur.execute("""
        SELECT e.id, e.first_name || ' ' || e.last_name AS nome
        FROM employee e
        JOIN company c ON c.id = e.company
        WHERE c.email = %s AND e.status = 1
        ORDER BY e.first_name
    """, (email,))
    emp_rows = cur.fetchall()

emp_names = [e["nome"] for e in emp_rows]
dates      = [week_start + timedelta(days=i) for i in range(7)]
col_hdrs   = [f"{DIAS_PT[i]}\n{d.strftime('%d/%m')}" for i, d in enumerate(dates)]

sched_map = {}
for r in escala_semana:
    if r["is_day_off"]:
        cell = DAY_OFF_DISPLAY.get(r["day_off_type"] or "dsr", "Folga")
    elif r["start_time"]:
        cell = r["start_time"].strftime("%H:%M")
    else:
        cell = ""
    sched_map[(r["nome"], r["work_date"])] = cell

df_semana = pd.DataFrame(
    {h: [sched_map.get((name, d), "") for name in emp_names]
     for h, d in zip(col_hdrs, dates)},
    index=emp_names,
)

if not df_semana.empty:
    st.dataframe(df_semana, use_container_width=True)
else:
    st.info("Nenhuma escala cadastrada para esta semana.")
