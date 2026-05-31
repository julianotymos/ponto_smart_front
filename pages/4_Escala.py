import streamlit as st
from utils.db import db_cursor
from datetime import date, timedelta, time as Time, datetime
import pandas as pd
import time as time_module
import re
import requests

st.set_page_config(page_title="Escala - Ponto Smart", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
[data-testid="stStatusWidget"] { display: none !important; }
[data-testid="stToolbar"] { display: none !important; }
.block-container { padding-top: 1rem !important; }
h1 { margin-bottom: 0 !important; }
h2, h3 { margin-top: 0 !important; margin-bottom: 0.5rem !important; }
hr { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
header[data-testid="stHeader"] { height: 2.5rem !important; min-height: 2.5rem !important; overflow: visible !important; }
</style>
""", unsafe_allow_html=True)

SYSTEM_USER = 1
DIAS_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

STORE_OPEN  = {0: Time(11,30), 1: Time(11,30), 2: Time(11,30),
               3: Time(11,30), 4: Time(11,30), 5: Time(11, 0), 6: Time(12, 0)}
STORE_CLOSE = {0: Time(21, 0), 1: Time(21, 0), 2: Time(21, 0),
               3: Time(21, 0), 4: Time(21, 0), 5: Time(21,30), 6: Time(21,30)}
MIDDAY_CHECK = Time(14, 0)

DAY_OFF_KEYWORDS = {
    "FOLGA":    "dsr",
    "FERIAS":   "ferias",
    "FÉRIAS":   "ferias",
    "FERIADO":  "feriado",
    "ATESTADO": "atestado",
    "BH":       "banco_horas",
    "LICENCA":  "licenca",
    "LICENÇA":  "licenca",
    "DISPENSA": "dispensa",
}

DAY_OFF_DISPLAY = {
    "dsr":         "Folga",
    "ferias":      "Férias",
    "feriado":     "Feriado",
    "atestado":    "Atestado",
    "banco_horas": "BH",
    "licenca":     "Licença",
    "dispensa":    "Dispensa",
    "rotacao":     "🔄 Folga",
    "sab_rotacao": "🔄 Folga",
    "pos_rotacao": "🔄 Folga",
}

from utils.auth import require_login


def parse_cell(cell):
    v = str(cell).strip() if cell and not pd.isna(cell) else ""
    if not v:
        return None, False, None
    is_rotation = v.startswith("🔄 ")
    v_norm = v.replace("🔄 ", "").strip()
    v_up = v_norm.upper()
    if v_up in DAY_OFF_KEYWORDS:
        day_off_type = "rotacao" if is_rotation else DAY_OFF_KEYWORDS[v_up]
        return None, True, day_off_type
    m = re.match(r"(\d{1,2}):(\d{2})$", v_norm)
    if not m:
        return None, None, None
    try:
        return Time(int(m[1]), int(m[2])), False, None
    except ValueError:
        return None, None, None


def calc_end(start: Time, shift_min: int) -> Time:
    dt = datetime(2000, 1, 1, start.hour, start.minute) + timedelta(minutes=shift_min)
    return dt.time()


def shift_minutes(weekly_workload) -> int:
    daily_h = float(weekly_workload or 40.0) / 5.0
    return int(daily_h * 60) + 60


def fmt(t: Time | None) -> str:
    return t.strftime("%H:%M") if t else ""


def cell_from_row(row) -> str:
    if row["is_day_off"]:
        return DAY_OFF_DISPLAY.get(row.get("day_off_type") or "dsr", "Folga")
    if row["start_time"]:
        return fmt(row["start_time"])
    return ""


def detect_cycle_week(company_id: int, target_monday: date,
                      tmpl_by_week: dict, emp_ids: list) -> int:
    """
    Compara o domingo real mais recente na escala com o padrão de domingos
    de cada semana do template para identificar em qual semana do ciclo
    (1-4) target_monday se encontra.
    Retorna 1 se não houver dados suficientes.
    """
    target_sunday = target_monday + timedelta(days=6)

    with db_cursor() as (_, cur):
        cur.execute("""
            SELECT MAX(work_date) AS ref_sunday
            FROM schedule
            WHERE company = %s
              AND EXTRACT(DOW FROM work_date) = 0
              AND work_date <= %s
        """, (company_id, target_sunday))
        row = cur.fetchone()
        ref_sunday = row["ref_sunday"] if row and row["ref_sunday"] else None

        if not ref_sunday:
            return 1

        cur.execute("""
            SELECT employee, is_day_off FROM schedule
            WHERE company = %s AND work_date = %s
        """, (company_id, ref_sunday))
        actual_off = {r["employee"]: r["is_day_off"] for r in cur.fetchall()}

    # Pontua cada semana do template pelo match no domingo
    best_wn, best_score = 1, -1
    for wn in range(1, 4):
        tmpl_wk = tmpl_by_week.get(wn, {})
        score = sum(
            1 for eid in emp_ids
            if actual_off.get(eid, False) == tmpl_wk.get((eid, 6), {}).get("is_day_off", False)
        )
        if score > best_score:
            best_score, best_wn = score, wn

    # Avança o número de semanas entre ref_sunday e target_sunday
    weeks_ahead = (target_sunday - ref_sunday).days // 7
    return (best_wn - 1 + weeks_ahead) % 3 + 1


def count_presentes(df: pd.DataFrame, col_headers: list) -> pd.DataFrame:
    counts = {}
    for h in col_headers:
        n = 0
        for name in df.index:
            cell = str(df.at[name, h]).strip()
            if cell:
                st_t, is_off, _ = parse_cell(cell)
                if st_t is not None and not is_off:
                    n += 1
        counts[h] = n
    return pd.DataFrame([counts], index=["👥 Presentes"])


def validate_grid(df: pd.DataFrame, col_headers: list, emp_shift: dict) -> list:
    msgs = []
    for i, col in enumerate(col_headers):
        dow = i % 7
        open_t  = STORE_OPEN[dow]
        close_t = STORE_CLOSE[dow]
        day_label = col.split("\n")[0]

        intervals = []
        for name in df.index:
            st_t, is_off, _ = parse_cell(df.at[name, col])
            if is_off or st_t is None:
                continue
            intervals.append((st_t, calc_end(st_t, emp_shift.get(name, 540))))

        if not any(s <= open_t for s, _ in intervals):
            msgs.append(f"**{day_label}** — ninguém cobre a abertura ({fmt(open_t)})")
        if not any(e >= close_t for _, e in intervals):
            msgs.append(f"**{day_label}** — ninguém cobre o fechamento ({fmt(close_t)})")

        if dow <= 4:
            WIN = Time(12, 30)
            critical = sorted({WIN} | {t for s, e in intervals for t in (s, e) if WIN <= t <= close_t})
            min_n, min_t = None, None
            for t in critical:
                if t >= close_t:
                    break
                n = sum(1 for s, e in intervals if s <= t < e)
                if min_n is None or n < min_n:
                    min_n, min_t = n, t
            if min_n is not None and min_n < 2:
                msgs.append(f"**{day_label}** — apenas {min_n} pessoa(s) às {fmt(min_t)} (mínimo 2 entre 12:30–{fmt(close_t)})")
        else:
            midday = sum(1 for s, e in intervals if s <= MIDDAY_CHECK <= e)
            if midday < 2:
                msgs.append(f"**{day_label}** — menos de 2 pessoas às {fmt(MIDDAY_CHECK)} ({midday})")
    return msgs


# ─── Dialogs ──────────────────────────────────────────────────────────────────

@st.dialog("💾 Salvar Escala")
def dlg_salvar_semana(week_label: str):
    st.markdown(f"Confirmar salvamento da semana **{week_label}**?")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ Salvar", type="primary", use_container_width=True):
            st.session_state["_confirm_action"] = "save_week"
            st.rerun()
    with col2:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()


@st.dialog("🗑️ Excluir Escala da Semana")
def dlg_excluir_semana(week_label: str):
    st.warning(f"Remove **todos** os registros da semana **{week_label}**.")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ Excluir", type="primary", use_container_width=True):
            st.session_state["_confirm_action"] = "delete_week"
            st.rerun()
    with col2:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()


@st.dialog("💾 Salvar Template")
def dlg_salvar_template():
    st.markdown("Confirmar salvamento do template de 3 semanas?")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ Salvar", type="primary", use_container_width=True):
            st.session_state["_confirm_action"] = "save_template"
            st.rerun()
    with col2:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()


@st.dialog("💾 Salvar Escala Gerada")
def dlg_salvar_gerada():
    st.markdown("Confirmar salvamento da escala gerada?")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ Salvar", type="primary", use_container_width=True):
            st.session_state["_confirm_action"] = "save_generated"
            st.rerun()
    with col2:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()


@st.dialog("🗑️ Descartar Escala Gerada")
def dlg_descartar_gerada():
    st.warning("Descarta a prévia gerada sem salvar. Continuar?")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ Descartar", type="primary", use_container_width=True):
            st.session_state["_confirm_action"] = "discard_generated"
            st.rerun()
    with col2:
        if st.button("Cancelar", use_container_width=True):
            st.rerun()


# ──────────────────────────────────────────────────────────────────────────────

require_login()
company_id = st.session_state["company_id"]

st.title("📅 Escala de Trabalho")
st.markdown("---")

with db_cursor() as (_, cur):
    cur.execute("""
        SELECT id, first_name || ' ' || last_name AS name, weekly_workload
        FROM employee
        WHERE company = %s AND status = 1
        ORDER BY first_name, last_name
    """, (company_id,))
    employees = cur.fetchall()

if not employees:
    st.info("Nenhum funcionário ativo cadastrado.")
    st.stop()

emp_ids      = [e["id"]   for e in employees]
emp_names    = [e["name"] for e in employees]
emp_by_name  = {e["name"]: e["id"] for e in employees}
emp_wl       = {e["name"]: e["weekly_workload"] for e in employees}
emp_shift    = {e["name"]: shift_minutes(e["weekly_workload"]) for e in employees}
emp_wl_by_id = {e["id"]: e["weekly_workload"] for e in employees}

# Carrega o template completo uma vez (usado em todas as abas)
with db_cursor() as (_, cur):
    cur.execute("""
        SELECT employee, week_number, day_of_week, start_time, end_time, is_day_off, day_off_type
        FROM schedule_template
        WHERE company = %s
        ORDER BY week_number, day_of_week
    """, (company_id,))
    tmpl_all_rows = cur.fetchall()

tmpl_by_week: dict[int, dict] = {wn: {} for wn in range(1, 4)}
for r in tmpl_all_rows:
    wn = r["week_number"]
    if wn in tmpl_by_week:
        tmpl_by_week[wn][(r["employee"], r["day_of_week"])] = r

tab_visao, tab_semana, tab_geracao, tab_template, tab_feriados, tab_regras = st.tabs(
    ["🗓️ 4 Semanas", "📅 Semana", "🤖 Geração Automática", "📋 Template", "🎉 Feriados", "📖 Regras"]
)


# ─── TAB: 4 SEMANAS ───────────────────────────────────────────────────────────
with tab_visao:
    today = date.today()
    view_start = today - timedelta(days=today.weekday())
    view_end   = view_start + timedelta(weeks=4) - timedelta(days=1)

    st.caption(
        f"Visão geral das próximas 4 semanas: "
        f"**{view_start.strftime('%d/%m/%Y')}** – **{view_end.strftime('%d/%m/%Y')}**"
    )

    with db_cursor() as (_, cur):
        cur.execute("""
            SELECT employee, work_date, start_time, end_time, is_day_off, day_off_type
            FROM schedule
            WHERE company = %s AND work_date BETWEEN %s AND %s
            ORDER BY work_date
        """, (company_id, view_start, view_end))
        all_rows = cur.fetchall()

    all_map = {(r["employee"], r["work_date"]): cell_from_row(r) for r in all_rows}

    # Detecta semana do ciclo apenas para a primeira semana e avança
    first_wk_num = detect_cycle_week(company_id, view_start, tmpl_by_week, emp_ids) if tmpl_all_rows else None

    for w in range(4):
        wk_start = view_start + timedelta(weeks=w)
        wk_dates = [wk_start + timedelta(days=d) for d in range(7)]
        wk_hdrs  = [f"{DIAS_PT[d]}\n{dt.strftime('%d/%m')}" for d, dt in enumerate(wk_dates)]

        df_wk = pd.DataFrame(
            {h: [all_map.get((eid, d), "") for eid in emp_ids] for h, d in zip(wk_hdrs, wk_dates)},
            index=emp_names,
        )

        is_current = wk_start == (today - timedelta(days=today.weekday()))
        wk_num_str = f"  *(ciclo: sem. {(first_wk_num - 1 + w) % 3 + 1})*" if first_wk_num else ""
        label = (
            f"Semana {w + 1} — {wk_start.strftime('%d/%m')} a "
            f"{(wk_start + timedelta(days=6)).strftime('%d/%m/%Y')}"
            f"{wk_num_str}"
        )
        if is_current:
            label += "  ← atual"

        with st.expander(label, expanded=(w == 0)):
            wk_warns = validate_grid(df_wk, wk_hdrs, emp_shift)
            if wk_warns:
                st.markdown(f"⚠️ {len(wk_warns)} aviso(s) de cobertura")
            st.dataframe(df_wk, use_container_width=True)


# ─── TAB: SEMANA ──────────────────────────────────────────────────────────────
with tab_semana:
    today = date.today()
    if "escala_week_start" not in st.session_state:
        st.session_state["escala_week_start"] = today - timedelta(days=today.weekday())

    week_start: date = st.session_state["escala_week_start"]
    week_end   = week_start + timedelta(days=6)
    week_label = f"{week_start.strftime('%d/%m/%Y')} – {week_end.strftime('%d/%m/%Y')}"

    # Detecta semana do ciclo para esta semana
    week_cycle = detect_cycle_week(company_id, week_start, tmpl_by_week, emp_ids) if tmpl_all_rows else None
    cycle_info = f" &nbsp;<small style='color:#888'>ciclo: sem. {week_cycle}</small>" if week_cycle else ""

    col_prev, col_lbl, col_next = st.columns([1, 5, 1])
    with col_prev:
        if st.button("◀ Anterior", use_container_width=True, key="prev_week"):
            st.session_state["escala_week_start"] -= timedelta(weeks=1)
            st.rerun()
    with col_lbl:
        st.markdown(
            f"<h3 style='text-align:center;margin:0;padding:4px'>"
            f"{week_label}{cycle_info}</h3>",
            unsafe_allow_html=True,
        )
    with col_next:
        if st.button("Próxima ▶", use_container_width=True, key="next_week"):
            st.session_state["escala_week_start"] += timedelta(weeks=1)
            st.rerun()

    dates    = [week_start + timedelta(days=i) for i in range(7)]
    col_hdrs = [f"{DIAS_PT[i]}\n{d.strftime('%d/%m')}" for i, d in enumerate(dates)]

    with db_cursor() as (_, cur):
        cur.execute("""
            SELECT employee, work_date, start_time, end_time, is_day_off, day_off_type
            FROM schedule
            WHERE company = %s AND work_date BETWEEN %s AND %s
        """, (company_id, week_start, week_end))
        db_rows = cur.fetchall()

    sched_map = {(r["employee"], r["work_date"]): cell_from_row(r) for r in db_rows}

    df_week = pd.DataFrame(
        {h: [sched_map.get((eid, d), "") for eid in emp_ids] for h, d in zip(col_hdrs, dates)},
        index=emp_names,
    )

    col_btn_tmpl, col_info = st.columns([2, 5])
    with col_btn_tmpl:
        btn_label = f"📋 Preencher do Template"
        if week_cycle:
            btn_label += f" (sem. {week_cycle})"
        if st.button(btn_label, key="fill_from_tmpl"):
            if not week_cycle:
                st.error("Configure o template antes de preencher.")
            else:
                tmpl_fill = tmpl_by_week.get(week_cycle, {})
                with db_cursor() as (conn, cur):
                    for eid in emp_ids:
                        shift_min = shift_minutes(emp_wl_by_id.get(eid))
                        for i, d in enumerate(dates):
                            row = tmpl_fill.get((eid, i % 7))
                            if not row:
                                continue
                            cell = cell_from_row(row)
                            st_t, is_off, dot = parse_cell(cell)
                            en_t = calc_end(st_t, shift_min) if st_t else None
                            cur.execute("""
                                INSERT INTO schedule (employee, company, work_date, start_time, end_time,
                                    is_day_off, day_off_type, system_user)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (employee, work_date) DO NOTHING
                            """, (eid, company_id, d, st_t, en_t, is_off, dot, SYSTEM_USER))
                st.success(f"Template da semana {week_cycle} aplicado (células existentes mantidas).")
                for _k in [f"week_editor_{week_start}"]:
                    if _k in st.session_state:
                        del st.session_state[_k]
                time_module.sleep(1.5)
                st.rerun()

    st.caption(
        "Digite a hora de **entrada** (ex: `10:00`) ou o tipo de folga: "
        "**Folga**, **Férias**, **Feriado**, **Atestado**, **BH**, **Licença**, **Dispensa**."
    )

    edited = st.data_editor(
        df_week,
        use_container_width=True,
        num_rows="fixed",
        key=f"week_editor_{week_start}",
        column_config={h: st.column_config.TextColumn(h, width="small") for h in col_hdrs},
    )

    _row_cnt = count_presentes(edited, col_hdrs).iloc[0]
    _parts = []
    for _h in col_hdrs:
        _day = _h.split("\n")[0]
        _n = int(_row_cnt[_h])
        _clr = "green" if _n >= 2 else "red"
        _parts.append(f"{_day} :{_clr}[**{_n}**]")
    st.caption("👥 Presentes — " + "  ·  ".join(_parts))

    warnings = validate_grid(edited, col_hdrs, emp_shift)
    if warnings:
        with st.expander(f"⚠️ {len(warnings)} aviso(s) de cobertura", expanded=True):
            for w in warnings:
                st.markdown(f"- {w}")
    else:
        st.success("✅ Cobertura completa para a semana.")

    if st.session_state.get("_confirm_action") == "save_week":
        del st.session_state["_confirm_action"]
        errs, count = [], 0
        with db_cursor() as (conn, cur):
            for name in emp_names:
                eid = emp_by_name[name]
                shift_min = emp_shift[name]
                for h, d in zip(col_hdrs, dates):
                    raw  = edited.at[name, h]
                    cell = str(raw).strip() if raw and not pd.isna(raw) else ""
                    if not cell:
                        cur.execute("DELETE FROM schedule WHERE employee=%s AND work_date=%s", (eid, d))
                        continue
                    st_t, is_off, dot = parse_cell(cell)
                    if not is_off and st_t is None:
                        errs.append(f"**{name}** / {h}: formato inválido `{cell}`")
                        continue
                    en_t = calc_end(st_t, shift_min) if st_t else None
                    cur.execute("""
                        INSERT INTO schedule (employee, company, work_date, start_time, end_time,
                            is_day_off, day_off_type, system_user)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (employee, work_date) DO UPDATE SET
                            start_time=EXCLUDED.start_time, end_time=EXCLUDED.end_time,
                            is_day_off=EXCLUDED.is_day_off, day_off_type=EXCLUDED.day_off_type,
                            update_date=NOW(), system_user=EXCLUDED.system_user
                    """, (eid, company_id, d, st_t, en_t, is_off, dot, SYSTEM_USER))
                    count += 1
        if errs:
            for e in errs:
                st.error(e)
        else:
            st.success(f"Escala salva! ({count} registros)")
            if f"week_editor_{week_start}" in st.session_state:
                del st.session_state[f"week_editor_{week_start}"]
            time_module.sleep(1.5)
            st.rerun()

    if st.session_state.get("_confirm_action") == "delete_week":
        del st.session_state["_confirm_action"]
        with db_cursor() as (conn, cur):
            cur.execute(
                "DELETE FROM schedule WHERE company=%s AND work_date BETWEEN %s AND %s",
                (company_id, week_start, week_end),
            )
            deleted = cur.rowcount
        st.success(f"{deleted} registros excluídos.")
        if f"week_editor_{week_start}" in st.session_state:
            del st.session_state[f"week_editor_{week_start}"]
        time_module.sleep(1.5)
        st.rerun()

    st.markdown("")
    col_sv, col_del = st.columns([3, 1])
    with col_sv:
        if st.button("💾 Salvar Escala", type="primary", use_container_width=True, key="save_week"):
            dlg_salvar_semana(week_label)
    with col_del:
        if st.button("🗑️ Excluir semana", use_container_width=True, key="btn_del_week"):
            dlg_excluir_semana(week_label)

    st.markdown("")
    with st.expander("ℹ️ Carga horária por funcionário", expanded=False):
        rows_leg = []
        for name in emp_names:
            wl = float(emp_wl.get(name) or 40.0)
            daily = wl / 5.0
            total_min = shift_minutes(emp_wl.get(name))
            rows_leg.append({
                "Funcionário": name,
                "Carga Semanal (h)": wl,
                "Horas/dia": f"{daily:.1f}h",
                "Turno (c/ 1h intervalo)": f"{int(total_min // 60)}h{int(total_min % 60):02d}min",
            })
        st.dataframe(pd.DataFrame(rows_leg).set_index("Funcionário"), use_container_width=True)


# ─── TAB: TEMPLATE ────────────────────────────────────────────────────────────
with tab_template:
    st.caption(
        "Define o padrão de **3 semanas** que se repete ciclicamente, incluindo "
        "os domingos de rotação de cada funcionário. "
        "A posição no ciclo é detectada automaticamente pelo histórico de domingos na escala."
    )

    # Constrói DataFrames editáveis por semana a partir do tmpl_by_week já carregado
    edited_tmpls: dict[int, pd.DataFrame] = {}

    st.caption(
        "Digite a hora de **entrada** (ex: `10:00`) ou o tipo de folga: "
        "**Folga**, **Férias**, **Feriado**, **Atestado**, **BH**, **Licença**, **Dispensa**."
    )

    for wn in range(1, 4):
        tmpl_wk = tmpl_by_week.get(wn, {})
        df_wn = pd.DataFrame(
            {dia: [cell_from_row(tmpl_wk[(eid, i)]) if (eid, i) in tmpl_wk else ""
                   for eid in emp_ids]
             for i, dia in enumerate(DIAS_PT)},
            index=emp_names,
        )

        # Identifica quem está de folga no domingo desta semana do template
        sun_off = [
            emp_names[j] for j, eid in enumerate(emp_ids)
            if tmpl_wk.get((eid, 6), {}).get("is_day_off", False)
        ]
        sun_info = f"  —  folga dom.: {', '.join(sun_off)}" if sun_off else "  —  todos trabalham domingo"

        with st.expander(f"Semana {wn}{sun_info}", expanded=(wn == 1)):
            warns_wn = validate_grid(df_wn, DIAS_PT, emp_shift)
            if warns_wn:
                st.caption(f"⚠️ {len(warns_wn)} aviso(s) de cobertura nesta semana")

            edited_wn = st.data_editor(
                df_wn,
                use_container_width=True,
                num_rows="fixed",
                key=f"tmpl_editor_w{wn}",
                column_config={dia: st.column_config.TextColumn(dia, width="small") for dia in DIAS_PT},
            )
            edited_tmpls[wn] = edited_wn

    # ── Validação: cada funcionário pode ter no máximo 1 domingo de folga no ciclo
    dom_off_count: dict[str, list[int]] = {name: [] for name in emp_names}
    for wn, df_ed in edited_tmpls.items():
        for name in emp_names:
            cell = str(df_ed.at[name, "Dom"]).strip()
            if cell:
                _, is_off, _ = parse_cell(cell)
                if is_off:
                    dom_off_count[name].append(wn)

    dom_erros = [
        f"**{name}**: domingo de folga em {len(semanas)} semanas ({', '.join(f'sem. {w}' for w in semanas)}) — permitido apenas 1"
        for name, semanas in dom_off_count.items()
        if len(semanas) > 1
    ]

    if dom_erros:
        st.markdown("---")
        st.error("Corrija antes de salvar — cada funcionário só pode ter **1 domingo de folga** no ciclo de 3 semanas:")
        for e in dom_erros:
            st.markdown(f"- {e}")

    if st.session_state.get("_confirm_action") == "save_template":
        del st.session_state["_confirm_action"]
        if dom_erros:
            st.error("Salvo cancelado. Corrija os domingos duplicados primeiro.")
        else:
            errs, count = [], 0
            with db_cursor() as (conn, cur):
                for wn, df_ed in edited_tmpls.items():
                    for name in emp_names:
                        eid = emp_by_name[name]
                        shift_min = emp_shift[name]
                        for i, dia in enumerate(DIAS_PT):
                            raw  = df_ed.at[name, dia]
                            cell = str(raw).strip() if raw and not pd.isna(raw) else ""
                            if not cell:
                                cur.execute(
                                    "DELETE FROM schedule_template WHERE employee=%s AND company=%s AND week_number=%s AND day_of_week=%s",
                                    (eid, company_id, wn, i),
                                )
                                continue
                            st_t, is_off, dot = parse_cell(cell)
                            if not is_off and st_t is None:
                                errs.append(f"Sem. {wn} / **{name}** / {dia}: formato inválido `{cell}`")
                                continue
                            en_t = calc_end(st_t, shift_min) if st_t else None
                            cur.execute("""
                                INSERT INTO schedule_template
                                    (employee, company, week_number, day_of_week, start_time, end_time,
                                     is_day_off, day_off_type, system_user)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (employee, week_number, day_of_week) DO UPDATE SET
                                    start_time=EXCLUDED.start_time, end_time=EXCLUDED.end_time,
                                    is_day_off=EXCLUDED.is_day_off, day_off_type=EXCLUDED.day_off_type,
                                    update_date=NOW(), system_user=EXCLUDED.system_user
                            """, (eid, company_id, wn, i, st_t, en_t, is_off, dot, SYSTEM_USER))
                            count += 1
            if errs:
                for e in errs:
                    st.error(e)
            else:
                st.success(f"Template de 4 semanas salvo! ({count} registros)")
                time_module.sleep(1.5)
                st.rerun()

    st.markdown("")
    if st.button("💾 Salvar Template", type="primary", use_container_width=True,
                 key="save_tmpl", disabled=bool(dom_erros)):
        dlg_salvar_template()


# ─── TAB: GERAÇÃO AUTOMÁTICA ──────────────────────────────────────────────────
with tab_geracao:
    today_ref = date.today()

    st.caption(
        "Gera a escala aplicando o template de 3 semanas ciclicamente. "
        "A semana do ciclo é detectada automaticamente pelos domingos já escalados."
    )

    if not tmpl_all_rows:
        st.warning("Nenhum template configurado. Preencha a aba **Template** antes de gerar.")
        st.stop()

    with db_cursor() as (_, cur):
        cur.execute("SELECT MAX(work_date) AS last_date FROM schedule WHERE company = %s", (company_id,))
        row_last = cur.fetchone()

    last_scheduled = row_last["last_date"] if row_last and row_last["last_date"] else None

    if last_scheduled:
        raw_next   = last_scheduled + timedelta(days=1)
        auto_start = raw_next - timedelta(days=raw_next.weekday())
        st.info(f"Escala existente até **{last_scheduled.strftime('%d/%m/%Y')}**. Início sugerido: **{auto_start.strftime('%d/%m/%Y')}**.")
    else:
        auto_start = today_ref + timedelta(days=(7 - today_ref.weekday()) % 7 or 7)
        st.info("Nenhuma escala encontrada. Início sugerido: próxima semana.")

    col_a, col_b = st.columns([2, 1])
    with col_a:
        gen_start_input = st.date_input("Início da geração", value=auto_start, key="gen_start")
        gen_start_adj   = gen_start_input - timedelta(days=gen_start_input.weekday())
        if gen_start_adj != gen_start_input:
            st.caption(f"Ajustado para segunda-feira: {gen_start_adj.strftime('%d/%m/%Y')}")
    with col_b:
        num_weeks_gen = int(st.number_input("Semanas", min_value=1, max_value=8, value=4, key="gen_weeks"))

    # Detecta a semana do ciclo para o início da geração
    start_cycle_wk = detect_cycle_week(company_id, gen_start_adj, tmpl_by_week, emp_ids)

    st.caption(
        f"Início da geração identificado como **semana {start_cycle_wk}** do ciclo. "
        "Verifique os domingos do template se o ciclo parecer incorreto."
    )

    st.caption(
        "Digite a hora de **entrada** (ex: `10:00`) ou o tipo de folga: "
        "**Folga**, **Férias**, **Feriado**, **Atestado**, **BH**, **Licença**, **Dispensa**."
    )

    st.markdown("")
    if st.button("⚡ Gerar Escala", type="primary", use_container_width=True, key="btn_gerar"):
        generated: dict[tuple, dict] = {}

        for w in range(num_weeks_gen):
            wk_start_gen = gen_start_adj + timedelta(weeks=w)
            wk_dates     = [wk_start_gen + timedelta(days=d) for d in range(7)]
            wk_num       = (start_cycle_wk - 1 + w) % 3 + 1
            tmpl_wk      = tmpl_by_week.get(wk_num, {})

            for eid in emp_ids:
                for i, d in enumerate(wk_dates):
                    row = tmpl_wk.get((eid, i))
                    if row:
                        generated[(eid, d)] = {
                            "start_time":   row["start_time"],
                            "is_day_off":   row["is_day_off"],
                            "day_off_type": row.get("day_off_type") or ("dsr" if row["is_day_off"] else None),
                        }
                    else:
                        generated[(eid, d)] = {"start_time": None, "is_day_off": False, "day_off_type": None}

        st.session_state["gen_result"]      = generated
        st.session_state["gen_start_adj"]   = gen_start_adj
        st.session_state["gen_num_weeks"]   = num_weeks_gen
        st.session_state["gen_start_cycle"] = start_cycle_wk
        st.rerun()

    # ── Prévia ────────────────────────────────────────────────────────────────
    if "gen_result" in st.session_state:
        generated     = st.session_state["gen_result"]
        g_start       = st.session_state["gen_start_adj"]
        g_weeks       = st.session_state["gen_num_weeks"]
        g_start_cycle = st.session_state.get("gen_start_cycle", 1)

        st.markdown("---")
        st.subheader("Prévia da Escala Gerada")
        st.caption("Edite direto nas células antes de salvar. Use **HH:MM** para horário de entrada ou o tipo de folga.")

        edited_weeks: dict[int, tuple] = {}

        for w in range(g_weeks):
            wk_start_g = g_start + timedelta(weeks=w)
            wk_dates   = [wk_start_g + timedelta(days=d) for d in range(7)]
            wk_hdrs    = [f"{DIAS_PT[d]}\n{dt.strftime('%d/%m')}" for d, dt in enumerate(wk_dates)]
            wk_num     = (g_start_cycle - 1 + w) % 3 + 1

            preview_data = {h: [] for h in wk_hdrs}
            for h, d in zip(wk_hdrs, wk_dates):
                for eid in emp_ids:
                    entry = generated.get((eid, d))
                    if not entry:
                        preview_data[h].append("")
                    elif entry["is_day_off"]:
                        preview_data[h].append(DAY_OFF_DISPLAY.get(entry.get("day_off_type") or "dsr", "Folga"))
                    elif entry["start_time"]:
                        preview_data[h].append(fmt(entry["start_time"]))
                    else:
                        preview_data[h].append("")

            df_prev = pd.DataFrame(preview_data, index=emp_names)

            label = (
                f"Semana {w+1} — {wk_start_g.strftime('%d/%m')} a "
                f"{(wk_start_g + timedelta(days=6)).strftime('%d/%m/%Y')}  "
                f"*(ciclo: sem. {wk_num})*"
            )
            with st.expander(label, expanded=(w == 0)):
                df_edited = st.data_editor(
                    df_prev,
                    use_container_width=True,
                    num_rows="fixed",
                    key=f"gen_editor_w{w}_{g_start}",
                    column_config={h: st.column_config.TextColumn(h, width="small") for h in wk_hdrs},
                )
                edited_weeks[w] = (df_edited, wk_hdrs, wk_dates)

                _row_cnt_g = count_presentes(df_edited, wk_hdrs).iloc[0]
                _parts_g = [
                    f"{_h.split(chr(10))[0]} :{'green' if int(_row_cnt_g[_h]) >= 2 else 'red'}[**{int(_row_cnt_g[_h])}**]"
                    for _h in wk_hdrs
                ]
                st.caption("👥 Presentes — " + "  ·  ".join(_parts_g))

                warns = validate_grid(df_edited, wk_hdrs, emp_shift)
                folga_warns = [
                    f"**{name}** — {sum(1 for h in wk_hdrs if parse_cell(str(df_edited.at[name, h]).strip())[1])} folga(s) (esperado: 2)"
                    for name in emp_names
                    if sum(1 for h in wk_hdrs if parse_cell(str(df_edited.at[name, h]).strip())[1]) != 2
                ]
                if folga_warns or warns:
                    st.markdown("---")
                    for fw in folga_warns:
                        st.markdown(f"- 🔴 {fw}")
                    for wm in warns:
                        st.markdown(f"- ⚠️ {wm}")

        st.markdown("")
        overwrite = st.checkbox("Substituir registros já existentes no período", value=False, key="gen_overwrite")

        if st.session_state.get("_confirm_action") == "save_generated":
            del st.session_state["_confirm_action"]
            saved, errs = 0, []
            with db_cursor() as (conn, cur):
                for w, (df_ed, wk_hdrs, wk_dates) in edited_weeks.items():
                    for name in emp_names:
                        eid       = emp_by_name[name]
                        shift_min = emp_shift.get(name, 540)
                        for h, d in zip(wk_hdrs, wk_dates):
                            raw  = df_ed.at[name, h]
                            cell = str(raw).strip() if raw and not pd.isna(raw) else ""
                            if not cell:
                                continue
                            st_t, is_off, dot = parse_cell(cell)
                            if not is_off and st_t is None:
                                errs.append(f"**{name}** / {h}: formato inválido `{cell}`")
                                continue
                            en_t = calc_end(st_t, shift_min) if st_t else None
                            if overwrite:
                                cur.execute("""
                                    INSERT INTO schedule (employee, company, work_date, start_time, end_time,
                                        is_day_off, day_off_type, system_user)
                                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                                    ON CONFLICT (employee, work_date) DO UPDATE SET
                                        start_time=EXCLUDED.start_time, end_time=EXCLUDED.end_time,
                                        is_day_off=EXCLUDED.is_day_off, day_off_type=EXCLUDED.day_off_type,
                                        update_date=NOW(), system_user=EXCLUDED.system_user
                                """, (eid, company_id, d, st_t, en_t, is_off, dot, SYSTEM_USER))
                            else:
                                cur.execute("""
                                    INSERT INTO schedule (employee, company, work_date, start_time, end_time,
                                        is_day_off, day_off_type, system_user)
                                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                                    ON CONFLICT (employee, work_date) DO NOTHING
                                """, (eid, company_id, d, st_t, en_t, is_off, dot, SYSTEM_USER))
                            saved += 1
            if errs:
                for e in errs:
                    st.error(e)
            else:
                st.success(f"Escala salva! ({saved} registros)")
                del st.session_state["gen_result"]
                for _w in range(g_weeks):
                    _k = f"gen_editor_w{_w}_{g_start}"
                    if _k in st.session_state:
                        del st.session_state[_k]
                time_module.sleep(1.5)
                st.rerun()

        if st.session_state.get("_confirm_action") == "discard_generated":
            del st.session_state["_confirm_action"]
            del st.session_state["gen_result"]
            st.rerun()

        col_sv, col_disc = st.columns([3, 1])
        with col_sv:
            if st.button("💾 Salvar Escala Gerada", type="primary", use_container_width=True, key="btn_save_gen"):
                dlg_salvar_gerada()
        with col_disc:
            if st.button("🗑️ Descartar", use_container_width=True, key="btn_disc_gen"):
                dlg_descartar_gerada()


# ─── TAB: FERIADOS ────────────────────────────────────────────────────────────
with tab_feriados:

    FERIADOS_KEY = st.secrets.get("feriadosapi", {}).get("api_key", "")

    # Prioridade ao tipo mais específico quando há duplicatas por (data, nome)
    TYPE_PRIORITY = {"MUNICIPAL": 3, "ESTADUAL": 2, "NACIONAL": 1}
    TYPE_LABEL    = {"NACIONAL": "Nacional", "ESTADUAL": "Estadual", "MUNICIPAL": "Municipal"}

    today_h = date.today()
    col_year, col_btn, col_del = st.columns([1, 3, 1])
    with col_year:
        year_sel = st.selectbox(
            "Ano", options=list(range(today_h.year - 1, today_h.year + 3)),
            index=1, key="feriados_year"
        )
    with col_btn:
        if st.button("🔄 Buscar feriados da API (São Paulo)", use_container_width=True, type="primary"):
            if not FERIADOS_KEY:
                st.error("API key não configurada.")
            else:
                try:
                    with st.spinner("Consultando feriadosapi.com..."):
                        r = requests.get(
                            "https://feriadosapi.com/api/v1/feriados/cidade/3550308",
                            headers={"Authorization": f"Bearer {FERIADOS_KEY}"},
                            params={"ano": year_sel},
                            timeout=15,
                        )
                        r.raise_for_status()
                        raw = r.json().get("feriados", [])

                    # Deduplica por (data, nome) mantendo o tipo mais específico
                    seen: dict[tuple, dict] = {}
                    for h in raw:
                        h_date = date(int(h["data"][6:10]), int(h["data"][3:5]), int(h["data"][0:2]))
                        key = (h_date, h["nome"])
                        prioridade = TYPE_PRIORITY.get(h["tipo"], 0)
                        if key not in seen or prioridade > TYPE_PRIORITY.get(seen[key]["tipo"], 0):
                            seen[key] = {"date": h_date, "nome": h["nome"], "tipo": h["tipo"]}

                    inserted = 0
                    with db_cursor() as (conn, cur):
                        cur.execute("DELETE FROM holidays WHERE year = %s", (year_sel,))
                        for (h_date, h_nome), h in seen.items():
                            h_type = TYPE_LABEL.get(h["tipo"], "Nacional")
                            cur.execute("""
                                INSERT INTO holidays (holiday_date, name, holiday_type, year)
                                VALUES (%s, %s, %s, %s)
                            """, (h_date, h_nome, h_type, year_sel))
                            inserted += 1

                    st.success(f"{inserted} feriado(s) importado(s) para {year_sel} (Nacional + Estadual SP + Municipal SP).")
                    time_module.sleep(1)
                    st.rerun()
                except requests.exceptions.RequestException as e:
                    st.error(f"Erro ao consultar API: {e}")

    with col_del:
        if st.button("🗑️ Limpar ano", use_container_width=True):
            with db_cursor() as (conn, cur):
                cur.execute("DELETE FROM holidays WHERE year = %s", (year_sel,))
                deleted = cur.rowcount
            st.warning(f"{deleted} feriado(s) removido(s) de {year_sel}.")
            time_module.sleep(1)
            st.rerun()

    st.markdown("---")

    with db_cursor() as (_, cur):
        cur.execute("""
            SELECT holiday_date, name, holiday_type
            FROM holidays
            WHERE year = %s
            ORDER BY holiday_date
        """, (year_sel,))
        holidays_db = cur.fetchall()

    if not holidays_db:
        st.info(f"Nenhum feriado cadastrado para {year_sel}. Use o botão acima para importar da API.")
    else:
        TYPE_COLOR = {
            "Nacional":    "🟦",
            "Estadual":    "🟩",
            "Municipal":   "🟨",
            "Facultativo": "⬜",
        }
        df_h = pd.DataFrame([{
            "Data":    h["holiday_date"].strftime("%d/%m/%Y"),
            "Feriado": h["name"],
            "Tipo":    f"{TYPE_COLOR.get(h['holiday_type'], '⬛')} {h['holiday_type'] or '-'}",
        } for h in holidays_db])

        st.markdown(f"**{len(holidays_db)} feriado(s) em {year_sel}**")
        st.dataframe(df_h, use_container_width=True, hide_index=True)

        st.caption("🟦 Nacional  🟩 Estadual (SP)  🟨 Municipal (São Paulo)  ⬜ Facultativo (não obrigatório)")


# ─── TAB: REGRAS ──────────────────────────────────────────────────────────────
with tab_regras:

    st.markdown("## Regras da Escala")
    st.markdown("---")

    with st.expander("🔄 Ciclo de 3 Semanas", expanded=True):
        st.markdown("""
A escala segue um ciclo rotativo de **3 semanas** que se repete continuamente.

- O template define o padrão completo das 3 semanas, incluindo os domingos de folga de cada funcionário.
- Cada funcionário tem **exatamente 1 domingo de folga** dentro do ciclo de 3 semanas.
- O sistema detecta automaticamente em qual semana do ciclo cada calendário se encontra, comparando
  o padrão de domingos da escala real com o padrão definido no template.
- Não é necessário definir uma data de referência manualmente — a posição é calculada a partir do
  último domingo registrado na escala.
        """)

    with st.expander("📅 Domingo de Folga (Rotação)", expanded=True):
        st.markdown("""
A rotação de domingo funciona da seguinte forma dentro do ciclo de 3 semanas:

- **Semana em que o funcionário folga no domingo**: o domingo é marcado como folga no template.
- As outras 2 semanas do ciclo o funcionário trabalha no domingo.
- Cada funcionário tem sua semana de folga de domingo em uma semana diferente do ciclo,
  garantindo que sempre haja cobertura no domingo.
- O template deve refletir exatamente esse padrão — o sistema valida que nenhum funcionário
  tenha mais de 1 domingo de folga no ciclo.
        """)

    with st.expander("🏪 Regras de Cobertura da Loja", expanded=True):
        st.markdown(f"""
A loja opera nos seguintes horários e exige cobertura mínima:

| Dia | Abertura | Fechamento |
|---|---|---|
| Segunda a Sexta | {fmt(STORE_OPEN[0])} | {fmt(STORE_CLOSE[0])} |
| Sábado | {fmt(STORE_OPEN[5])} | {fmt(STORE_CLOSE[5])} |
| Domingo | {fmt(STORE_OPEN[6])} | {fmt(STORE_CLOSE[6])} |

**Regras de cobertura validadas automaticamente:**

- Sempre deve haver alguém com entrada **antes ou na hora da abertura** da loja.
- Sempre deve haver alguém com saída **depois ou na hora do fechamento** da loja.
- **Segunda a Sexta**: mínimo de **2 funcionários presentes** simultaneamente entre 12:30 e o fechamento.
- **Sábado e Domingo**: mínimo de **2 funcionários presentes** às {fmt(MIDDAY_CHECK)}.

Quando essas regras não são atendidas, avisos aparecem automaticamente nas abas de Semana,
Template e Geração Automática.
        """)

    with st.expander("📋 Template de 3 Semanas", expanded=False):
        st.markdown("""
O template define o padrão semanal padrão de cada funcionário para cada uma das 3 semanas do ciclo.

**Como preencher:**
- Digite a hora de entrada no formato `HH:MM` (ex: `10:00`) para dias de trabalho.
- Digite o tipo de folga para dias de descanso (ver tabela de tipos abaixo).
- Células vazias indicam que o funcionário não tem registro naquele dia.

**Regras do template:**
- Cada funcionário deve ter exatamente **1 domingo de folga** nas 3 semanas — o sistema bloqueia o salvamento se houver duplicatas.
- O template é aplicado automaticamente na aba **Semana** usando o botão "Preencher do Template", que identifica a semana correta do ciclo.
- Alterações no template não afetam semanas já salvas na escala.
        """)

    with st.expander("🤖 Geração Automática", expanded=False):
        st.markdown("""
A geração automática cria a escala aplicando o template ciclicamente a partir de uma data de início.

**Funcionamento:**
1. O sistema detecta a semana do ciclo correspondente à data de início, comparando o padrão de
   domingos da escala existente com o template.
2. Para cada semana gerada, aplica o template da semana do ciclo correspondente.
3. O ciclo avança automaticamente: semana 1 → semana 2 → semana 3 → semana 1 → ...

**Opções disponíveis:**
- **Início da geração**: data a partir da qual a escala será gerada (ajustada para segunda-feira).
- **Semanas**: quantidade de semanas a gerar (máximo 8).
- **Substituir registros existentes**: se marcado, sobrescreve semanas já salvas; caso contrário, mantém.

**Antes de salvar a prévia**, é possível editar qualquer célula diretamente no grid.
        """)

    with st.expander("🗂️ Tipos de Folga", expanded=False):
        st.markdown("""
Os seguintes tipos de folga podem ser digitados diretamente nas células do grid:

| Digite | Tipo | Descrição |
|---|---|---|
| `Folga` | DSR | Descanso Semanal Remunerado — folga obrigatória semanal |
| `Férias` | Férias | Férias anuais remuneradas |
| `Feriado` | Feriado | Feriado nacional, estadual ou municipal |
| `Atestado` | Atestado | Atestado médico |
| `BH` | Banco de Horas | Folga compensatória por banco de horas acumulado |
| `Licença` | Licença | Licença diversa (maternidade, paternidade, nojo, etc.) |
| `Dispensa` | Dispensa | Dispensa por baixo movimento — registrada para acompanhamento |

**Observação sobre Dispensa:** este tipo é registrado separadamente dos demais para permitir
o acompanhamento da frequência com que ocorre, auxiliando na análise de padrões de movimento da loja.

**Faltas:** não são registradas no template ou na escala — são detectadas automaticamente
pela comparação entre a escala prevista e os registros de ponto realizados.
        """)

    with st.expander("⚠️ Validações Automáticas", expanded=False):
        st.markdown("""
O sistema realiza as seguintes validações em tempo real:

**No Template:**
- Nenhum funcionário pode ter mais de 1 domingo de folga no ciclo de 3 semanas.
- O botão de salvar fica desabilitado enquanto houver violação dessa regra.

**Na Semana e na Geração:**
- Verificação de cobertura na abertura da loja.
- Verificação de cobertura no fechamento da loja.
- Verificação de mínimo de 2 pessoas no período crítico (12:30 até o fechamento de seg–sex; às 14:00 no fim de semana).
- Contagem de funcionários presentes por dia (indicador verde ≥ 2, vermelho < 2).

**Ao salvar:**
- Células com formato inválido (nem horário nem tipo de folga reconhecido) geram erro e impedem o salvamento.
        """)

    with st.expander("💡 Dicas de Uso", expanded=False):
        st.markdown("""
**Fluxo recomendado:**

1. **Configure o Template** (aba Template) com o padrão de 3 semanas de toda a equipe,
   incluindo os domingos de rotação de cada funcionário.
2. **Gere a escala** (aba Geração Automática) para as próximas semanas — o sistema detecta
   automaticamente a posição no ciclo e aplica o template correto.
3. **Ajuste manualmente** na aba Semana se necessário (feriados pontuais, trocas, dispensas).
4. **Acompanhe** na aba 4 Semanas a visão geral da escala vigente e futura.

**A posição no ciclo é sempre detectada automaticamente** — se o template estiver correto
e a escala tiver pelo menos um domingo registrado, o sistema encontra a semana certa
sem intervenção manual.
        """)

