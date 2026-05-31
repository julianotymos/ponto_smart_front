import streamlit as st
from utils.db import db_cursor
from datetime import date, timedelta
import pandas as pd

st.set_page_config(page_title="Relatorio de Ponto - Ponto Smart", layout="wide")
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


from utils.auth import require_login


require_login()

email = st.session_state["company_email"]

st.title("Relatorio de Ponto")
st.markdown("---")

# --- Filtros (compartilhados entre as abas) ---
col_de, col_ate, col_func = st.columns(3)

with col_de:
    data_de = st.date_input("De", value=date.today().replace(day=1))

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
    "email":        email,
    "date_from":    data_de.strftime("%Y-%m-%d"),
    "date_to":      data_ate.strftime("%Y-%m-%d"),
    "emp_id":       employee_id,   # 0 = todos
}
employee_filter = ""
if employee_id != 0:
    employee_filter = "AND a.employee = %(employee_id)s"
    params["employee_id"] = employee_id

st.markdown("---")

tab_resumo, tab_semanal, tab_diario = st.tabs(["📊 Resumo por Funcionário", "Horas por Semana", "Registros Diarios"])


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
                "horas_trabalhadas": "Horas Trab.",
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
                    "dias_trabalhados": "Dias Trab.",
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
          AND a.check_out_time IS NOT NULL
          AND a.check_out_time > a.check_in_time
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
                  AND a.check_out_time IS NOT NULL
                  AND a.check_out_time > a.check_in_time
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


# =============================================================================
# ABA: RESUMO POR FUNCIONÁRIO
# =============================================================================
with tab_resumo:
    query_resumo = """
    WITH emp AS (
        SELECT e.id, e.first_name || ' ' || e.last_name AS nome, e.weekly_workload
        FROM employee e
        JOIN company c ON c.id = e.company
        WHERE c.email = %(email)s AND e.status = 1
          AND (%(emp_id)s = 0 OR e.id = %(emp_id)s)
    ),
    dias_trab AS (
        SELECT a.employee, COUNT(DISTINCT a.work_day) AS total
        FROM attendance a
        JOIN emp ON emp.id = a.employee
        WHERE a.work_day BETWEEN DATE(%(date_from)s) AND DATE(%(date_to)s)
          AND a.status IN (1, 3)
          AND a.check_out_time IS NOT NULL
          AND a.check_out_time > a.check_in_time
        GROUP BY a.employee
    ),
    horas_trab AS (
        SELECT a.employee,
            SUM(a.check_out_time - a.check_in_time) AS total
        FROM attendance a
        JOIN emp ON emp.id = a.employee
        WHERE a.work_day BETWEEN DATE(%(date_from)s) AND DATE(%(date_to)s)
          AND a.status = 1
          AND a.check_out_time IS NOT NULL
          AND a.check_out_time > a.check_in_time
        GROUP BY a.employee
    ),
    horas_plan AS (
        SELECT s.employee,
            SUM(
                CASE
                    WHEN s.is_day_off = FALSE AND s.start_time IS NOT NULL AND s.end_time IS NOT NULL
                        THEN s.end_time - s.start_time - INTERVAL '1 hour'
                    WHEN s.day_off_type = 'dispensa'
                        THEN (emp.weekly_workload / 5.0) * INTERVAL '1 hour'
                    ELSE INTERVAL '0'
                END
            ) AS total
        FROM schedule s
        JOIN emp ON emp.id = s.employee
        WHERE s.work_date BETWEEN DATE(%(date_from)s) AND DATE(%(date_to)s)
          AND (
              (s.is_day_off = FALSE AND s.start_time IS NOT NULL AND s.end_time IS NOT NULL)
              OR s.day_off_type = 'dispensa'
          )
        GROUP BY s.employee
    ),
    domingos AS (
        SELECT a.employee, COUNT(DISTINCT a.work_day) AS total
        FROM attendance a
        JOIN emp ON emp.id = a.employee
        WHERE a.work_day BETWEEN DATE(%(date_from)s) AND DATE(%(date_to)s)
          AND a.status IN (1, 3)
          AND a.check_out_time IS NOT NULL
          AND a.check_out_time > a.check_in_time
          AND EXTRACT(DOW FROM a.work_day) = 0
        GROUP BY a.employee
    ),
    feriados_trab AS (
        SELECT a.employee, COUNT(DISTINCT a.work_day) AS total
        FROM attendance a
        JOIN emp ON emp.id = a.employee
        JOIN holidays h ON h.holiday_date = a.work_day
        WHERE a.work_day BETWEEN DATE(%(date_from)s) AND DATE(%(date_to)s)
          AND a.status IN (1, 3)
          AND a.check_out_time IS NOT NULL
          AND a.check_out_time > a.check_in_time
        GROUP BY a.employee
    ),
    horas_feriado AS (
        SELECT s.employee,
            SUM(
                CASE WHEN s.end_time IS NOT NULL AND s.start_time IS NOT NULL
                THEN EXTRACT(EPOCH FROM (s.end_time - s.start_time - INTERVAL '1 hour')) / 3600.0
                ELSE 0 END
            ) AS total_horas
        FROM schedule s
        JOIN emp ON emp.id = s.employee
        JOIN holidays h ON h.holiday_date = s.work_date
        WHERE s.work_date BETWEEN DATE(%(date_from)s) AND DATE(%(date_to)s)
          AND s.is_day_off = FALSE
          AND EXISTS (
              SELECT 1 FROM attendance a
              WHERE a.employee = s.employee
                AND a.work_day = s.work_date
                AND a.status IN (1, 3)
                AND a.check_out_time IS NOT NULL
                AND a.check_out_time > a.check_in_time
          )
        GROUP BY s.employee
    ),
    primeiro_checkin AS (
        SELECT employee, work_day, MIN(check_in_time)::time AS first_in
        FROM attendance
        WHERE status IN (1, 3)
        GROUP BY employee, work_day
    ),
    atrasos AS (
        SELECT s.employee, COUNT(*) AS total
        FROM schedule s
        JOIN emp ON emp.id = s.employee
        JOIN primeiro_checkin pc ON pc.employee = s.employee AND pc.work_day = s.work_date
        WHERE s.work_date BETWEEN DATE(%(date_from)s) AND DATE(%(date_to)s)
          AND s.is_day_off = FALSE
          AND s.start_time IS NOT NULL
          AND pc.first_in > (s.start_time + INTERVAL '10 minutes')
        GROUP BY s.employee
    ),
    faltas AS (
        SELECT s.employee, COUNT(*) AS total
        FROM schedule s
        JOIN emp ON emp.id = s.employee
        LEFT JOIN attendance a ON a.employee = s.employee
            AND a.work_day = s.work_date
            AND a.status IN (1, 3)
            AND a.check_out_time IS NOT NULL
            AND a.check_out_time > a.check_in_time
        WHERE s.work_date BETWEEN DATE(%(date_from)s) AND DATE(%(date_to)s)
          AND s.is_day_off = FALSE
          AND s.start_time IS NOT NULL
          AND a.id IS NULL
        GROUP BY s.employee
    ),
    ferias AS (
        SELECT s.employee, COUNT(*) AS total
        FROM schedule s
        JOIN emp ON emp.id = s.employee
        WHERE s.work_date BETWEEN DATE(%(date_from)s) AND DATE(%(date_to)s)
          AND s.day_off_type = 'ferias'
        GROUP BY s.employee
    ),
    dispensas AS (
        SELECT s.employee, COUNT(*) AS total
        FROM schedule s
        JOIN emp ON emp.id = s.employee
        WHERE s.work_date BETWEEN DATE(%(date_from)s) AND DATE(%(date_to)s)
          AND s.day_off_type = 'dispensa'
        GROUP BY s.employee
    )
    SELECT
        emp.nome                                        AS funcionario,
        COALESCE(dt.total,  0)                          AS dias_trabalhados,
        COALESCE(TO_CHAR(ht.total,  'HH24:MI'), '-')   AS horas_trabalhadas,
        COALESCE(TO_CHAR(hp.total,  'HH24:MI'), '-')   AS horas_planejadas,
        CASE
            WHEN ht.total IS NULL OR hp.total IS NULL THEN '-'
            WHEN ht.total >= hp.total
                THEN '+' || TO_CHAR(ht.total - hp.total, 'HH24:MI')
            ELSE
                '-' || TO_CHAR(hp.total - ht.total, 'HH24:MI')
        END                                             AS diferenca_horas,
        COALESCE(dom.total, 0)                          AS domingos_trabalhados,
        COALESCE(ft.total,  0)                          AS feriados_trabalhados,
        ROUND(COALESCE(hf.total_horas, 0)::numeric, 1) AS horas_em_feriado,
        COALESCE(at.total,  0)                          AS atrasos,
        COALESCE(fa.total,  0)                          AS faltas,
        COALESCE(fv.total,  0)                          AS ferias,
        COALESCE(disp.total, 0)                         AS dispensas
    FROM emp
    LEFT JOIN dias_trab      dt   ON dt.employee   = emp.id
    LEFT JOIN horas_trab     ht   ON ht.employee   = emp.id
    LEFT JOIN horas_plan     hp   ON hp.employee   = emp.id
    LEFT JOIN domingos       dom  ON dom.employee  = emp.id
    LEFT JOIN feriados_trab  ft   ON ft.employee   = emp.id
    LEFT JOIN horas_feriado  hf   ON hf.employee   = emp.id
    LEFT JOIN atrasos        at   ON at.employee   = emp.id
    LEFT JOIN faltas         fa   ON fa.employee   = emp.id
    LEFT JOIN ferias         fv   ON fv.employee   = emp.id
    LEFT JOIN dispensas      disp ON disp.employee = emp.id
    ORDER BY emp.nome
    """

    subtab_dados, subtab_explicativo = st.tabs(["📊 Dados", "📖 Explicativo"])

    with subtab_explicativo:
        st.markdown("## Campos e Regras do Resumo por Funcionário")
        st.markdown("---")

        with st.expander("📅 Dias Trabalhados", expanded=True):
            st.markdown("""
Conta os dias distintos em que o funcionário possui registro de ponto **válido** no período:
- Precisa ter **check-in E check-out** registrados
- O horário de saída deve ser **posterior** ao de entrada (`check_out > check_in`)
- Dias com registro zerado (`00:00 → 00:00`) **não contam**
- Inclui todos os dias: dias normais, domingos e feriados
            """)

        with st.expander("🕐 Horas Trabalhadas", expanded=True):
            st.markdown("""
Soma de `check_out_time − check_in_time` de todos os registros válidos no período:
- Inclui apenas registros com status **fechado** (check-out registrado e maior que check-in)
- Se o funcionário bateu ponto em intervalos separados (ex: entrada/saída do almoço), cada intervalo é somado individualmente — o almoço fica **excluído** naturalmente
- Inclui horas trabalhadas em **feriados e domingos**
            """)

        with st.expander("📋 Horas Planejadas", expanded=True):
            st.markdown("""
Soma das horas previstas na escala para o período, com as seguintes regras:

**Dias normais de trabalho** (`is_day_off = FALSE`, com horário definido):
- Usa `end_time − start_time − 1h` (desconta 1 hora de almoço embutida no turno)
- Ex: turno 11:00–21:00 → 9h na escala → **8h planejadas**

**Dias de Dispensa** (`day_off_type = 'dispensa'`):
- Usa a **carga horária padrão diária** do funcionário: `carga_semanal ÷ 5`
- Ex: funcionário de 40h/semana → **8h planejadas** por dia de dispensa
- Dispensa entra como planejada pois o funcionário teria trabalhado naquele dia

**Não entram nas horas planejadas:**
- Folgas (DSR), Férias, Feriados, Atestados, BH, Licenças
            """)

        with st.expander("⚖️ Saldo de Horas (trabalhadas − planejadas)", expanded=True):
            st.markdown("""
Resultado de `Horas Trabalhadas − Horas Planejadas`:
- **`+HH:MM`** → trabalhou **mais** que o planejado (horas extras ou trabalho em feriados/folgas)
- **`−HH:MM`** → trabalhou **menos** que o planejado (faltas, saídas antecipadas, dispensas sem reposição)

O **Saldo Total** no topo dos cartões soma todos os funcionários do filtro selecionado.
            """)

        with st.expander("🌞 Domingos Trabalhados", expanded=True):
            st.markdown("""
Conta os domingos com registro de ponto válido (check-out > check-in) no período.
Útil para acompanhar o revezamento de folgas de domingo e verificar se algum funcionário está trabalhando domingos além do previsto.
            """)

        with st.expander("🎉 Feriados Trabalhados", expanded=True):
            st.markdown("""
Conta os dias que são **feriados cadastrados** na aba de Feriados da Escala E o funcionário possui registro de ponto válido.
- Só conta feriados importados na base — se o feriado não estiver cadastrado, não é reconhecido
- Inclui feriados Nacionais, Estaduais (SP) e Municipais (São Paulo)
            """)

        with st.expander("⏱️ Horas em Feriado", expanded=True):
            st.markdown("""
Soma das horas do turno previsto em escala nos dias em que:
1. O dia é um feriado cadastrado
2. O funcionário **tem registro de ponto válido** naquele dia

Usa `end_time − start_time − 1h` da escala (horas planejadas menos almoço).
Permite saber quantas horas foram trabalhadas em datas de feriado para fins de compensação ou pagamento adicional.
            """)

        with st.expander("⚠️ Atrasos", expanded=True):
            st.markdown("""
Conta os dias em que o **primeiro check-in do dia** foi registrado mais de **10 minutos** após o horário de início previsto na escala:
- Compara `MIN(check_in_time)` do dia com `schedule.start_time + 10 minutos`
- Apenas dias em que há turno previsto na escala são considerados
- 1 atraso por dia, independente de quantos minutos de atraso
            """)

        with st.expander("❌ Faltas", expanded=True):
            st.markdown("""
Conta os dias em que o funcionário **estava escalado para trabalhar mas não tem registro de ponto válido**:
- O dia precisa ter `is_day_off = FALSE` e horário de início definido na escala
- Registros zerados (`00:00 → 00:00`) **não contam** como presença — o dia é considerado falta
- Dias de folga, férias, feriados, dispensas e atestados não entram na contagem
            """)

        with st.expander("🏖️ Férias (dias)", expanded=True):
            st.markdown("""
Conta os dias marcados como **Férias** na escala (`day_off_type = 'ferias'`) no período selecionado.
Não exige registro de ponto — basta estar previsto na escala como férias.
            """)

        with st.expander("💼 Dispensas (dias)", expanded=True):
            st.markdown("""
Conta os dias marcados como **Dispensa** na escala (`day_off_type = 'dispensa'`) no período:
- Dispensa é uma liberação dada pela gestão por baixo movimento ou outro motivo operacional
- O dia de dispensa **entra nas Horas Planejadas** com a carga horária padrão do funcionário
- Isso permite que o saldo reflita corretamente o impacto das dispensas no total de horas
- A coluna permite acompanhar a frequência com que dispensas são concedidas
            """)

    with subtab_dados:
        with db_cursor() as (_, cur):
            cur.execute(query_resumo, params)
            rows_resumo = cur.fetchall()

        if not rows_resumo:
            st.info("Nenhum dado encontrado para os filtros selecionados.")
        else:
            st.markdown(
                f"Período: **{data_de.strftime('%d/%m/%Y')}** a **{data_ate.strftime('%d/%m/%Y')}**"
            )

            df_r = pd.DataFrame([dict(r) for r in rows_resumo])

            st.dataframe(
            df_r.rename(columns={
                "funcionario":           "Funcionário",
                "dias_trabalhados":      "Dias Trab.",
                "horas_trabalhadas":     "Horas Trab.",
                "horas_planejadas":      "Horas Planejadas",
                "diferenca_horas":       "Diferença",
                "domingos_trabalhados":  "Domingos Trab.",
                "feriados_trabalhados":  "Feriados Trab.",
                "horas_em_feriado":      "Horas em Feriado",
                "atrasos":               "Atrasos",
                "faltas":                "Faltas",
                "ferias":                "Férias (dias)",
                "dispensas":             "Dispensas (dias)",
            }),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Dias Trab.":           st.column_config.NumberColumn(format="%d"),
                "Horas Trab.":          st.column_config.TextColumn(),
                "Horas Planejadas":     st.column_config.TextColumn(),
                "Diferença":            st.column_config.TextColumn(help="+ = trabalhou mais que o planejado  |  - = trabalhou menos"),
                "Domingos Trab.": st.column_config.NumberColumn(format="%d"),
                "Feriados Trab.": st.column_config.NumberColumn(format="%d"),
                "Horas em Feriado":     st.column_config.NumberColumn(format="%.1fh"),
                "Atrasos":              st.column_config.NumberColumn(format="%d"),
                "Faltas":               st.column_config.NumberColumn(format="%d"),
                "Férias (dias)":        st.column_config.NumberColumn(format="%d"),
                "Dispensas (dias)":     st.column_config.NumberColumn(format="%d"),
            },
            )
            st.caption("Diferença = Horas Trabalhadas − Horas Planejadas  |  Atraso: entrada > 10 min após o previsto na escala.")

            # ── Cartões por funcionário (layout para impressão) ──────────
            st.markdown("---")
            periodo_str = f"{data_de.strftime('%d/%m/%Y')} a {data_ate.strftime('%d/%m/%Y')}"

            def _diff_to_min(s: str) -> int:
                if not s or s == "-":
                    return 0
                sign = 1 if s.startswith("+") else -1
                h, m = s[1:].split(":")
                return sign * (int(h) * 60 + int(m))

            def _min_to_diff(total: int) -> str:
                sign = "+" if total >= 0 else "-"
                total = abs(total)
                return f"{sign}{total // 60:02d}:{total % 60:02d}"

            total_diff_min = sum(_diff_to_min(r["diferenca_horas"]) for r in rows_resumo)
            total_str = _min_to_diff(total_diff_min)
            label_total = "a mais" if total_diff_min >= 0 else "a menos"
            cor_total   = "green"  if total_diff_min >= 0 else "red"
            st.markdown(
                f"**Saldo total do período:** :{cor_total}[**{total_str}**] ({label_total})"
            )
            st.markdown("---")

            saldo_label = "Saldo de Horas (trabalhadas − planejadas)"
            for r in rows_resumo:
                diff_min = _diff_to_min(r["diferenca_horas"])
                diff_cor = "green" if diff_min >= 0 else "red"
                diff_str = f":{diff_cor}[**{r['diferenca_horas'] or '-'}**]"

                with st.container(border=True):
                    st.markdown(
                        f"**{r['funcionario']}** &nbsp;&nbsp;"
                        f"<span style='color:#888;font-size:0.85em'>Período: {periodo_str}</span>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"| | |\n|---|---|\n"
                        f"| Dias Trabalhados | **{r['dias_trabalhados']}** |\n"
                        f"| Horas Trabalhadas | **{r['horas_trabalhadas'] or '-'}** |\n"
                        f"| Horas Planejadas | **{r['horas_planejadas'] or '-'}** |\n"
                        f"| {saldo_label} | {diff_str} |\n"
                        f"| Domingos Trabalhados | **{r['domingos_trabalhados']}** |\n"
                        f"| Feriados Trabalhados | **{r['feriados_trabalhados']}** |\n"
                        f"| Horas em Feriado | **{r['horas_em_feriado']}h** |\n"
                        f"| Atrasos | **{r['atrasos']}** |\n"
                        f"| Faltas | **{r['faltas']}** |\n"
                        f"| Férias (dias) | **{r['ferias']}** |\n"
                        f"| Dispensas (dias) | **{r['dispensas']}** |"
                    )
