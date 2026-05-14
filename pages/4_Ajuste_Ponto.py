import streamlit as st
import pandas as pd
from utils.db import db_cursor
from datetime import date, datetime, time, timedelta

st.set_page_config(page_title="Ajuste de Ponto - Ponto Smart", layout="wide")
st.markdown("""
<style>
[data-testid="stStatusWidget"] { display: none !important; }
.block-container { padding-top: 1rem !important; }
@media (min-width: 768px) { .block-container { padding-top: 0.5rem !important; } }
h1, h2, h3 { margin-bottom: 0.5rem !important; }
hr { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
header[data-testid="stHeader"] { position: relative; overflow: hidden; }
header[data-testid="stHeader"]::after {
    content: "Ponto Smart";
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    font-size: 1rem;
    font-weight: 600;
}
</style>
""", unsafe_allow_html=True)


def require_login():
    if "company_email" not in st.session_state:
        st.warning("Acesse a pagina inicial e informe o email da empresa.")
        st.stop()


require_login()

email = st.session_state["company_email"]

st.title("Ajuste Manual de Ponto")
st.markdown("---")

tab_registros, tab_alertas = st.tabs(["Registros do Periodo", "Alertas  +10h"])


# =============================================================================
# ABA: REGISTROS DO PERIODO
# =============================================================================
with tab_registros:

    # --- Grid de funcionarios ---
    with db_cursor() as (_, cur):
        cur.execute(
            """
            SELECT e.id,
                   e.employee_code               AS codigo,
                   e.first_name || ' ' || e.last_name AS nome,
                   COALESCE(e.position, '-')     AS cargo,
                   COALESCE(e.phone_number, '-') AS telefone,
                   e.email
            FROM employee e
            JOIN company c ON c.id = e.company
            WHERE c.email = %s AND e.status = 1
            ORDER BY e.first_name ASC
            """,
            (email,),
        )
        funcionarios = cur.fetchall()

    if not funcionarios:
        st.info("Nenhum funcionario ativo encontrado.")
        st.stop()

    df_func = pd.DataFrame([dict(r) for r in funcionarios])
    ids_func = df_func["id"].tolist()

    st.markdown("Selecione o funcionario:")
    ev_func = st.dataframe(
        df_func.drop(columns=["id"]),
        use_container_width=True,
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        key="sel_func_reg",
        column_config={
            "codigo":   st.column_config.TextColumn("Codigo"),
            "nome":     st.column_config.TextColumn("Nome"),
            "cargo":    st.column_config.TextColumn("Cargo"),
            "telefone": st.column_config.TextColumn("Telefone"),
            "email":    st.column_config.TextColumn("Email"),
        },
    )

    sel_reg = ev_func.selection.rows
    if not sel_reg:
        st.info("Selecione um funcionario para ver os registros.")
        st.stop()

    func_id   = ids_func[sel_reg[0]]
    func_nome = df_func.iloc[sel_reg[0]]["nome"]

    st.markdown("---")
    st.subheader(f"Registros de {func_nome}")

    col_de, col_ate, _ = st.columns([1, 1, 2])
    with col_de:
        data_de = st.date_input("De", value=date.today() - timedelta(days=7), key="reg_de")
    with col_ate:
        data_ate = st.date_input("Ate", value=date.today(), key="reg_ate")

    if data_de > data_ate:
        st.error("A data inicial nao pode ser maior que a data final.")
        st.stop()

    with db_cursor() as (_, cur):
        cur.execute(
            """
            SELECT a.id,
                   a.work_day,
                   TO_CHAR(a.work_day, 'DD/MM/YYYY')   AS dia,
                   TO_CHAR(a.check_in_time, 'HH24:MI')  AS entrada,
                   TO_CHAR(a.check_out_time, 'HH24:MI') AS saida,
                   CASE a.status WHEN 3 THEN 'Aberto' ELSE 'Fechado' END AS status,
                   COALESCE(a.observation, '') AS observacao_entrada,
                   a.check_in_time            AS check_in_raw,
                   a.check_out_time           AS check_out_raw
            FROM attendance a
            WHERE a.employee = %s
              AND a.work_day BETWEEN %s AND %s
              AND a.status IN (1, 3)
            ORDER BY a.work_day DESC, a.check_in_time ASC
            """,
            (func_id, data_de, data_ate),
        )
        registros = cur.fetchall()

    if not registros:
        st.info(f"Nenhum registro encontrado para {func_nome} no periodo selecionado.")
    else:
        st.markdown(f"**{len(registros)} registro(s)** entre {data_de.strftime('%d/%m/%Y')} e {data_ate.strftime('%d/%m/%Y')}")
        st.markdown("---")

        dias = {}
        for reg in registros:
            if reg["dia"] not in dias:
                dias[reg["dia"]] = []
            dias[reg["dia"]].append(reg)

        for dia, regs in dias.items():
            st.markdown(f"##### {dia}")
            for reg in regs:
                label = f"Entrada: {reg['entrada']}  |  Saida: {reg['saida'] or 'Em aberto'}  |  {reg['status']}"
                with st.expander(label, expanded=(len(registros) == 1)):
                    col_edit, col_del = st.columns([4, 1])
                    with col_edit:
                        with st.form(f"form_edit_{reg['id']}"):
                            col_e, col_s = st.columns(2)
                            with col_e:
                                hora_entrada = st.time_input(
                                    "Hora de Entrada",
                                    value=reg["check_in_raw"].time() if reg["check_in_raw"] else time(8, 0),
                                    key=f"entrada_{reg['id']}",
                                )
                            with col_s:
                                hora_saida_val = reg["check_out_raw"].time() if reg["check_out_raw"] else None
                                hora_saida = st.time_input(
                                    "Hora de Saida",
                                    value=hora_saida_val or time(17, 0),
                                    key=f"saida_{reg['id']}",
                                )
                                sem_saida = st.checkbox(
                                    "Manter em aberto",
                                    value=(hora_saida_val is None),
                                    key=f"aberto_{reg['id']}",
                                )
                            obs = st.text_input("Observacao", value=reg["observacao_entrada"], key=f"obs_{reg['id']}")
                            salvar = st.form_submit_button("Salvar Alteracoes", type="primary")

                        if salvar:
                            work_day     = reg["check_in_raw"].date()
                            check_in_dt  = datetime.combine(work_day, hora_entrada)
                            check_out_dt = None if sem_saida else datetime.combine(work_day, hora_saida)
                            if check_out_dt and check_out_dt < check_in_dt:
                                st.error("Hora de saida nao pode ser anterior a entrada.")
                            else:
                                with db_cursor() as (_, cur):
                                    cur.execute(
                                        """
                                        UPDATE attendance SET
                                            check_in_time = %s, check_out_time = %s,
                                            status = %s, observation = %s, update_date = NOW()
                                        WHERE id = %s AND employee = %s
                                        """,
                                        (check_in_dt, check_out_dt, 3 if sem_saida else 1,
                                         obs or None, reg["id"], func_id),
                                    )
                                st.success("Registro atualizado.")
                                st.rerun()

                    with col_del:
                        st.markdown("&nbsp;")
                        if st.button("Excluir", key=f"del_{reg['id']}", type="secondary", use_container_width=True):
                            with db_cursor() as (_, cur):
                                cur.execute("DELETE FROM attendance WHERE id = %s AND employee = %s", (reg["id"], func_id))
                            st.success("Registro excluido.")
                            st.rerun()
            st.markdown("---")


# =============================================================================
# ABA: ALERTAS +10h  (independente — todos os funcionarios, sem filtro obrigatorio)
# =============================================================================
with tab_alertas:
    st.markdown("Dias com **mais de 10 horas** trabalhadas em qualquer funcionario da empresa.")

    col_a_de, col_a_ate, _ = st.columns([1, 1, 2])
    with col_a_de:
        alerta_de = st.date_input("De", value=date.today() - timedelta(days=30), key="alerta_de")
    with col_a_ate:
        alerta_ate = st.date_input("Ate", value=date.today(), key="alerta_ate")

    with db_cursor() as (_, cur):
        cur.execute(
            """
            SELECT
                a.employee                                                           AS emp_id,
                e.first_name || ' ' || e.last_name                                  AS funcionario,
                a.work_day,
                TO_CHAR(a.work_day, 'DD/MM/YYYY')                                   AS dia,
                TO_CHAR(MIN(a.check_in_time), 'HH24:MI')                            AS entrada,
                TO_CHAR(MAX(a.check_out_time), 'HH24:MI')                           AS saida,
                TO_CHAR(SUM(a.check_out_time - a.check_in_time), 'HH24:MI')         AS horas_trabalhadas
            FROM attendance a
            JOIN employee e ON e.id = a.employee
            JOIN company c ON c.id = e.company
            WHERE c.email = %s
              AND a.status = 1
              AND a.work_day BETWEEN %s AND %s
            GROUP BY a.employee, e.first_name, e.last_name, a.work_day
            HAVING SUM(a.check_out_time - a.check_in_time) > INTERVAL '10 hours'
            ORDER BY a.work_day DESC, funcionario ASC
            """,
            (email, alerta_de, alerta_ate),
        )
        alertas = cur.fetchall()

    if not alertas:
        st.success("Nenhum dia com mais de 10 horas trabalhadas no periodo.")
        st.stop()

    st.warning(f"{len(alertas)} dia(s) com mais de 10 horas encontrado(s).")

    df_alertas = pd.DataFrame([dict(r) for r in alertas])
    emp_ids_alerta  = df_alertas["emp_id"].tolist()
    work_days_alerta = df_alertas["work_day"].tolist()

    ev_alerta = st.dataframe(
        df_alertas[["funcionario", "dia", "entrada", "saida", "horas_trabalhadas"]].rename(columns={
            "funcionario":       "Funcionario",
            "dia":               "Data",
            "entrada":           "Primeira Entrada",
            "saida":             "Ultima Saida",
            "horas_trabalhadas": "Total Trabalhado",
        }),
        use_container_width=True,
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        key="sel_alerta",
    )

    sel_alerta = ev_alerta.selection.rows
    if not sel_alerta:
        st.info("Clique em uma linha para editar os registros daquele dia.")
        st.stop()

    alerta_emp_id  = emp_ids_alerta[sel_alerta[0]]
    alerta_work_day = work_days_alerta[sel_alerta[0]]
    alerta_nome    = df_alertas.iloc[sel_alerta[0]]["funcionario"]
    alerta_dia_str = df_alertas.iloc[sel_alerta[0]]["dia"]

    st.markdown("---")
    st.subheader(f"Editando registros de {alerta_nome} — {alerta_dia_str}")

    with db_cursor() as (_, cur):
        cur.execute(
            """
            SELECT a.id,
                   TO_CHAR(a.check_in_time, 'HH24:MI')  AS entrada,
                   TO_CHAR(a.check_out_time, 'HH24:MI') AS saida,
                   CASE a.status WHEN 3 THEN 'Aberto' ELSE 'Fechado' END AS status,
                   COALESCE(a.observation, '') AS observacao_entrada,
                   a.check_in_time            AS check_in_raw,
                   a.check_out_time           AS check_out_raw
            FROM attendance a
            WHERE a.employee = %s AND a.work_day = %s AND a.status IN (1, 3)
            ORDER BY a.check_in_time ASC
            """,
            (alerta_emp_id, alerta_work_day),
        )
        regs_alerta = cur.fetchall()

    for reg in regs_alerta:
        label = f"Entrada: {reg['entrada']}  |  Saida: {reg['saida'] or 'Em aberto'}  |  {reg['status']}"
        with st.expander(label, expanded=True):
            col_edit, col_del = st.columns([4, 1])
            with col_edit:
                with st.form(f"form_alerta_{reg['id']}"):
                    col_e, col_s = st.columns(2)
                    with col_e:
                        hora_entrada = st.time_input(
                            "Hora de Entrada",
                            value=reg["check_in_raw"].time() if reg["check_in_raw"] else time(8, 0),
                            key=f"a_entrada_{reg['id']}",
                        )
                    with col_s:
                        hora_saida_val = reg["check_out_raw"].time() if reg["check_out_raw"] else None
                        hora_saida = st.time_input(
                            "Hora de Saida",
                            value=hora_saida_val or time(17, 0),
                            key=f"a_saida_{reg['id']}",
                        )
                        sem_saida = st.checkbox(
                            "Manter em aberto",
                            value=(hora_saida_val is None),
                            key=f"a_aberto_{reg['id']}",
                        )
                    obs = st.text_input("Observacao", value=reg["observacao_entrada"], key=f"a_obs_{reg['id']}")
                    salvar = st.form_submit_button("Salvar Alteracoes", type="primary")

                if salvar:
                    check_in_dt  = datetime.combine(alerta_work_day, hora_entrada)
                    check_out_dt = None if sem_saida else datetime.combine(alerta_work_day, hora_saida)
                    if check_out_dt and check_out_dt < check_in_dt:
                        st.error("Hora de saida nao pode ser anterior a entrada.")
                    else:
                        with db_cursor() as (_, cur):
                            cur.execute(
                                """
                                UPDATE attendance SET
                                    check_in_time = %s, check_out_time = %s,
                                    status = %s, observation = %s, update_date = NOW()
                                WHERE id = %s AND employee = %s
                                """,
                                (check_in_dt, check_out_dt, 3 if sem_saida else 1,
                                 obs or None, reg["id"], alerta_emp_id),
                            )
                        st.success("Registro atualizado.")
                        st.rerun()

            with col_del:
                st.markdown("&nbsp;")
                if st.button("Excluir", key=f"a_del_{reg['id']}", type="secondary", use_container_width=True):
                    with db_cursor() as (_, cur):
                        cur.execute("DELETE FROM attendance WHERE id = %s AND employee = %s", (reg["id"], alerta_emp_id))
                    st.success("Registro excluido.")
                    st.rerun()
