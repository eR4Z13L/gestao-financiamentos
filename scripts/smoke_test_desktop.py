"""Valida as telas PySide6 sem precisar abrir uma janela de verdade (roda
com QT_QPA_PLATFORM=offscreen) - confere se os valores exibidos nos cards e
nas tabelas batem com o que core/dashboard.py e core/clientes.py calculam.

Os dois primeiros testes so leem - nao mexem no arquivo real. Os demais
(exclusao, edicao de proposta) escrevem, entao rodam numa copia temporaria.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_desktop.py
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from PySide6.QtWidgets import QApplication, QMessageBox

from config import CAMINHO_XLSX

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
from core import clientes as clientes_mod
from core import dashboard as dashboard_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from desktop.screens.dashboard_screen import DashboardScreen
from desktop.screens.ficha_cliente_screen import FichaClienteScreen


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def testar_dashboard_screen(app: QApplication) -> None:
    linha("1) DashboardScreen")

    tela = DashboardScreen()
    propostas = propostas_mod.listar_propostas()
    topo = dashboard_mod.indicadores_do_topo(propostas)

    assert tela._card_em_analise.valor() == str(topo["em_analise"]["quantidade"])
    assert tela._card_a_efetivar.valor() == str(topo["a_efetivar"]["quantidade"])
    print(f"Cards batem com indicadores_do_topo(): {topo['em_analise']['quantidade']} em análise, {topo['a_efetivar']['quantidade']} a efetivar")

    funil_esperado = dashboard_mod.funil_por_etapa(propostas)
    assert [(e.etapa, e.quantidade) for e in tela._funil.etapas()] == [(e.etapa, e.quantidade) for e in funil_esperado]
    print(f"Funil por etapa: {len(funil_esperado)} linhas, as mesmas de core/dashboard.py")

    bancos_esperados = dashboard_mod.por_banco(propostas)
    assert tela._tabela_bancos.total_de_linhas() == len(bancos_esperados)
    print(f"Tabela por banco: {tela._tabela_bancos.total_de_linhas()} linhas (esperado {len(bancos_esperados)})")

    vendedor_esperado = dashboard_mod.por_vendedor(propostas)
    assert tela._tabela_vendedores.total_de_linhas() == len(vendedor_esperado)
    print(f"Tabela de desempenho por vendedor: {tela._tabela_vendedores.total_de_linhas()} linhas (esperado {len(vendedor_esperado)})")

    print("\nOK: DashboardScreen exibe exatamente o que core/dashboard.py calcula.")


def testar_ficha_cliente_screen(app: QApplication) -> None:
    linha("2) FichaClienteScreen")

    tela = FichaClienteScreen()
    todos_clientes = clientes_mod.listar_clientes()

    assert tela._lista.count() == len(todos_clientes)
    assert tela._painel_stack.currentIndex() == 0
    print(f"Lista inicial (sem busca): {tela._lista.count()} clientes, painel no estado vazio (indice 0).")

    primeiro_nome = todos_clientes.iloc[0]["CLIENTE"]
    termo = primeiro_nome.split()[0]

    tela._busca.setText(termo)
    esperado_busca = clientes_mod.buscar(termo)
    assert tela._lista.count() == len(esperado_busca), (
        f"busca por '{termo}' deveria retornar {len(esperado_busca)} cliente(s), lista tem {tela._lista.count()}"
    )
    assert tela._painel_stack.currentIndex() == 0  # buscar de novo reseta o painel
    print(f"Busca por '{termo}' filtrou para {tela._lista.count()} cliente(s) (bate com core.clientes.buscar).")

    tela._busca.setText("")
    assert tela._lista.count() == len(todos_clientes)

    # seleciona um cliente que tem propostas (o primeiro da lista de propostas,
    # nao necessariamente o primeiro por ordem alfabetica) pra exercitar o
    # caminho "com historico" tambem, nao so o de lista vazia
    propostas = propostas_mod.listar_propostas()
    cpf_com_proposta = propostas.iloc[0]["CPF"]
    cliente_com_proposta = clientes_mod.buscar_por_cpf(cpf_com_proposta)

    indice_na_lista = next(
        i for i in range(tela._lista.count())
        if tela._lista.cpf_da_linha(i) == cliente_com_proposta["CPF/CNPJ"]
    )
    tela._lista.definir_linha_atual(indice_na_lista)

    assert tela._painel_stack.currentIndex() == 1
    assert tela._nome_label.text() == cliente_com_proposta["CLIENTE"]
    assert tela._campo_cpf.text() == cliente_com_proposta["CPF/CNPJ"]
    assert tela._campo_vendedor.text() == (cliente_com_proposta["VENDEDOR"] or "—")

    # isVisible() so reflete a realidade quando a janela foi de fato mostrada
    # na tela (nao e o caso aqui, em modo headless) - isHidden() reflete o
    # setVisible()/hide() que o proprio codigo da tela chamou, entao e o que
    # da pra verificar sem abrir uma janela de verdade.
    historico_esperado = propostas_mod.historico_por_cpf(cpf_com_proposta)
    assert tela._modelo_historico.rowCount() == len(historico_esperado)
    assert tela._contentor_historico.isHidden() is False
    assert tela._historico_vazio.isHidden() is True
    print(
        f"Selecionar '{cliente_com_proposta['CLIENTE']}' preencheu a ficha e o historico "
        f"({tela._modelo_historico.rowCount()} proposta(s), esperado {len(historico_esperado)})."
    )

    # agora um cliente sem nenhuma proposta, pra exercitar o estado vazio do historico
    cpfs_com_proposta = set(propostas["CPF"])
    cliente_sem_proposta = next(
        clientes_mod.buscar_por_cpf(row["CPF/CNPJ"])
        for _, row in todos_clientes.iterrows()
        if row["CPF/CNPJ"] not in cpfs_com_proposta
    )
    indice_sem_proposta = next(
        i for i in range(tela._lista.count())
        if tela._lista.cpf_da_linha(i) == cliente_sem_proposta["CPF/CNPJ"]
    )
    tela._lista.definir_linha_atual(indice_sem_proposta)
    assert tela._modelo_historico.rowCount() == 0
    assert tela._contentor_historico.isHidden() is True
    assert tela._historico_vazio.isHidden() is False
    print(f"Selecionar '{cliente_sem_proposta['CLIENTE']}' (sem propostas) mostrou o estado vazio corretamente.")

    print("\nOK: FichaClienteScreen busca/filtra/seleciona e exibe dados+histórico igual ao core.")


def testar_exclusao_cliente(app: QApplication) -> None:
    linha("3) Exclusão de cliente (copia temporaria)")

    tmp_path = CAMINHO_XLSX.parent / "_smoke_test_exclusao.xlsx"
    shutil.copy(CAMINHO_XLSX, tmp_path)
    clientes_mod.CAMINHO_XLSX = tmp_path
    propostas_mod.CAMINHO_XLSX = tmp_path

    # QMessageBox.question e modal (.exec() proprio) - em modo headless trava
    # esperando um clique que nunca vem. Troca por um stub que so responde "Sim".
    mensagens: list[str] = []
    original_question = QMessageBox.question

    def _stub_question(*args, **kwargs):
        mensagens.append(args[2] if len(args) > 2 else "")
        return QMessageBox.StandardButton.Yes

    QMessageBox.question = staticmethod(_stub_question)

    try:
        tela = FichaClienteScreen()
        todos = clientes_mod.listar_clientes()
        propostas = propostas_mod.listar_propostas()
        cpfs_com_proposta = set(propostas["CPF"])

        cliente_sem_proposta = next(
            row for _, row in todos.iterrows() if row["CPF/CNPJ"] not in cpfs_com_proposta
        )
        tela._selecionar_por_cpf(cliente_sem_proposta["CPF/CNPJ"])
        assert tela._cpf_selecionado == cliente_sem_proposta["CPF/CNPJ"]

        tela._excluir_cliente()
        assert "não pode ser desfeita" in mensagens[-1]
        assert "Atenção" not in mensagens[-1]  # sem propostas vinculadas, sem aviso extra
        assert clientes_mod.buscar_por_cpf(cliente_sem_proposta["CPF/CNPJ"]) is None
        print(f"OK: '{cliente_sem_proposta['CLIENTE']}' (sem propostas) excluído, sem aviso extra na confirmação.")

        cpf_com_proposta = propostas.iloc[0]["CPF"]
        tela._selecionar_por_cpf(cpf_com_proposta)
        assert tela._cpf_selecionado == cpf_com_proposta

        tela._excluir_cliente()
        assert "Atenção" in mensagens[-1] and "proposta" in mensagens[-1]
        assert clientes_mod.buscar_por_cpf(cpf_com_proposta) is None
        # a proposta em si continua na planilha (nao apagamos historico)
        assert not propostas_mod.historico_por_cpf(cpf_com_proposta).empty
        print("OK: cliente com propostas vinculadas também foi excluído, com aviso extra na confirmação.")
        print("OK: a(s) proposta(s) dele NÃO foram apagadas (ficam órfãs de propósito, como combinado).")

        print("\nOK: exclusão de cliente funciona nos dois casos (com e sem propostas vinculadas).")
    finally:
        QMessageBox.question = original_question
        tmp_path.unlink(missing_ok=True)


def testar_edicao_proposta(app: QApplication) -> None:
    linha("4) Edição de proposta existente (cópia temporária)")

    tmp_path = CAMINHO_XLSX.parent / "_smoke_test_edicao_proposta.xlsx"
    shutil.copy(CAMINHO_XLSX, tmp_path)
    clientes_mod.CAMINHO_XLSX = tmp_path
    propostas_mod.CAMINHO_XLSX = tmp_path

    # QMessageBox.warning/critical/question sao modais - se a edicao for
    # rejeitada por algum motivo (valor em branco na proposta escolhida,
    # etc.) ou disparar a confirmacao de "campo recomendado em branco"/
    # "possivel duplicata" (FormularioProposta._salvar), elas travam esperando
    # um clique que nunca vem em modo headless. Stub por garantia.
    mensagens: list[str] = []
    original_warning = QMessageBox.warning
    original_critical = QMessageBox.critical
    original_question = QMessageBox.question

    def _stub_mensagem(*args, **kwargs):
        mensagens.append(args[2] if len(args) > 2 else "")
        return QMessageBox.StandardButton.Ok

    def _stub_question(*args, **kwargs):
        mensagens.append(args[2] if len(args) > 2 else "")
        return QMessageBox.StandardButton.Yes

    QMessageBox.warning = staticmethod(_stub_mensagem)
    QMessageBox.critical = staticmethod(_stub_mensagem)
    QMessageBox.question = staticmethod(_stub_question)

    try:
        tela = FichaClienteScreen()
        propostas = propostas_mod.listar_propostas()  # 1 unica leitura do arquivo

        # pega um cliente cuja proposta MAIS RECENTE (linha 0 de
        # historico_por_cpf - a mesma funcao/ordenacao que a tela e o
        # dialogo usam de verdade) tem status, banco E valor preenchidos, E
        # nao tem outra proposta do mesmo cliente com mesma data/valor - a
        # planilha real tem algumas propostas com campos em branco ou que
        # parecem duplicata (dado historico real, nao e bug), que sao um
        # caso a parte (campo em branco ou duplicata dispara a confirmacao
        # "salvar assim mesmo?" do dialogo, o que fugiria do "caminho feliz"
        # que este teste quer exercitar). Usa historico_por_cpf() direto (em
        # vez de agrupar/reordenar `propostas` na mao) porque sort_values usa
        # quicksort (nao estavel) por padrao - reordenar um subconjunto ja
        # ordenado pode desempatar datas iguais de um jeito diferente do que
        # historico_por_cpf() faria, escolhendo uma linha "mais recente"
        # diferente da que a tela de verdade vai selecionar.
        cpf_alvo = None
        for cpf_candidato in propostas["CPF"].unique():
            historico_candidato = propostas_mod.historico_por_cpf(cpf_candidato)
            mais_recente = historico_candidato.iloc[0]
            if not (
                mais_recente["STATUS"] != ""
                and mais_recente["BANCO"] != ""
                and not pd.isna(mais_recente["VALOR (R$)"])
            ):
                continue
            outras = historico_candidato.iloc[1:]
            duplicata = (
                (outras["DATA"] == mais_recente["DATA"])
                & ((outras["VALOR (R$)"] - mais_recente["VALOR (R$)"]).abs() < 0.01)
            ).any()
            if not duplicata:
                cpf_alvo = cpf_candidato
                break
        assert cpf_alvo is not None, "nenhum cliente com proposta 'limpa' (sem campo em branco nem duplicata) encontrado"

        historico_antes = propostas_mod.historico_por_cpf(cpf_alvo)
        assert not historico_antes.empty

        tela._selecionar_por_cpf(cpf_alvo)
        assert tela._cpf_selecionado == cpf_alvo

        # seleciona (1 clique) o primeiro card do historico
        tela._lista_historico.setCurrentIndex(tela._modelo_historico.index(0))
        indice_real = tela._modelo_historico.indice_real(0)
        status_original = historico_antes.loc[indice_real, "STATUS"]

        # o duplo clique no card EXPANDE o proprio card (nao trava esperando ninguem, ao
        # contrario do popup que existia): o teste pega o formulario aberto e "clica OK"
        # direto, chamando _salvar()
        tela._expansor.alternar(0)
        formulario = tela._expansor.formulario()
        assert formulario._status.currentText() == status_original, (
            f"card veio com status {formulario._status.currentText()!r}, esperado {status_original!r}"
        )
        assert formulario._modo_leitura, "proposta existente deveria abrir em modo leitura"
        formulario._habilitar_edicao()
        formulario._status.setCurrentText(propostas_mod.STATUS_APROVADO)
        formulario._observacoes.setPlainText("editado no smoke test")
        formulario._salvar()
        assert tela._expansor.formulario() is not formulario, "gravar recarrega o card (volta a leitura com o que foi gravado)"
        tela._expansor.descartar()

        historico_depois = propostas_mod.historico_por_cpf(cpf_alvo)
        linha_editada = historico_depois.loc[indice_real]
        assert linha_editada["STATUS"] == propostas_mod.STATUS_APROVADO
        assert linha_editada["OBSERVAÇÕES"] == "editado no smoke test"
        # as outras propostas do mesmo cliente nao podem ter mudado
        assert len(historico_depois) == len(historico_antes)
        print(f"OK: proposta (posição real {indice_real} no arquivo) editada via tela -> STATUS={linha_editada['STATUS']}")

        if mensagens:
            raise AssertionError(f"nao deveria ter mostrado nenhuma mensagem de erro, mostrou: {mensagens}")

        print("\nOK: edição de proposta existente funciona de ponta a ponta (seleção → card expandido → gravação).")
    finally:
        QMessageBox.warning = original_warning
        QMessageBox.critical = original_critical
        QMessageBox.question = original_question
        tmp_path.unlink(missing_ok=True)


def testar_texto_longo_sem_quebra(app: QApplication) -> None:
    linha("5) Texto longo sem espaço (URL colada) não estica o layout")

    # bug real reportado: uma URL longa sem espaço em Rede Social fazia o
    # tamanho MINIMO da ficha inteira (e por tabela, da janela) crescer bem
    # alem da tela, empurrando ate a barra lateral pra fora da area visivel
    tmp_path = CAMINHO_XLSX.parent / "_smoke_test_texto_longo.xlsx"
    shutil.copy(CAMINHO_XLSX, tmp_path)
    clientes_mod.CAMINHO_XLSX = tmp_path
    propostas_mod.CAMINHO_XLSX = tmp_path

    # token de proposito sem "/", "-", "." ou espaço nenhum - o pior caso,
    # onde o Qt normalmente nao tem NENHUM ponto de quebra natural
    token_sem_quebra = "Draju9k2LpXz7QmNvBw4RtY8sHcF1JdA3EoU6IgK5WnT2XcVbZmQpLrSjHfDkGa" * 3
    url_longa = "https://maapp.com.br/" + token_sem_quebra

    try:
        todos = clientes_mod.listar_clientes()
        cliente = todos[todos["TIPO"] == "Cliente"].iloc[0]
        cpf = cliente["CPF/CNPJ"]
        clientes_mod.atualizar_cliente(
            cpf, {"CPF/CNPJ": cpf, "CLIENTE": cliente["CLIENTE"], "TIPO": "Cliente", "REDE SOCIAL": url_longa}
        )

        historico = propostas_mod.historico_por_cpf(cpf)
        if not historico.empty:
            propostas_mod.atualizar_proposta(historico.index[0], {"OBSERVAÇÕES": url_longa})

        tela = FichaClienteScreen()
        tela._selecionar_por_cpf(cpf)

        # e o teste que realmente importa: a URL inteira (em Rede Social E em
        # Observacoes) nao pode forcar a ficha a pedir uma largura minima
        # gigante - antes da correcao, so o campo Rede Social sozinho ja
        # levava isso a quase 2000px
        largura_minima = tela.minimumSizeHint().width()
        assert largura_minima < 1100, f"minimumSizeHint ficou grande demais ({largura_minima}px) - layout vai estourar a tela"
        print(f"OK: minimumSizeHint da ficha com URL longa em Rede Social e Observações ficou em {largura_minima}px (< 1100px).")

        # o texto exibido tem que conter a URL inteira (so quebrada por
        # espacos de largura zero invisiveis) - nenhum caractere pode ter
        # sido perdido/truncado silenciosamente
        texto_exibido = tela._campo_rede_social.text().replace("​", "")
        assert texto_exibido == url_longa, "a URL exibida deveria ser identica a original, sem espaços de largura zero"
        print("OK: a URL inteira continua visível na ficha (só quebrada em várias linhas), nada foi cortado.")

        if not historico.empty:
            # os cards do historico nao mostram as observacoes (ficam na tela de leitura da proposta):
            # a URL longa la nao pode pesar no tamanho da lista
            largura_lista = tela._lista_historico.minimumSizeHint().width()
            assert largura_lista < 400, f"a lista de cards do historico pede {largura_lista}px de largura minima"
            print(f"OK: a lista de cards do histórico pede só {largura_lista}px de largura mínima, mesmo com a URL longa nas observações.")

        print("\nOK: texto longo sem espaço não estica mais o layout da Ficha de Cliente.")
    finally:
        clientes_mod.CAMINHO_XLSX = CAMINHO_XLSX
        propostas_mod.CAMINHO_XLSX = CAMINHO_XLSX
        tmp_path.unlink(missing_ok=True)


def main() -> None:
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    app = QApplication.instance() or QApplication(sys.argv)
    testar_dashboard_screen(app)
    testar_ficha_cliente_screen(app)
    testar_exclusao_cliente(app)
    testar_edicao_proposta(app)
    testar_texto_longo_sem_quebra(app)
    linha("TUDO OK")


if __name__ == "__main__":
    main()
