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
from core import bancos as bancos_mod
from core import clientes as clientes_mod
from core import dashboard as dashboard_mod
from core import data_store as bd
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendas as vendas_mod
from core.validators import apenas_digitos
from desktop.screens.dashboard_screen import DashboardScreen
from desktop.screens.ficha_cliente_screen import FichaClienteScreen
from desktop.widgets.card_da_venda import LARGURA_CARD


# as telas criadas pelo teste ficam vivas ate o fim, como no app (onde cada tela existe a sessao toda). Largadas, viram
# lixo com ciclos de referencia entre os widgets, e o coletor de lixo do Python, ao recolher, apagava pedacos do Qt fora
# de ordem e derrubava o processo (access violation) num momento qualquer do teste seguinte.
_TELAS_VIVAS: list = []


def _manter_viva(tela):
    _TELAS_VIVAS.append(tela)
    return tela


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def testar_dashboard_screen(app: QApplication) -> None:
    linha("1) DashboardScreen")

    tela = _manter_viva(DashboardScreen())
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

    tela = _manter_viva(FichaClienteScreen())
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
    assert tela._campo_nome.text() == cliente_com_proposta["CLIENTE"]
    # a ficha mostra o CPF formatado; o cadastro pode ter so os numeros: o que importa sao os digitos
    assert apenas_digitos(tela._campo_cpf.text()) == apenas_digitos(cliente_com_proposta["CPF/CNPJ"])
    assert tela._campo_vendedor.currentText() == (cliente_com_proposta["VENDEDOR"] or "")

    # isVisible() so reflete a realidade quando a janela foi de fato mostrada
    # na tela (nao e o caso aqui, em modo headless) - isHidden() reflete o
    # setVisible()/hide() que o proprio codigo da tela chamou, entao e o que
    # da pra verificar sem abrir uma janela de verdade.
    historico_esperado = propostas_mod.historico_por_cpf(cpf_com_proposta)
    vendas_esperadas = vendas_mod.vendas_do_cliente(cpf_com_proposta)
    antigas = historico_esperado[~historico_esperado["ID_VENDA"].isin({v.id for v in vendas_esperadas})]
    assert tela.lista_antigas.total() == len(antigas)
    assert sorted(c.item.proposta.indice for c in tela.lista_antigas.cards) == sorted(antigas.index)[:30]
    assert [c.venda.id for c in tela.lista_vendas.cards] == [v.id for v in vendas_esperadas][:30]
    assert tela.lista_antigas.isHidden() is antigas.empty
    assert tela._historico_vazio.isHidden() is True  # (o aviso "nenhuma proposta" e so do vendedor)
    print(
        f"Selecionar '{cliente_com_proposta['CLIENTE']}' preencheu a ficha, as vendas ({len(vendas_esperadas)}) e as "
        f"propostas de antes das vendas ({tela.lista_antigas.total()}, esperado {len(antigas)})."
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
    assert tela.lista_antigas.total() == 0
    assert tela.lista_antigas.isHidden() is True and tela._titulo_historico.isHidden() is True
    assert tela.lista_vendas.vazio.isHidden() is bool(vendas_mod.vendas_do_cliente(cliente_sem_proposta["CPF/CNPJ"]))
    print(f"Selecionar '{cliente_sem_proposta['CLIENTE']}' (sem propostas) mostrou o estado vazio corretamente.")

    print("\nOK: FichaClienteScreen busca/filtra/seleciona e exibe dados+histórico igual ao core.")


def testar_exclusao_cliente(app: QApplication) -> None:
    linha("3) Exclusão de cliente (copia temporaria)")

    tmp_path = CAMINHO_XLSX.parent / "_smoke_test_exclusao.xlsx"
    shutil.copy(CAMINHO_XLSX, tmp_path)
    clientes_mod.CAMINHO_XLSX = tmp_path
    propostas_mod.CAMINHO_XLSX = tmp_path
    bancos_mod.CAMINHO_XLSX = tmp_path

    # QMessageBox.question e modal (.exec() proprio) - em modo headless trava
    # esperando um clique que nunca vem. Troca por um stub que so responde "Sim".
    mensagens: list[str] = []
    original_question = QMessageBox.question

    def _stub_question(*args, **kwargs):
        mensagens.append(args[2] if len(args) > 2 else "")
        return QMessageBox.StandardButton.Yes

    QMessageBox.question = staticmethod(_stub_question)

    try:
        tela = _manter_viva(FichaClienteScreen())
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
    bancos_mod.CAMINHO_XLSX = tmp_path

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
        tela = _manter_viva(FichaClienteScreen())
        # uma proposta de uma venda com status, banco e valor preenchidos e que nao e de banco fechado (fechado so
        # aceita Aprovado/Efetivado) - editada pelo card da venda, que e onde a Ficha edita propostas agora
        # (e sem outra do mesmo cliente com a mesma data e valor: isso dispara a pergunta "possivel duplicata", que
        # foge do caminho feliz)
        todas = propostas_mod.listar_propostas()
        repetidas = todas.assign(_cpf=todas["CPF"].map(apenas_digitos)).duplicated(["_cpf", "DATA", "VALOR (R$)"], keep=False)
        ids_repetidos = set(todas.loc[repetidas, "ID_PROPOSTA"])
        alvo = next(
            ((venda, p) for venda in vendas_mod.listar_vendas() for p in venda.propostas
             if p.status in vendas_mod.STATUS_DA_PROPOSTA and p.banco and p.valor and not p.fechada
             and venda.status not in vendas_mod.DESFECHOS_DA_VENDA and p.id not in ids_repetidos),
            None,
        )
        assert alvo is not None, "nenhuma proposta de venda 'limpa' (status, banco e valor, banco nao fechado) encontrada"
        venda, proposta = alvo
        # nunca Negado: com todas negadas viria a pergunta "marcar como perdida?" (e o stub responde Sim)
        novo_status = propostas_mod.STATUS_APROVADO if proposta.status != propostas_mod.STATUS_APROVADO else "Pré-aprovado"
        antes = bd.ler_propostas(tmp_path)

        tela._selecionar_por_cpf(venda.cpf)
        assert apenas_digitos(tela._cpf_selecionado) == apenas_digitos(venda.cpf)
        assert tela.lista_vendas.editar_proposta(next(c.venda for c in tela.lista_vendas.cards if c.venda.id == venda.id), proposta)
        app.processEvents()
        card = tela.lista_vendas.card_aberto()
        formulario = card.formulario
        assert card.venda.id == venda.id and formulario is not None
        assert formulario._status.currentText() == proposta.status, (
            f"o formulario veio com status {formulario._status.currentText()!r}, esperado {proposta.status!r}"
        )
        formulario._status.setCurrentText(novo_status)
        formulario._observacoes.setPlainText("editado no smoke test")
        formulario._salvar()
        for _ in range(4):
            app.processEvents()
        assert tela.lista_vendas.editando is None and not tela.tem_edicao_pendente(), "gravar fecha o formulario"

        depois = bd.ler_propostas(tmp_path)
        editada = depois[depois["ID_PROPOSTA"] == proposta.id].iloc[0]
        assert editada["STATUS"] == novo_status and editada["OBSERVAÇÕES"] == "editado no smoke test"
        outras_antes = antes[antes["ID_PROPOSTA"] != proposta.id].reset_index(drop=True)
        outras_depois = depois[depois["ID_PROPOSTA"] != proposta.id].reset_index(drop=True)
        pd.testing.assert_frame_equal(outras_antes, outras_depois)  # as outras propostas nao mudaram
        print(f"OK: proposta {proposta.id} ({proposta.banco}) editada pelo card da venda na Ficha -> STATUS={editada['STATUS']}")

        if mensagens:
            raise AssertionError(f"nao deveria ter mostrado nenhuma mensagem de erro, mostrou: {mensagens}")

        print("\nOK: edição de proposta existente funciona de ponta a ponta (ficha → card da venda → gravação).")
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
    bancos_mod.CAMINHO_XLSX = tmp_path

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
        # e uma proposta de antes das vendas (fora de qualquer venda) com a URL nas observacoes: o card dela aparece
        propostas_mod.adicionar_proposta({"CPF": cpf, "BANCO": "Banco Longo", "EQUIPAMENTO": "Equipamento Longo",
                                          "VALOR (R$)": 1000, "STATUS": propostas_mod.STATUS_EM_ANALISE,
                                          "OBSERVAÇÕES": url_longa})

        tela = _manter_viva(FichaClienteScreen())
        tela._selecionar_por_cpf(cpf)

        # e o teste que realmente importa: a URL inteira (em Rede Social E em
        # Observacoes) nao pode forcar a ficha a pedir uma largura minima
        # gigante - antes da correcao, so o campo Rede Social sozinho ja
        # levava isso a quase 2000px
        largura_minima = tela.minimumSizeHint().width()
        assert largura_minima < 1100, f"minimumSizeHint ficou grande demais ({largura_minima}px) - layout vai estourar a tela"
        print(f"OK: minimumSizeHint da ficha com URL longa em Rede Social e Observações ficou em {largura_minima}px (< 1100px).")

        # a Rede Social mostra a URL crua no campo (como QLineEdit, não estica o layout -
        # ele rola por dentro, ao contrário de um QLabel com word-wrap); o botão do lado
        # e so um icone (largura fixa, nao pesa no layout) - o dominio CURTO (sem a URL
        # inteira) aparece no tooltip, que precisa continuar levando pro endereço INTEIRO
        assert tela._campo_rede_social.text() == url_longa, "o campo deveria mostrar a URL exata, como foi digitada"
        assert tela._botao_abrir_rede_social.toolTip() == "Abrir no maapp.com.br", "o tooltip deveria mostrar um link curto, não a URL crua"
        print("OK: a Rede Social mostra a URL crua no campo, com um ícone (tooltip 'Abrir no maapp.com.br') do lado.")

        if tela.lista_antigas.cards:
            # os cards do historico nao mostram as observacoes (ficam no formulario da proposta aberta):
            # a URL longa la nao pode pesar no tamanho dos cards - cada um pede so a largura minima de um card
            largura_card = max(c.minimumSizeHint().width() for c in tela.lista_antigas.cards)
            assert largura_card <= LARGURA_CARD + 40, f"um card do historico pede {largura_card}px de largura minima"
            print(f"OK: os cards do histórico pedem só {largura_card}px de largura mínima, mesmo com a URL longa nas observações.")
        else:
            print("(este cliente não tem propostas de antes das vendas: a largura dos cards é conferida em smoke_test_todas_as_propostas)")

        print("\nOK: texto longo sem espaço não estica mais o layout da Ficha de Cliente.")
    finally:
        clientes_mod.CAMINHO_XLSX = CAMINHO_XLSX
        propostas_mod.CAMINHO_XLSX = CAMINHO_XLSX
        bancos_mod.CAMINHO_XLSX = CAMINHO_XLSX
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
