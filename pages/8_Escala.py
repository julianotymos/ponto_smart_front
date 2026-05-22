import streamlit as st
from utils.db import db_cursor
from datetime import date, timedelta, time as Time, datetime, timezone
import pandas as pd
import time as time_module
import re

st.set_page_config(page_title="Escala - Ponto Smart", layout="wide")
st.markdown("""
<style>
[data-testid="stStatusWidget"] { display: none !important; }
.block-container { padding-top: 1rem !important; }
h1 { margin-bottom: 0 !important; }
h2, h3 { margin-top: 0 !important; margin-bottom: 0.5rem !important; }
hr { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
header[data-testid="stHeader"] { height: 2.5rem !important; min-height: 2.5rem !important; }
</style>
""", unsafe_allow_html=True)

SYSTEM_USER = 1
DIAS_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

# Horário de funcionamento (dia_semana 0=Seg): (abertura, fechamento)
STORE_OPEN  = {0: Time(11,30), 1: Time(11,30), 2: Time(11,30),
               3: Time(11,30), 4: Time(11,30), 5: Time(11, 0), 6: Time(12, 0)}
STORE_CLOSE = {0: Time(21, 0), 1: Time(21, 0), 2: Time(21, 0),
               3: Time(21, 0), 4: Time(21, 0), 5: Time(21,30), 6: Time(21,30)}
MIDDAY_CHECK = Time(14, 0)


def require_login():
    if "company_email" not in st.session_state:
        st.warning("Acesse a página inicial e informe o email da empresa.")
        st.stop()


def parse_cell(cell):
    """Retorna (start_time, is_day_off). Aceita 'HH:MM' ou 'Folga' ou vazio."""
    v = str(cell).strip() if cell and not pd.isna(cell) else ""
    if not v:
        return None, False
    if v.upper() == "FOLGA":
        return None, True
    m = re.match(r"(\d{1,2}):(\d{2})$", v)
    if not m:
        return None, None  # None, None = formato inválido
    try:
        return Time(int(m[1]), int(m[2])), False
    except ValueError:
        return None, None


def calc_end(start: Time, shift_minutes: int) -> Time:
    """start_time + shift_minutes (já inclui intervalo)."""
    dt = datetime(2000, 1, 1, start.hour, start.minute) + timedelta(minutes=shift_minutes)
    return dt.time()


def shift_minutes(weekly_workload) -> int:
    """Minutos totais do turno = carga_semanal/5 + 1h de intervalo."""
    daily_h = float(weekly_workload or 40.0) / 5.0
    return int(daily_h * 60) + 60


def fmt(t: Time | None) -> str:
    return t.strftime("%H:%M") if t else ""


def cell_from_row(row) -> str:
    if row["is_day_off"]:
        return "Folga"
    if row["start_time"]:
        return fmt(row["start_time"])
    return ""


def count_presentes(df: pd.DataFrame, col_headers: list) -> pd.DataFrame:
    """Retorna DataFrame de 1 linha com contagem de pessoas trabalhando por dia."""
    counts = {}
    for h in col_headers:
        n = 0
        for name in df.index:
            cell = str(df.at[name, h]).strip()
            cell_norm = cell.replace("🔄 ", "")
            if cell_norm and cell_norm.upper() != "FOLGA":
                st_t, _ = parse_cell(cell_norm)
                if st_t is not None:
                    n += 1
        counts[h] = n
    return pd.DataFrame([counts], index=["👥 Presentes"])


def style_presentes(df_count: pd.DataFrame) -> object:
    """Aplica cor verde (≥2) ou vermelha (<2) na linha de contagem."""
    def color(val):
        return "background-color:#d4edda;color:#155724;font-weight:bold" if val >= 2 \
               else "background-color:#f8d7da;color:#721c24;font-weight:bold"
    return df_count.style.applymap(color)


def validate_grid(df: pd.DataFrame, col_headers: list, emp_shift: dict[str, int]) -> list[str]:
    msgs = []
    for i, col in enumerate(col_headers):
        dow = i % 7
        open_t  = STORE_OPEN[dow]
        close_t = STORE_CLOSE[dow]
        day_label = col.split("\n")[0]

        intervals = []
        for name in df.index:
            raw = df.at[name, col]
            st_t, is_off = parse_cell(raw)
            if is_off or st_t is None:
                continue
            en_t = calc_end(st_t, emp_shift.get(name, 540))
            intervals.append((st_t, en_t))

        if not any(s <= open_t for s, _ in intervals):
            msgs.append(f"**{day_label}** — ninguém cobre a abertura ({fmt(open_t)})")
        if not any(e >= close_t for _, e in intervals):
            msgs.append(f"**{day_label}** — ninguém cobre o fechamento ({fmt(close_t)})")

        if dow <= 4:  # Seg–Sex: mínimo 2 pessoas simultâneas de 12:30 até o fechamento
            WIN = Time(12, 30)
            # Pontos críticos = início/fim de cada turno dentro da janela + 12:30
            critical = sorted({WIN} | {
                t for s, e in intervals for t in (s, e)
                if WIN <= t <= close_t
            })
            min_n, min_t = None, None
            for t in critical:
                if t >= close_t:
                    break
                n = sum(1 for s, e in intervals if s <= t < e)
                if min_n is None or n < min_n:
                    min_n, min_t = n, t
            if min_n is not None and min_n < 2:
                msgs.append(
                    f"**{day_label}** — apenas {min_n} pessoa(s) às {fmt(min_t)} "
                    f"(mínimo 2 entre 12:30–{fmt(close_t)})"
                )
        else:  # Sáb/Dom: pelo menos 2 às 14:00
            midday = sum(1 for s, e in intervals if s <= MIDDAY_CHECK <= e)
            if midday < 2:
                msgs.append(f"**{day_label}** — menos de 2 pessoas às {fmt(MIDDAY_CHECK)} ({midday})")

    return msgs


require_login()
company_id = st.session_state["company_id"]

st.title("📅 Escala de Trabalho")
st.markdown("---")

# Carrega funcionários ativos com carga horária
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
emp_wl       = {e["name"]: e["weekly_workload"] for e in employees}       # horas/semana
emp_shift    = {e["name"]: shift_minutes(e["weekly_workload"]) for e in employees}  # min/dia
emp_wl_by_id = {e["id"]: e["weekly_workload"] for e in employees}

tab_semana, tab_template, tab_geracao, tab_visao = st.tabs(["📅 Semana", "📋 Template", "🤖 Geração Automática", "🗓️ 4 Semanas"])


# ─── TAB: SEMANA ──────────────────────────────────────────────────────────────
with tab_semana:
    today = date.today()
    if "escala_week_start" not in st.session_state:
        st.session_state["escala_week_start"] = today - timedelta(days=today.weekday())

    week_start: date = st.session_state["escala_week_start"]
    week_end   = week_start + timedelta(days=6)

    col_prev, col_lbl, col_next = st.columns([1, 5, 1])
    with col_prev:
        if st.button("◀ Anterior", use_container_width=True, key="prev_week"):
            st.session_state["escala_week_start"] -= timedelta(weeks=1)
            st.rerun()
    with col_lbl:
        st.markdown(
            f"<h3 style='text-align:center;margin:0;padding:4px'>"
            f"{week_start.strftime('%d/%m/%Y')} – {week_end.strftime('%d/%m/%Y')}"
            f"</h3>",
            unsafe_allow_html=True,
        )
    with col_next:
        if st.button("Próxima ▶", use_container_width=True, key="next_week"):
            st.session_state["escala_week_start"] += timedelta(weeks=1)
            st.rerun()

    dates    = [week_start + timedelta(days=i) for i in range(7)]
    col_hdrs = [f"{DIAS_PT[i]}\n{d.strftime('%d/%m')}" for i, d in enumerate(dates)]

    # Carrega escala do banco para a semana
    with db_cursor() as (_, cur):
        cur.execute("""
            SELECT employee, work_date, start_time, end_time, is_day_off
            FROM schedule
            WHERE company = %s AND work_date BETWEEN %s AND %s
        """, (company_id, week_start, week_end))
        db_rows = cur.fetchall()

    sched_map = {(r["employee"], r["work_date"]): cell_from_row(r) for r in db_rows}

    df_week = pd.DataFrame(
        {h: [sched_map.get((eid, d), "") for eid in emp_ids] for h, d in zip(col_hdrs, dates)},
        index=emp_names,
    )

    # Botão preencher do template
    col_btn_tmpl, _ = st.columns([2, 5])
    with col_btn_tmpl:
        if st.button("📋 Preencher do Template", key="fill_from_tmpl"):
            with db_cursor() as (_, cur):
                cur.execute("""
                    SELECT employee, day_of_week, start_time, is_day_off
                    FROM schedule_template
                    WHERE company = %s
                """, (company_id,))
                tmpl = {(r["employee"], r["day_of_week"]): cell_from_row(r) for r in cur.fetchall()}

            with db_cursor() as (conn, cur):
                for eid in emp_ids:
                    wl = emp_wl_by_id.get(eid)
                    shift_min = shift_minutes(wl)
                    for i, d in enumerate(dates):
                        cell = tmpl.get((eid, i % 7), "")
                        if not cell:
                            continue
                        st_t, is_off = parse_cell(cell)
                        en_t = calc_end(st_t, shift_min) if st_t else None
                        cur.execute("""
                            INSERT INTO schedule (employee, company, work_date, start_time, end_time, is_day_off, system_user)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (employee, work_date) DO NOTHING
                        """, (eid, company_id, d, st_t, en_t, is_off, SYSTEM_USER))
            for _k in [f"week_editor_{week_start}", f"wk_emp_{week_start}"]:
                if _k in st.session_state:
                    del st.session_state[_k]
            st.success("Template aplicado à semana (células existentes não foram substituídas).")
            time_module.sleep(1.5)
            st.rerun()

    # Legenda de carga por funcionário
    with st.expander("ℹ️ Carga horária por funcionário", expanded=False):
        rows_leg = []
        for name in emp_names:
            wl = float(emp_wl.get(name) or 40.0)
            daily = wl / 5.0
            total_min = shift_minutes(emp_wl.get(name))
            rows_leg.append({"Funcionário": name, "Carga Semanal (h)": wl,
                             "Horas/dia": f"{daily:.1f}h", "Turno (c/ 1h intervalo)": f"{int(total_min // 60)}h{int(total_min % 60):02d}min"})
        st.dataframe(pd.DataFrame(rows_leg).set_index("Funcionário"), use_container_width=True)

    st.caption("Digite a hora de **entrada** no formato **HH:MM** (ex: `10:00`) ou **Folga**. A saída é calculada automaticamente.")

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

    # Validação em tempo real
    warnings = validate_grid(edited, col_hdrs, emp_shift)
    if warnings:
        with st.expander(f"⚠️ {len(warnings)} aviso(s) de cobertura", expanded=True):
            for w in warnings:
                st.markdown(f"- {w}")
    else:
        st.success("✅ Cobertura completa para a semana.")

    st.markdown("")
    if st.button("💾 Salvar Escala", type="primary", use_container_width=True, key="save_week"):
        errs = []
        count = 0
        with db_cursor() as (conn, cur):
            for name in emp_names:
                eid = emp_by_name[name]
                shift_min = emp_shift[name]
                for h, d in zip(col_hdrs, dates):
                    raw = edited.at[name, h]
                    cell = str(raw).strip() if raw and not pd.isna(raw) else ""
                    if not cell:
                        cur.execute("DELETE FROM schedule WHERE employee=%s AND work_date=%s", (eid, d))
                        continue
                    st_t, is_off = parse_cell(cell)
                    if not is_off and st_t is None:
                        errs.append(f"**{name}** / {h}: formato inválido `{cell}` — use HH:MM ou Folga")
                        continue
                    en_t = calc_end(st_t, shift_min) if st_t else None
                    cur.execute("""
                        INSERT INTO schedule (employee, company, work_date, start_time, end_time, is_day_off, system_user)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (employee, work_date) DO UPDATE SET
                            start_time  = EXCLUDED.start_time,
                            end_time    = EXCLUDED.end_time,
                            is_day_off  = EXCLUDED.is_day_off,
                            update_date = NOW(),
                            system_user = EXCLUDED.system_user
                    """, (eid, company_id, d, st_t, en_t, is_off, SYSTEM_USER))
                    count += 1
        if errs:
            for e in errs:
                st.error(e)
        else:
            st.success(f"Escala salva! ({count} registros atualizados)")
            _wk_key = f"week_editor_{week_start}"
            if _wk_key in st.session_state:
                del st.session_state[_wk_key]
            time_module.sleep(1.5)
            st.rerun()

    # ── Exclusão da semana ────────────────────────────────────────────────────
    with st.expander("🗑️ Excluir escala desta semana", expanded=False):
        st.warning(
            f"Remove **todos** os registros de escala da semana "
            f"**{week_start.strftime('%d/%m/%Y')} – {week_end.strftime('%d/%m/%Y')}** para todos os funcionários."
        )
        col_del, col_conf = st.columns([2, 1])
        with col_del:
            confirmar_del = st.text_input(
                "Digite **CONFIRMAR** para liberar o botão", key="confirm_del_week", placeholder="CONFIRMAR"
            )
        with col_conf:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🗑️ Excluir semana", type="secondary", use_container_width=True,
                         key="btn_del_week", disabled=(confirmar_del.strip().upper() != "CONFIRMAR")):
                with db_cursor() as (conn, cur):
                    cur.execute(
                        "DELETE FROM schedule WHERE company=%s AND work_date BETWEEN %s AND %s",
                        (company_id, week_start, week_end),
                    )
                    deleted = cur.rowcount
                st.success(f"{deleted} registros excluídos.")
                _wk_key = f"week_editor_{week_start}"
                if _wk_key in st.session_state:
                    del st.session_state[_wk_key]
                time_module.sleep(1.5)
                st.rerun()


# ─── TAB: TEMPLATE ────────────────────────────────────────────────────────────
with tab_template:
    st.caption(
        "Define o padrão semanal de cada funcionário. "
        "Use **Preencher do Template** na aba Semana para aplicar automaticamente."
    )

    with db_cursor() as (_, cur):
        cur.execute("""
            SELECT employee, day_of_week, start_time, end_time, is_day_off
            FROM schedule_template
            WHERE company = %s
        """, (company_id,))
        tmpl_rows = cur.fetchall()

    tmpl_map = {(r["employee"], r["day_of_week"]): cell_from_row(r) for r in tmpl_rows}

    df_tmpl = pd.DataFrame(
        {dia: [tmpl_map.get((eid, i), "") for eid in emp_ids] for i, dia in enumerate(DIAS_PT)},
        index=emp_names,
    )

    st.caption("Digite apenas a hora de **entrada** (ex: `10:00`) ou **Folga**.")

    edited_tmpl = st.data_editor(
        df_tmpl,
        use_container_width=True,
        num_rows="fixed",
        key="tmpl_editor",
        column_config={dia: st.column_config.TextColumn(dia, width="small") for dia in DIAS_PT},
    )

    warnings_tmpl = validate_grid(edited_tmpl, DIAS_PT, emp_shift)
    if warnings_tmpl:
        with st.expander(f"⚠️ {len(warnings_tmpl)} aviso(s) no template", expanded=False):
            for w in warnings_tmpl:
                st.markdown(f"- {w}")
    else:
        st.success("✅ Cobertura completa no template.")

    st.markdown("")
    if st.button("💾 Salvar Template", type="primary", use_container_width=True, key="save_tmpl"):
        errs = []
        count = 0
        with db_cursor() as (conn, cur):
            for name in emp_names:
                eid = emp_by_name[name]
                shift_min = emp_shift[name]
                for i, dia in enumerate(DIAS_PT):
                    raw = edited_tmpl.at[name, dia]
                    cell = str(raw).strip() if raw and not pd.isna(raw) else ""
                    if not cell:
                        cur.execute(
                            "DELETE FROM schedule_template WHERE employee=%s AND company=%s AND day_of_week=%s",
                            (eid, company_id, i),
                        )
                        continue
                    st_t, is_off = parse_cell(cell)
                    if not is_off and st_t is None:
                        errs.append(f"**{name}** / {dia}: formato inválido `{cell}`")
                        continue
                    en_t = calc_end(st_t, shift_min) if st_t else None
                    cur.execute("""
                        INSERT INTO schedule_template (employee, company, day_of_week, start_time, end_time, is_day_off, system_user)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (employee, day_of_week) DO UPDATE SET
                            start_time  = EXCLUDED.start_time,
                            end_time    = EXCLUDED.end_time,
                            is_day_off  = EXCLUDED.is_day_off,
                            update_date = NOW(),
                            system_user = EXCLUDED.system_user
                    """, (eid, company_id, i, st_t, en_t, is_off, SYSTEM_USER))
                    count += 1
        if errs:
            for e in errs:
                st.error(e)
        else:
            st.success(f"Template salvo! ({count} registros)")
            time_module.sleep(1.5)
            st.rerun()


# ─── TAB: GERAÇÃO AUTOMÁTICA ──────────────────────────────────────────────────
with tab_geracao:
    today_ref = date.today()

    st.caption(
        "Gera a escala com base no padrão de folgas de cada funcionário e na rotação de domingo "
        "(a cada 3 domingos: trabalha, trabalha, folga)."
    )

    # ── Detecta data de início ────────────────────────────────────────────────
    with db_cursor() as (_, cur):
        cur.execute("SELECT MAX(work_date) AS last_date FROM schedule WHERE company = %s", (company_id,))
        row_last = cur.fetchone()

    last_scheduled = row_last["last_date"] if row_last and row_last["last_date"] else None

    if last_scheduled:
        raw_next = last_scheduled + timedelta(days=1)
        auto_start = raw_next - timedelta(days=raw_next.weekday())  # ajusta para segunda
        st.info(f"Escala existente até **{last_scheduled.strftime('%d/%m/%Y')}**. Início sugerido: **{auto_start.strftime('%d/%m/%Y')}**.")
    else:
        auto_start = today_ref + timedelta(days=(7 - today_ref.weekday()) % 7 or 7)
        st.info("Nenhuma escala encontrada. Início sugerido: próxima semana.")

    col_a, col_b, col_c = st.columns([2, 1, 2])
    with col_a:
        gen_start_input = st.date_input("Início da geração", value=auto_start, key="gen_start")
        gen_start_adj   = gen_start_input - timedelta(days=gen_start_input.weekday())
        if gen_start_adj != gen_start_input:
            st.caption(f"Ajustado para segunda-feira: {gen_start_adj.strftime('%d/%m/%Y')}")
    with col_b:
        num_weeks_gen = int(st.number_input("Semanas", min_value=1, max_value=8, value=4, key="gen_weeks"))
    with col_c:
        folga_sabado = st.checkbox("Dar sábado de folga junto com domingo de rotação", value=True, key="gen_sat")

    # ── Rotação: último domingo de folga por funcionário ──────────────────────
    st.markdown("---")

    # Auto-detecção: último domingo com is_day_off=TRUE no banco
    with db_cursor() as (_, cur):
        cur.execute("""
            SELECT employee, MAX(work_date) AS last_off_sunday
            FROM schedule
            WHERE company = %s
              AND EXTRACT(DOW FROM work_date) = 0
              AND is_day_off = TRUE
            GROUP BY employee
        """, (company_id,))
        off_sunday_rows = cur.fetchall()

    detected_last_off = {r["employee"]: r["last_off_sunday"] for r in off_sunday_rows}

    df_rotation = pd.DataFrame([
        {"Funcionário": name, "Último domingo de folga de rotação": detected_last_off.get(eid)}
        for name, eid in zip(emp_names, emp_ids)
    ]).set_index("Funcionário")

    with st.expander("🔄 Rotação de domingo — clique para revisar / editar", expanded=False):
        st.caption(
            "Informe o **último domingo em que cada funcionário teve folga de rotação**. "
            "Ciclo: trabalha → trabalha → **folga** (a cada 3 domingos). "
            "Deixe em branco para quem não trabalha domingo."
        )
        edited_rotation = st.data_editor(
            df_rotation,
            column_config={
                "Último domingo de folga de rotação": st.column_config.DateColumn(
                    "Último domingo de folga de rotação", format="DD/MM/YYYY"
                )
            },
            use_container_width=True,
            key="rotation_editor",
        )

    # ── Gerar ────────────────────────────────────────────────────────────────
    st.markdown("")
    if st.button("⚡ Gerar Escala", type="primary", use_container_width=True, key="btn_gerar"):
        with db_cursor() as (_, cur):
            cur.execute("""
                SELECT employee, day_of_week, start_time, is_day_off
                FROM schedule_template WHERE company = %s
            """, (company_id,))
            tmpl_rows = cur.fetchall()

        if not tmpl_rows:
            st.error("Nenhum template configurado. Preencha a aba Template antes de gerar.")
            st.stop()

        tmpl_map = {(r["employee"], r["day_of_week"]): r for r in tmpl_rows}

        # Coleta último domingo de folga editado pelo usuário
        last_sunday_off: dict[int, date | None] = {}
        for name, eid in zip(emp_names, emp_ids):
            val = edited_rotation.at[name, "Último domingo de folga de rotação"]
            last_sunday_off[eid] = val if val and not pd.isna(val) else None

        # Para funcionários sem histórico de folga: usa o domingo anterior ao início
        # → trabalha 2 domingos, depois folga (ciclo começa em posição 1)
        default_ref = gen_start_adj - timedelta(days=1)  # domingo imediatamente antes
        for eid in emp_ids:
            if last_sunday_off[eid] is None:
                last_sunday_off[eid] = default_ref

        # Folgas regulares vêm direto do template (is_day_off=TRUE)
        emp_days_off: dict[int, set] = {
            eid: {dow for dow in range(7) if tmpl_map.get((eid, dow), {}).get("is_day_off")}
            for eid in emp_ids
        }

        # ── Geração semana a semana ───────────────────────────────────────────
        # Regra de domingo: semanas_desde_ultima_folga % 3 == 0 → folga de rotação
        # Após semana de rotação (Sáb+Dom off): semana seguinte folga Seg+Ter
        generated: dict[tuple, dict] = {}
        lso = dict(last_sunday_off)  # cópia mutável por funcionário

        # Verifica se o domingo imediatamente antes do início foi rotação
        # (para que a primeira semana gerada já receba Seg+Ter de folga se necessário)
        sunday_before = gen_start_adj - timedelta(days=1)  # domingo anterior
        with db_cursor() as (_, cur):
            cur.execute("""
                SELECT employee FROM schedule
                WHERE company = %s AND work_date = %s AND is_day_off = TRUE
            """, (company_id, sunday_before))
            post_rotation: set[int] = {r["employee"] for r in cur.fetchall()} & set(emp_ids)

        for w in range(num_weeks_gen):
            wk_start = gen_start_adj + timedelta(weeks=w)
            wk_dates = [wk_start + timedelta(days=d) for d in range(7)]
            sunday   = wk_dates[6]
            rotation_this_week: set[int] = set()

            for eid in emp_ids:
                ref = lso[eid]
                weeks_since = (sunday - ref).days // 7 if ref else 0
                rotation_dom = (weeks_since > 0 and weeks_since % 3 == 0)

                if rotation_dom:
                    days_off_wk = {5, 6} if folga_sabado else {6}
                    lso[eid] = sunday
                    rotation_this_week.add(eid)
                elif eid in post_rotation:
                    # Semana seguinte à rotação: folga Seg+Ter
                    days_off_wk = {0, 1}
                else:
                    days_off_wk = emp_days_off.get(eid, set())

                for i, d in enumerate(wk_dates):
                    dow = i
                    if dow in days_off_wk:
                        if rotation_dom:
                            reason = "rotação" if dow == 6 else "sáb-rotação"
                        elif eid in post_rotation:
                            reason = "pós-rotação"
                        else:
                            reason = None
                        generated[(eid, d)] = {"start_time": None, "is_day_off": True, "reason": reason}
                    else:
                        tmpl = tmpl_map.get((eid, dow))
                        generated[(eid, d)] = {
                            "start_time": tmpl["start_time"] if tmpl else None,
                            "is_day_off": False,
                            "reason": None,
                        }

            post_rotation = rotation_this_week  # próxima semana sabe quem veio de rotação

        st.session_state["gen_result"]    = generated
        st.session_state["gen_start_adj"] = gen_start_adj
        st.session_state["gen_num_weeks"] = num_weeks_gen
        st.rerun()

    # ── Prévia ────────────────────────────────────────────────────────────────
    if "gen_result" in st.session_state:
        generated     = st.session_state["gen_result"]
        g_start       = st.session_state["gen_start_adj"]
        g_weeks       = st.session_state["gen_num_weeks"]

        st.markdown("---")
        st.subheader("Prévia da Escala Gerada")
        st.caption(
            "🔄 = folga por rotação  |  Edite direto nas células antes de salvar. "
            "Use **HH:MM** para horário de entrada, **Folga** para folga, vazio para remover."
        )

        total_warnings = 0
        edited_weeks: dict[int, tuple[pd.DataFrame, list, list]] = {}  # w → (df_edited, wk_hdrs, wk_dates)

        for w in range(g_weeks):
            wk_start = g_start + timedelta(weeks=w)
            wk_dates = [wk_start + timedelta(days=d) for d in range(7)]
            wk_hdrs  = [f"{DIAS_PT[d]}\n{dt.strftime('%d/%m')}" for d, dt in enumerate(wk_dates)]

            preview_data: dict[str, list] = {h: [] for h in wk_hdrs}
            for h, d in zip(wk_hdrs, wk_dates):
                for eid in emp_ids:
                    entry = generated.get((eid, d))
                    if entry is None:
                        preview_data[h].append("")
                    elif entry["is_day_off"]:
                        preview_data[h].append("🔄 Folga" if entry.get("reason") else "Folga")
                    elif entry["start_time"]:
                        preview_data[h].append(fmt(entry["start_time"]))
                    else:
                        preview_data[h].append("")

            df_prev = pd.DataFrame(preview_data, index=emp_names)

            label = f"Semana {w+1} — {wk_start.strftime('%d/%m')} a {(wk_start + timedelta(days=6)).strftime('%d/%m/%Y')}"
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
                _parts_g = []
                for _h in wk_hdrs:
                    _day = _h.split("\n")[0]
                    _n = int(_row_cnt_g[_h])
                    _clr = "green" if _n >= 2 else "red"
                    _parts_g.append(f"{_day} :{_clr}[**{_n}**]")
                st.caption("👥 Presentes — " + "  ·  ".join(_parts_g))

                # Validações dinâmicas — recalculadas a cada edição
                df_val = df_edited.replace("🔄 Folga", "Folga")
                warns  = validate_grid(df_val, wk_hdrs, emp_shift)

                folga_warns = []
                for name in emp_names:
                    n_folgas = sum(
                        1 for h in wk_hdrs
                        if str(df_edited.at[name, h]).strip().upper() in ("FOLGA", "🔄 FOLGA")
                    )
                    if n_folgas != 2:
                        folga_warns.append(f"**{name}** — {n_folgas} folga(s) (esperado: 2)")

                total_warnings += len(warns) + len(folga_warns)

                if folga_warns or warns:
                    st.markdown("---")
                    for fw in folga_warns:
                        st.markdown(f"- 🔴 {fw}")
                    for wm in warns:
                        st.markdown(f"- ⚠️ {wm}")

        st.markdown("")
        overwrite = st.checkbox("Substituir registros já existentes no período", value=False, key="gen_overwrite")

        col_sv, col_disc = st.columns([3, 1])
        with col_sv:
            if st.button("💾 Salvar Escala Gerada", type="primary", use_container_width=True, key="btn_save_gen"):
                saved = 0
                errs  = []
                with db_cursor() as (conn, cur):
                    for w, (df_ed, wk_hdrs, wk_dates) in edited_weeks.items():
                        for name in emp_names:
                            eid       = emp_by_name[name]
                            shift_min = emp_shift.get(name, 540)
                            for h, d in zip(wk_hdrs, wk_dates):
                                raw  = df_ed.at[name, h]
                                cell = str(raw).strip() if raw and not pd.isna(raw) else ""
                                # Normaliza marcador de rotação
                                cell_norm = cell.replace("🔄 ", "")
                                if not cell_norm:
                                    continue
                                is_off = cell_norm.upper() == "FOLGA"
                                st_t, _ = parse_cell(cell_norm) if not is_off else (None, True)
                                if not is_off and st_t is None:
                                    errs.append(f"**{name}** / {h}: formato inválido `{cell}`")
                                    continue
                                en_t = calc_end(st_t, shift_min) if st_t else None
                                if overwrite:
                                    cur.execute("""
                                        INSERT INTO schedule (employee, company, work_date, start_time, end_time, is_day_off, system_user)
                                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                                        ON CONFLICT (employee, work_date) DO UPDATE SET
                                            start_time=EXCLUDED.start_time, end_time=EXCLUDED.end_time,
                                            is_day_off=EXCLUDED.is_day_off, update_date=NOW(),
                                            system_user=EXCLUDED.system_user
                                    """, (eid, company_id, d, st_t, en_t, is_off, SYSTEM_USER))
                                else:
                                    cur.execute("""
                                        INSERT INTO schedule (employee, company, work_date, start_time, end_time, is_day_off, system_user)
                                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                                        ON CONFLICT (employee, work_date) DO NOTHING
                                    """, (eid, company_id, d, st_t, en_t, is_off, SYSTEM_USER))
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
        with col_disc:
            if st.button("🗑️ Descartar", use_container_width=True, key="btn_disc_gen"):
                del st.session_state["gen_result"]
                st.rerun()


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
            SELECT employee, work_date, start_time, end_time, is_day_off
            FROM schedule
            WHERE company = %s AND work_date BETWEEN %s AND %s
            ORDER BY work_date
        """, (company_id, view_start, view_end))
        all_rows = cur.fetchall()

    all_map = {(r["employee"], r["work_date"]): cell_from_row(r) for r in all_rows}

    for w in range(4):
        wk_start = view_start + timedelta(weeks=w)
        wk_dates = [wk_start + timedelta(days=d) for d in range(7)]
        wk_hdrs  = [f"{DIAS_PT[d]}\n{dt.strftime('%d/%m')}" for d, dt in enumerate(wk_dates)]

        df_wk = pd.DataFrame(
            {h: [all_map.get((eid, d), "") for eid in emp_ids] for h, d in zip(wk_hdrs, wk_dates)},
            index=emp_names,
        )

        is_current = wk_start == (today - timedelta(days=today.weekday()))
        label = f"Semana {w + 1} — {wk_start.strftime('%d/%m')} a {(wk_start + timedelta(days=6)).strftime('%d/%m/%Y')}"
        if is_current:
            label += "  *(semana atual)*"

        with st.expander(label, expanded=(w == 0)):
            wk_warns = validate_grid(df_wk, wk_hdrs, emp_shift)
            if wk_warns:
                st.markdown(f"⚠️ {len(wk_warns)} aviso(s) de cobertura")
            st.dataframe(df_wk, use_container_width=True)
