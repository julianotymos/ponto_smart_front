import streamlit as st
from utils.db import db_cursor
from datetime import datetime, date, timedelta, timezone

BRT = timezone(timedelta(hours=-3))

def to_brt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BRT)

st.set_page_config(page_title="Aprovações - Ponto Smart", layout="wide")
st.markdown("""
<style>
[data-testid="stStatusWidget"] { display: none !important; }
.block-container { padding-top: 1rem !important; }
h1 { margin-bottom: 0 !important; }
hr { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
header[data-testid="stHeader"] { height: 2.5rem !important; min-height: 2.5rem !important; }
</style>
""", unsafe_allow_html=True)

SYSTEM_USER = 1

from utils.auth import require_login

require_login()
company_id = st.session_state["company_id"]

st.title("✅ Aprovações de Ponto")
st.markdown("---")

col_title, col_refresh = st.columns([6, 1])
with col_refresh:
    if st.button("🔄 Atualizar", use_container_width=True):
        st.rerun()

aba_pendentes, aba_historico = st.tabs(["⏳ Pendentes", "📋 Histórico"])


# ─── ABA PENDENTES ───────────────────────────────────────────
with aba_pendentes:
    with db_cursor() as (_, cur):
        cur.execute("""
            SELECT
                apr.id,
                apr.employee,
                e.first_name || ' ' || e.last_name AS employee_name,
                apr.work_date,
                apr.requested_at,
                apr.schedule_start_time,
                apr.minutes_diff,
                apr.location,
                apr.observation
            FROM attendance_pending_request apr
            JOIN employee e ON e.id = apr.employee
            WHERE apr.company = %s
              AND apr.status = 'pending'
            ORDER BY apr.requested_at ASC
        """, (company_id,))
        rows = cur.fetchall()

    if not rows:
        st.info("Nenhuma solicitação pendente no momento.")
    else:
        st.markdown(f"**{len(rows)} solicitação(ões) aguardando aprovação**")
        st.markdown("")

        for row in rows:
            minutes = abs(row["minutes_diff"])
            direction = "atrasado(a)" if row["minutes_diff"] > 0 else "adiantado(a)"
            schedule_str = row["schedule_start_time"].strftime("%H:%M") if row["schedule_start_time"] else "-"
            requested_str = to_brt(row["requested_at"]).strftime("%H:%M") if row["requested_at"] else "-"
            date_str = row["work_date"].strftime("%d/%m/%Y") if row["work_date"] else "-"

            with st.container(border=True):
                col1, col2 = st.columns([3, 1])

                with col1:
                    st.markdown(f"### {row['employee_name']}")
                    st.markdown(
                        f"📅 **{date_str}** &nbsp;|&nbsp; "
                        f"🕐 Escala: **{schedule_str}** &nbsp;|&nbsp; "
                        f"Solicitação: **{requested_str}** &nbsp;|&nbsp; "
                        f"{'🔴' if row['minutes_diff'] > 0 else '🟡'} **{minutes} min {direction}**"
                    )
                    if row["location"]:
                        st.caption(f"📍 {row['location']}")
                    if row["observation"]:
                        st.caption(f"💬 Motivo: {row['observation']}")

                with col2:
                    manager_note = st.text_input(
                        "Observação (opcional)",
                        key=f"note_{row['id']}",
                        label_visibility="collapsed",
                        placeholder="Observação...",
                    )

                    col_ap, col_rej = st.columns(2)
                    with col_ap:
                        if st.button("✅ Aprovar", key=f"approve_{row['id']}", use_container_width=True, type="primary"):
                            with db_cursor() as (conn, cur):
                                cur.execute("""
                                    UPDATE attendance_pending_request
                                    SET status = 'approved',
                                        manager_note = %s,
                                        reviewed_by = %s,
                                        reviewed_at = NOW()
                                    WHERE id = %s AND status = 'pending'
                                """, (manager_note or None, SYSTEM_USER, row["id"]))
                                cur.execute("""
                                    INSERT INTO attendance (
                                        employee, work_day, check_in_time, check_out_time,
                                        observation, insert_date, update_date, status, status_date,
                                        system_user, location
                                    ) VALUES (
                                        %s, %s, %s, NULL,
                                        %s, NOW(), NOW(), 3, NOW(),
                                        %s, %s
                                    )
                                """, (
                                    row["employee"],
                                    to_brt(row["requested_at"]).date(),
                                    to_brt(row["requested_at"]).replace(tzinfo=None),
                                    row["observation"],
                                    SYSTEM_USER,
                                    row["location"],
                                ))
                                conn.commit()
                            st.success(f"Aprovado. Ponto registrado automaticamente.")
                            st.rerun()

                    with col_rej:
                        if st.button("❌ Rejeitar", key=f"reject_{row['id']}", use_container_width=True):
                            with db_cursor() as (conn, cur):
                                cur.execute("""
                                    UPDATE attendance_pending_request
                                    SET status = 'rejected',
                                        manager_note = %s,
                                        reviewed_by = %s,
                                        reviewed_at = NOW()
                                    WHERE id = %s AND status = 'pending'
                                """, (manager_note or None, SYSTEM_USER, row["id"]))
                                conn.commit()
                            st.warning(f"Rejeitado.")
                            st.rerun()


# ─── ABA HISTÓRICO ───────────────────────────────────────────
with aba_historico:
    col_f1, col_f2, col_f3 = st.columns([2, 2, 2])
    with col_f1:
        data_ini = st.date_input("De", value=date.today() - timedelta(days=30), key="hist_ini")
    with col_f2:
        data_fim = st.date_input("Até", value=date.today(), key="hist_fim")
    with col_f3:
        status_filter = st.selectbox(
            "Status",
            options=["Todos", "Pendente", "Aprovado", "Rejeitado"],
            key="hist_status"
        )

    status_map = {"Todos": None, "Pendente": "pending", "Aprovado": "approved", "Rejeitado": "rejected"}
    status_val = status_map[status_filter]

    with db_cursor() as (_, cur):
        if status_val:
            cur.execute("""
                SELECT
                    apr.id,
                    e.first_name || ' ' || e.last_name AS employee_name,
                    apr.work_date,
                    apr.requested_at,
                    apr.schedule_start_time,
                    apr.minutes_diff,
                    apr.status,
                    apr.location,
                    apr.observation,
                    apr.manager_note,
                    apr.reviewed_at
                FROM attendance_pending_request apr
                JOIN employee e ON e.id = apr.employee
                WHERE apr.company = %s
                  AND apr.work_date BETWEEN %s AND %s
                  AND apr.status = %s
                ORDER BY apr.work_date DESC, apr.requested_at DESC
            """, (company_id, data_ini, data_fim, status_val))
        else:
            cur.execute("""
                SELECT
                    apr.id,
                    e.first_name || ' ' || e.last_name AS employee_name,
                    apr.work_date,
                    apr.requested_at,
                    apr.schedule_start_time,
                    apr.minutes_diff,
                    apr.status,
                    apr.location,
                    apr.observation,
                    apr.manager_note,
                    apr.reviewed_at
                FROM attendance_pending_request apr
                JOIN employee e ON e.id = apr.employee
                WHERE apr.company = %s
                  AND apr.work_date BETWEEN %s AND %s
                ORDER BY apr.work_date DESC, apr.requested_at DESC
            """, (company_id, data_ini, data_fim))
        hist_rows = cur.fetchall()

    if not hist_rows:
        st.info("Nenhum registro encontrado para o período selecionado.")
    else:
        st.markdown(f"**{len(hist_rows)} registro(s) encontrado(s)**")
        st.markdown("")

        STATUS_LABEL = {
            "pending":  ("⏳ Pendente",  "orange"),
            "approved": ("✅ Aprovado",  "green"),
            "rejected": ("❌ Rejeitado", "red"),
        }

        for row in hist_rows:
            minutes   = abs(row["minutes_diff"])
            direction = "atrasado(a)" if row["minutes_diff"] > 0 else "adiantado(a)"
            schedule_str  = row["schedule_start_time"].strftime("%H:%M") if row["schedule_start_time"] else "-"
            requested_str = to_brt(row["requested_at"]).strftime("%H:%M") if row["requested_at"] else "-"
            date_str      = row["work_date"].strftime("%d/%m/%Y") if row["work_date"] else "-"
            label, color  = STATUS_LABEL.get(row["status"], (row["status"], "gray"))

            with st.container(border=True):
                col_info, col_act = st.columns([5, 1])

                with col_info:
                    st.markdown(
                        f"**{row['employee_name']}** &nbsp;·&nbsp; 📅 {date_str} &nbsp;·&nbsp; "
                        f":{color}[{label}]"
                    )
                    st.markdown(
                        f"🕐 Escala: **{schedule_str}** &nbsp;|&nbsp; "
                        f"Solicitação: **{requested_str}** &nbsp;|&nbsp; "
                        f"{'🔴' if row['minutes_diff'] > 0 else '🟡'} **{minutes} min {direction}**"
                    )
                    if row["observation"]:
                        st.markdown(f"💬 **Motivo:** {row['observation']}")
                    if row["manager_note"]:
                        st.caption(f"📝 Gestor: {row['manager_note']}")
                    if row["location"]:
                        st.caption(f"📍 {row['location']}")

                with col_act:
                    if st.button("🗑️ Excluir", key=f"del_hist_{row['id']}", use_container_width=True):
                        with db_cursor() as (conn, cur):
                            cur.execute("DELETE FROM attendance_pending_request WHERE id = %s", (row["id"],))
                            conn.commit()
                        st.rerun()
