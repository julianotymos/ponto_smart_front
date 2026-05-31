import streamlit as st
from utils.db import db_cursor
from datetime import date

st.set_page_config(page_title="Funcionarios - Ponto Smart", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
[data-testid="stStatusWidget"] { display: none !important; }
.block-container { padding-top: 1rem !important; }
h1 { margin-bottom: 0 !important; }
h2, h3 { margin-top: 0 !important; margin-bottom: 0.5rem !important; }
hr { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
header[data-testid="stHeader"] { height: 2.5rem !important; min-height: 2.5rem !important; overflow: visible !important; }
</style>
""", unsafe_allow_html=True)

ESTADOS_BR = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO",
    "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
    "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
]

JORNADAS = ["5x2", "6x1", "12x36", "4x2", "Livre"]


from utils.auth import require_login


def idx(lista, valor):
    try:
        return lista.index(valor)
    except (ValueError, TypeError):
        return 0


require_login()

email = st.session_state["company_email"]
company_id = st.session_state.get("company_id")

st.title("Funcionarios")
st.markdown("---")

tab_editar, tab_novo = st.tabs(["Editar Funcionario", "Novo Funcionario"])


# =============================================================================
# ABA: NOVO FUNCIONARIO
# =============================================================================
with tab_novo:
    with st.form("form_novo_funcionario", clear_on_submit=True):

        st.subheader("Dados Pessoais")
        col1, col2 = st.columns(2)
        with col1:
            n_primeiro_nome = st.text_input("Primeiro Nome *", placeholder="Maria", key="n_first")
            n_identificacao = st.text_input("CPF / CNPJ *", placeholder="000.000.000-00", key="n_id")
            n_email_func = st.text_input("Email *", placeholder="funcionario@email.com", key="n_email")
            n_nascimento = st.date_input("Data de Nascimento *", value=None, min_value=date(1940, 1, 1), max_value=date.today(), key="n_birth")
        with col2:
            n_ultimo_nome = st.text_input("Sobrenome *", placeholder="Silva", key="n_last")
            n_tipo_pessoa = st.radio("Tipo", ["PF", "PJ"], horizontal=True, key="n_type")
            n_telefone = st.text_input("Telefone", placeholder="(11) 99999-9999", max_chars=15, key="n_phone")

        st.subheader("Endereco")
        col_end1, col_end2, col_end3 = st.columns([3, 1, 1])
        with col_end1:
            n_endereco = st.text_input("Logradouro", placeholder="Rua das Flores", key="n_addr")
        with col_end2:
            n_numero = st.text_input("Numero", placeholder="123", key="n_num")
        with col_end3:
            n_complemento = st.text_input("Complemento", placeholder="Apto 4", key="n_comp")
        col_cid, col_est, col_cep = st.columns(3)
        with col_cid:
            n_cidade = st.text_input("Cidade", placeholder="Sao Paulo", key="n_city")
        with col_est:
            n_estado = st.selectbox("Estado", ESTADOS_BR, index=ESTADOS_BR.index("SP"), key="n_state")
        with col_cep:
            n_cep = st.text_input("CEP", placeholder="00000-000", max_chars=10, key="n_zip")

        st.subheader("Dados de Emprego")
        col_emp1, col_emp2 = st.columns(2)
        with col_emp1:
            n_cargo = st.text_input("Cargo / Funcao", placeholder="Atendente", key="n_pos")
            n_admissao = st.date_input("Data de Admissao", value=date.today(), key="n_hire")
            n_jornada = st.selectbox("Jornada de Trabalho", JORNADAS, key="n_journal")
        with col_emp2:
            n_salario = st.number_input("Salario (R$)", min_value=0.0, step=100.0, format="%.2f", key="n_salary")
            n_carga_semanal = st.number_input("Carga Horaria Semanal (h)", min_value=0.0, max_value=60.0, value=44.0, step=0.5, key="n_wl")

        st.subheader("Beneficios")
        col_b1, col_b2 = st.columns(2)
        with col_b1:
            n_vale_refeicao = st.number_input("Vale Refeicao (R$/dia)", min_value=0.0, step=1.0, format="%.2f", key="n_meal")
        with col_b2:
            n_vale_transporte = st.number_input("Vale Transporte (R$/dia)", min_value=0.0, step=1.0, format="%.2f", key="n_transport")

        st.subheader("Contato de Emergencia")
        col_em1, col_em2 = st.columns(2)
        with col_em1:
            n_contato_nome = st.text_input("Nome do Contato", placeholder="Joao Silva", key="n_ec_name")
        with col_em2:
            n_contato_tel = st.text_input("Telefone do Contato", placeholder="(11) 99999-9999", max_chars=15, key="n_ec_phone")

        st.subheader("Dados Bancarios")
        col_bk1, col_bk2, col_bk3, col_bk4 = st.columns(4)
        with col_bk1:
            n_banco = st.text_input("Cod. Banco", placeholder="001", max_chars=5, key="n_bank")
        with col_bk2:
            n_agencia = st.text_input("Agencia", placeholder="0001", max_chars=5, key="n_branch")
        with col_bk3:
            n_conta = st.text_input("Conta", placeholder="00000-0", key="n_account")
        with col_bk4:
            n_pix = st.text_input("PIX", placeholder="CPF, email ou chave", key="n_pix")

        st.subheader("Foto")
        col_foto_prev, col_foto_inputs = st.columns([1, 3])
        with col_foto_inputs:
            n_photo_file = st.file_uploader("Enviar foto", type=["jpg", "jpeg", "png"], key="n_photo_file")
            st.caption("ou informe uma URL existente:")
            n_photo_url = st.text_input("URL da Foto", placeholder="https://...", key="n_photo")
        with col_foto_prev:
            if n_photo_file:
                st.image(n_photo_file, use_container_width=True, caption="Pre-visualizacao")
            elif n_photo_url:
                try:
                    st.image(n_photo_url, use_container_width=True)
                except Exception:
                    st.caption("URL invalida ou inacessivel")
            else:
                st.caption("Sem foto")

        st.markdown("---")
        n_submitted = st.form_submit_button("Cadastrar Funcionario", type="primary", use_container_width=True)

    if n_submitted:
        erros = []
        if not n_primeiro_nome.strip():
            erros.append("Primeiro Nome e obrigatorio.")
        if not n_ultimo_nome.strip():
            erros.append("Sobrenome e obrigatorio.")
        if not n_identificacao.strip():
            erros.append("CPF/CNPJ e obrigatorio.")
        if not n_email_func.strip() or "@" not in n_email_func:
            erros.append("Email valido e obrigatorio.")
        if not n_nascimento:
            erros.append("Data de Nascimento e obrigatoria.")
        if not company_id:
            erros.append("Empresa nao identificada. Volte a pagina inicial.")

        if erros:
            for e in erros:
                st.error(e)
        else:
            from utils.storage import upload_photo

            with db_cursor() as (_, cur):
                cur.execute(
                    "SELECT COALESCE(MAX(CAST(employee_code AS INTEGER)), 0) + 1 AS next_num FROM employee WHERE employee_code ~ '^[0-9]+$'"
                )
                next_num = cur.fetchone()["next_num"]
                employee_code = str(next_num).zfill(4)

            # Upload da foto se enviada
            foto_final_url = n_photo_url.strip() or None
            if n_photo_file:
                try:
                    foto_final_url = upload_photo(n_photo_file.getvalue(), employee_code, n_photo_file.type)
                except Exception as ex:
                    st.error(f"Erro no upload da foto: {ex}")
                    st.stop()

            with db_cursor() as (_, cur):
                cur.execute(
                    """
                    INSERT INTO employee (
                        employee_code, identification_number, person_type,
                        first_name, last_name, email, phone_number, birth_date,
                        address, house_number, additional_information, city, state, zip_code,
                        account_number, branch_id, bank_id, pix,
                        status, status_date, system_user, company,
                        position, salary, journal, weekly_workload, hire_date,
                        emergency_contact_name, emergency_contact_phone,
                        meal_voucher_value, transport_voucher_value,
                        photo_url,
                        insert_date, update_date
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        1, NOW(), 1, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s,
                        NOW(), NOW()
                    )
                    """,
                    (
                        employee_code, n_identificacao.strip(), n_tipo_pessoa,
                        n_primeiro_nome.strip(), n_ultimo_nome.strip(), n_email_func.strip(),
                        n_telefone.strip() or None, n_nascimento,
                        n_endereco.strip() or None, n_numero.strip() or None,
                        n_complemento.strip() or None, n_cidade.strip() or None,
                        n_estado, n_cep.strip() or None,
                        n_conta.strip() or None, n_agencia.strip() or None,
                        n_banco.strip() or None, n_pix.strip() or None,
                        company_id,
                        n_cargo.strip() or None, n_salario if n_salario > 0 else None,
                        n_jornada, n_carga_semanal if n_carga_semanal > 0 else None, n_admissao,
                        n_contato_nome.strip() or None, n_contato_tel.strip() or None,
                        n_vale_refeicao if n_vale_refeicao > 0 else None,
                        n_vale_transporte if n_vale_transporte > 0 else None,
                        foto_final_url,
                    ),
                )

            st.success(
                f"Funcionario **{n_primeiro_nome.strip()} {n_ultimo_nome.strip()}** cadastrado com sucesso! "
                f"Codigo: `{employee_code}`"
            )


# =============================================================================
# ABA: EDITAR FUNCIONARIO
# =============================================================================
with tab_editar:
    import pandas as pd

    filtro_status = st.radio(
        "Filtrar por status",
        ["Ativo", "Inativo", "Todos"],
        horizontal=True,
        key="filtro_status_edit",
    )

    status_filtro_sql = {"Ativo": "AND e.status = 1", "Inativo": "AND e.status = 2", "Todos": ""}

    with db_cursor() as (_, cur):
        cur.execute(
            f"""
            SELECT
                e.id,
                e.employee_code                               AS codigo,
                e.first_name || ' ' || e.last_name           AS nome,
                e.identification_number                       AS cpf_cnpj,
                COALESCE(e.position, '-')                     AS cargo,
                s.description                                 AS status,
                TO_CHAR(e.hire_date, 'DD/MM/YYYY')           AS admissao,
                COALESCE(e.phone_number, '-')                 AS telefone,
                e.email
            FROM employee e
            JOIN company c ON c.id = e.company
            JOIN status s ON s.id = e.status
            WHERE c.email = %s {status_filtro_sql[filtro_status]}
            ORDER BY e.first_name ASC
            """,
            (email,),
        )
        funcionarios = cur.fetchall()

    if not funcionarios:
        st.info(f"Nenhum funcionario com status '{filtro_status}' encontrado.")
    else:
        df_func = pd.DataFrame([dict(r) for r in funcionarios])
        ids = df_func["id"].tolist()
        df_grid = df_func.drop(columns=["id"])

        st.markdown("Clique em uma linha para selecionar o funcionario e carregar os dados para edicao.")

        evento = st.dataframe(
            df_grid,
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            column_config={
                "codigo":    st.column_config.TextColumn("Codigo"),
                "nome":      st.column_config.TextColumn("Nome"),
                "cpf_cnpj": st.column_config.TextColumn("CPF / CNPJ"),
                "cargo":     st.column_config.TextColumn("Cargo"),
                "status":    st.column_config.TextColumn("Status"),
                "admissao":  st.column_config.TextColumn("Admissao"),
                "telefone":  st.column_config.TextColumn("Telefone"),
                "email":     st.column_config.TextColumn("Email"),
            },
        )

        linhas_sel = evento.selection.rows
        if not linhas_sel:
            st.info("Selecione um funcionario na tabela acima para editar.")
            st.stop()

        func_id = ids[linhas_sel[0]]

        with db_cursor() as (_, cur):
            cur.execute(
                "SELECT e.*, s.description AS status_description FROM employee e JOIN status s ON s.id = e.status WHERE e.id = %s",
                (func_id,),
            )
            emp = dict(cur.fetchone())

            cur.execute("SELECT id, description FROM status ORDER BY id")
            status_rows = cur.fetchall()

        status_map = {r["description"]: r["id"] for r in status_rows}
        status_desc_list = list(status_map.keys())

        st.markdown("---")
        st.markdown(f"**Editando:** {emp['first_name']} {emp['last_name']} &nbsp;|&nbsp; Codigo: `{emp['employee_code']}` &nbsp;|&nbsp; Status: {emp['status_description']}")

        with st.form("form_editar_funcionario"):

            st.subheader("Dados Pessoais")
            col_foto, col1, col2 = st.columns([1, 2, 2])
            with col_foto:
                foto_atual = emp.get("photo_url") or ""
                if foto_atual:
                    try:
                        st.image(foto_atual, use_container_width=True)
                    except Exception:
                        st.caption("Foto indisponivel")
                else:
                    st.caption("Sem foto cadastrada")
                e_photo_file = st.file_uploader("Enviar nova foto", type=["jpg", "jpeg", "png"], key="e_photo_file")
                e_photo_url = st.text_input("ou URL da Foto", value=foto_atual, placeholder="https://...", key="e_photo")
            with col1:
                e_primeiro_nome = st.text_input("Primeiro Nome *", value=emp.get("first_name", ""), key="e_first")
                e_identificacao = st.text_input("CPF / CNPJ *", value=emp.get("identification_number", ""), key="e_id")
                e_email_func = st.text_input("Email *", value=emp.get("email", ""), key="e_email")
                e_nascimento = st.date_input("Data de Nascimento", value=emp.get("birth_date") or None, min_value=date(1940, 1, 1), max_value=date.today(), key="e_birth")
            with col2:
                e_ultimo_nome = st.text_input("Sobrenome *", value=emp.get("last_name", ""), key="e_last")
                e_tipo_pessoa = st.radio("Tipo", ["PF", "PJ"], index=0 if emp.get("person_type", "PF") == "PF" else 1, horizontal=True, key="e_type")
                e_telefone = st.text_input("Telefone", value=emp.get("phone_number", "") or "", max_chars=15, key="e_phone")

            col_code, col_status = st.columns(2)
            with col_code:
                st.text_input("Codigo do Funcionario", value=emp.get("employee_code", ""), disabled=True, key="e_code")
                e_employee_code = emp["employee_code"]
            with col_status:
                e_status_sel = st.selectbox("Status", status_desc_list, index=idx(status_desc_list, emp.get("status_description")), key="e_status")

            st.subheader("Endereco")
            col_end1, col_end2, col_end3 = st.columns([3, 1, 1])
            with col_end1:
                e_endereco = st.text_input("Logradouro", value=emp.get("address", "") or "", key="e_addr")
            with col_end2:
                e_numero = st.text_input("Numero", value=emp.get("house_number", "") or "", key="e_num")
            with col_end3:
                e_complemento = st.text_input("Complemento", value=emp.get("additional_information", "") or "", key="e_comp")
            col_cid, col_est, col_cep = st.columns(3)
            with col_cid:
                e_cidade = st.text_input("Cidade", value=emp.get("city", "") or "", key="e_city")
            with col_est:
                e_estado = st.selectbox("Estado", ESTADOS_BR, index=idx(ESTADOS_BR, emp.get("state")), key="e_state")
            with col_cep:
                e_cep = st.text_input("CEP", value=emp.get("zip_code", "") or "", max_chars=10, key="e_zip")

            st.subheader("Dados de Emprego")
            col_emp1, col_emp2 = st.columns(2)
            with col_emp1:
                e_cargo = st.text_input("Cargo / Funcao", value=emp.get("position", "") or "", key="e_pos")
                e_admissao = st.date_input("Data de Admissao", value=emp.get("hire_date") or date.today(), key="e_hire")
                e_jornada = st.selectbox("Jornada de Trabalho", JORNADAS, index=idx(JORNADAS, emp.get("journal")), key="e_journal")
            with col_emp2:
                e_salario = st.number_input("Salario (R$)", min_value=0.0, step=100.0, format="%.2f", value=float(emp.get("salary") or 0), key="e_salary")
                e_carga_semanal = st.number_input("Carga Horaria Semanal (h)", min_value=0.0, max_value=60.0, step=0.5, value=float(emp.get("weekly_workload") or 44), key="e_wl")
                e_demissao = st.date_input("Data de Demissao", value=emp.get("termination_date") or None, key="e_term")

            st.subheader("Beneficios")
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                e_vale_refeicao = st.number_input("Vale Refeicao (R$/dia)", min_value=0.0, step=1.0, format="%.2f", value=float(emp.get("meal_voucher_value") or 0), key="e_meal")
            with col_b2:
                e_vale_transporte = st.number_input("Vale Transporte (R$/dia)", min_value=0.0, step=1.0, format="%.2f", value=float(emp.get("transport_voucher_value") or 0), key="e_transport")

            st.subheader("Contato de Emergencia")
            col_em1, col_em2 = st.columns(2)
            with col_em1:
                e_contato_nome = st.text_input("Nome do Contato", value=emp.get("emergency_contact_name", "") or "", key="e_ec_name")
            with col_em2:
                e_contato_tel = st.text_input("Telefone do Contato", value=emp.get("emergency_contact_phone", "") or "", max_chars=15, key="e_ec_phone")

            st.subheader("Dados Bancarios")
            col_bk1, col_bk2, col_bk3, col_bk4 = st.columns(4)
            with col_bk1:
                e_banco = st.text_input("Cod. Banco", value=emp.get("bank_id", "") or "", max_chars=5, key="e_bank")
            with col_bk2:
                e_agencia = st.text_input("Agencia", value=emp.get("branch_id", "") or "", max_chars=5, key="e_branch")
            with col_bk3:
                e_conta = st.text_input("Conta", value=emp.get("account_number", "") or "", key="e_account")
            with col_bk4:
                e_pix = st.text_input("PIX", value=emp.get("pix", "") or "", key="e_pix")

            st.markdown("---")
            e_salvar = st.form_submit_button("Salvar Alteracoes", type="primary", use_container_width=True)

        if e_salvar:
            erros = []
            if not e_primeiro_nome.strip():
                erros.append("Primeiro Nome e obrigatorio.")
            if not e_ultimo_nome.strip():
                erros.append("Sobrenome e obrigatorio.")
            if not e_identificacao.strip():
                erros.append("CPF/CNPJ e obrigatorio.")
            if not e_email_func.strip() or "@" not in e_email_func:
                erros.append("Email valido e obrigatorio.")

            if erros:
                for e in erros:
                    st.error(e)
            else:
                from utils.storage import upload_photo

                foto_edit_url = e_photo_url.strip() or None
                if e_photo_file:
                    try:
                        foto_edit_url = upload_photo(e_photo_file.getvalue(), emp["employee_code"], e_photo_file.type)
                    except Exception as ex:
                        st.error(f"Erro no upload da foto: {ex}")
                        st.stop()

                novo_status_id = status_map[e_status_sel]
                with db_cursor() as (_, cur):
                    cur.execute(
                        """
                        UPDATE employee SET
                            employee_code            = %s,
                            first_name               = %s,
                            last_name                = %s,
                            identification_number    = %s,
                            person_type              = %s,
                            email                    = %s,
                            phone_number             = %s,
                            birth_date               = %s,
                            address                  = %s,
                            house_number             = %s,
                            additional_information   = %s,
                            city                     = %s,
                            state                    = %s,
                            zip_code                 = %s,
                            position                 = %s,
                            salary                   = %s,
                            journal                  = %s,
                            weekly_workload          = %s,
                            hire_date                = %s,
                            termination_date         = %s,
                            meal_voucher_value       = %s,
                            transport_voucher_value  = %s,
                            emergency_contact_name   = %s,
                            emergency_contact_phone  = %s,
                            bank_id                  = %s,
                            branch_id                = %s,
                            account_number           = %s,
                            pix                      = %s,
                            photo_url                = %s,
                            status                   = %s,
                            status_date              = NOW(),
                            update_date              = NOW()
                        WHERE id = %s
                        """,
                        (
                            e_employee_code.strip() or emp["employee_code"],
                            e_primeiro_nome.strip(),
                            e_ultimo_nome.strip(),
                            e_identificacao.strip(),
                            e_tipo_pessoa,
                            e_email_func.strip(),
                            e_telefone.strip() or None,
                            e_nascimento,
                            e_endereco.strip() or None,
                            e_numero.strip() or None,
                            e_complemento.strip() or None,
                            e_cidade.strip() or None,
                            e_estado,
                            e_cep.strip() or None,
                            e_cargo.strip() or None,
                            e_salario if e_salario > 0 else None,
                            e_jornada,
                            e_carga_semanal if e_carga_semanal > 0 else None,
                            e_admissao,
                            e_demissao,
                            e_vale_refeicao if e_vale_refeicao > 0 else None,
                            e_vale_transporte if e_vale_transporte > 0 else None,
                            e_contato_nome.strip() or None,
                            e_contato_tel.strip() or None,
                            e_banco.strip() or None,
                            e_agencia.strip() or None,
                            e_conta.strip() or None,
                            e_pix.strip() or None,
                            foto_edit_url,
                            novo_status_id,
                            func_id,
                        ),
                    )

                st.success(f"Dados de **{e_primeiro_nome.strip()} {e_ultimo_nome.strip()}** atualizados com sucesso.")
                st.rerun()
