"""Testa os status novos "Não efetivado" e "Encerrada": a regra de transição (só a partir de
"Aprovado"), as funções de "mesma venda em bancos diferentes" (propostas_da_mesma_venda,
propostas_em_aberto_da_mesma_venda, encerrar_propostas) e o fluxo da tela que pergunta se deve
encerrar as outras propostas quando uma é efetivada (o sinal `efetivada_agora`, o diálogo e o
Expansor). Dados FICTÍCIOS numa planilha temporária; preferências isoladas (nunca toca o registro
real do Windows).

Rodar com: venv/Scripts/python.exe scripts/smoke_test_mesma_venda.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl
from PySide6.QtWidgets import QApplication, QDialog, QWidget

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
from core import bancos as bancos_mod
from core import clientes as clientes_mod
from core import data_store as bd
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from core.validators import _digito_verificador_cpf
import desktop.widgets.expansor_proposta as expansor_mod
from desktop.widgets.encerrar_propostas_da_venda import perguntar_e_encerrar
from desktop.widgets.expansor_proposta import ExpansorDeProposta
from desktop.widgets.formulario_proposta import FormularioProposta
from desktop.widgets.lista_cartoes import ListaCartoes, ModeloCartoes


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _cpf(n: int) -> str:
    base = f"{123456780 + n:09d}"
    return base + _digito_verificador_cpf(base)


def _criar_planilha_vazia(caminho: Path) -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nome, colunas in (
        (bd.ABA_CLIENTES, bd.CLIENTES_COLUNAS),
        (bd.ABA_EQUIPAMENTOS, bd.EQUIPAMENTOS_COLUNAS),
        (bd.ABA_PROPOSTAS, bd.PROPOSTAS_COLUNAS),
        (bd.ABA_VENDEDORES, bd.VENDEDORES_COLUNAS),
    ):
        wb.create_sheet(nome).append(colunas)
    wb.save(caminho)


def _cliente(cpf: str, nome: str) -> None:
    clientes_mod.adicionar_cliente({"CPF/CNPJ": cpf, "CLIENTE": nome, "TIPO": "Cliente", "VENDEDOR": "ANA"})


def testar_transicao(arquivo: Path) -> None:
    linha("1) 'Não efetivado' só a partir de 'Aprovado'; 'Encerrada' pode ser escolhida à mão")
    cpf = _cpf(0)
    _cliente(cpf, "CLIENTE TRANSICAO")

    try:
        propostas_mod.adicionar_proposta(
            {"CPF": cpf, "VALOR (R$)": 1000, "EQUIPAMENTO": "EQ", "BANCO": "Banco A", "STATUS": "Não efetivado"}
        )
    except propostas_mod.ErroProposta as exc:
        assert "Aprovado" in str(exc)
    else:
        raise AssertionError("deveria recusar 'Não efetivado' numa proposta nova")

    indice = propostas_mod.adicionar_proposta(
        {"CPF": cpf, "VALOR (R$)": 1000, "EQUIPAMENTO": "EQ", "BANCO": "Banco A", "STATUS": "Em Análise"}
    )
    try:
        propostas_mod.atualizar_proposta(indice, {"STATUS": "Não efetivado"})
    except propostas_mod.ErroProposta as exc:
        assert "Aprovado" in str(exc)
    else:
        raise AssertionError("deveria recusar a partir de 'Em Análise'")

    propostas_mod.atualizar_proposta(indice, {"STATUS": "Aprovado"})
    propostas_mod.atualizar_proposta(indice, {"STATUS": "Não efetivado"})  # agora pode
    assert bd.ler_propostas(arquivo).loc[indice, "STATUS"] == "Não efetivado"
    print("OK: 'Não efetivado' só a partir de uma proposta que estava exatamente 'Aprovado' (nunca ao criar).")

    indice2 = propostas_mod.adicionar_proposta(
        {"CPF": cpf, "VALOR (R$)": 1500, "EQUIPAMENTO": "EQ2", "BANCO": "Banco B", "STATUS": "Em Análise"}
    )
    propostas_mod.atualizar_proposta(indice2, {"STATUS": "Encerrada"})
    assert bd.ler_propostas(arquivo).loc[indice2, "STATUS"] == "Encerrada"
    print("OK: 'Encerrada' pode ser escolhida direto no formulário (o admin pode ter outro motivo pra fechar).")


def testar_mesma_venda(arquivo: Path) -> None:
    linha("2) propostas_da_mesma_venda / propostas_em_aberto_da_mesma_venda / encerrar_propostas")
    cpf = _cpf(1)
    _cliente(cpf, "CLIENTE VENDA")
    i_x = propostas_mod.adicionar_proposta({"CPF": cpf, "VALOR (R$)": 2000, "EQUIPAMENTO": "Trator XYZ", "BANCO": "Banco X", "STATUS": "Aprovado"})
    i_y = propostas_mod.adicionar_proposta({"CPF": cpf, "VALOR (R$)": 2000, "EQUIPAMENTO": " trator xyz ", "BANCO": "Banco Y", "STATUS": "Em Análise"})
    i_z = propostas_mod.adicionar_proposta({"CPF": cpf, "VALOR (R$)": 2000, "EQUIPAMENTO": "TRATOR XYZ", "BANCO": "Banco Z", "STATUS": "Negado"})
    propostas_mod.adicionar_proposta({"CPF": cpf, "VALOR (R$)": 500, "EQUIPAMENTO": "Outro equipamento", "BANCO": "Banco W", "STATUS": "Em Análise"})

    todas = propostas_mod.propostas_da_mesma_venda(cpf, "Trator XYZ", ignorar_indice=i_x)
    assert set(todas.index) == {i_y, i_z}, set(todas.index)

    abertas = propostas_mod.propostas_em_aberto_da_mesma_venda(cpf, "Trator XYZ", ignorar_indice=i_x)
    assert set(abertas.index) == {i_y}, set(abertas.index)
    print("OK: agrupa por cliente+equipamento (sem diferenciar maiúsculas/espaços), ignora o índice atual e outro "
          "equipamento; só quem está 'em aberto' entra na segunda (a Negada, não).")

    n = propostas_mod.encerrar_propostas([i_y])
    assert n == 1
    depois = bd.ler_propostas(arquivo)
    assert depois.loc[i_y, "STATUS"] == "Encerrada"
    assert depois.loc[i_z, "STATUS"] == "Negado", "Negado nunca é mexido por isto"

    m = propostas_mod.encerrar_propostas([i_z, 999999])
    assert m == 0
    assert bd.ler_propostas(arquivo).loc[i_z, "STATUS"] == "Negado"
    assert propostas_mod.encerrar_propostas([]) == 0
    print("OK: encerrar_propostas muda só quem estava em aberto, numa única escrita; índice já resolvido, "
          "inexistente ou lista vazia é ignorado sem erro.")


def testar_sinal_efetivada_agora(arquivo: Path) -> None:
    linha("3) FormularioProposta emite 'efetivada_agora' só na TRANSIÇÃO para Efetivado")
    cpf = _cpf(2)
    _cliente(cpf, "CLIENTE SINAL")
    indice = propostas_mod.adicionar_proposta({"CPF": cpf, "VALOR (R$)": 1000, "EQUIPAMENTO": "EQ SINAL", "BANCO": "Banco A", "STATUS": "Aprovado"})

    capturados = []
    proposta = bd.ler_propostas(arquivo).loc[indice].to_dict()
    formulario = FormularioProposta(cpf, "CLIENTE SINAL", proposta=proposta, indice=indice)
    formulario.efetivada_agora.connect(lambda c, e, i: capturados.append((c, e, i)))
    formulario._habilitar_edicao()
    formulario._status.setCurrentText("Efetivado")
    formulario._salvar()
    assert capturados == [(cpf, "EQ SINAL", indice)], capturados

    capturados.clear()
    proposta2 = bd.ler_propostas(arquivo).loc[indice].to_dict()
    formulario2 = FormularioProposta(cpf, "CLIENTE SINAL", proposta=proposta2, indice=indice)
    formulario2.efetivada_agora.connect(lambda *a: capturados.append(a))
    formulario2._habilitar_edicao()
    formulario2._observacoes.setPlainText("só um comentário")
    formulario2._salvar()
    assert capturados == [], "já estava Efetivado: não pergunta de novo"
    print("OK: o sinal só dispara quando o status ACABA de virar Efetivado (nunca ao resalvar quem já era Efetivado).")


def testar_dialogo_perguntar_e_encerrar(arquivo: Path) -> None:
    linha("4) O diálogo 'perguntar_e_encerrar': cancelar não mexe em nada, aceitar encerra as marcadas")
    cpf = _cpf(3)
    _cliente(cpf, "CLIENTE DIALOGO")
    i_efetivada = propostas_mod.adicionar_proposta({"CPF": cpf, "VALOR (R$)": 4000, "EQUIPAMENTO": "Plantadeira", "BANCO": "Banco A", "STATUS": "Aprovado"})
    i_aberta = propostas_mod.adicionar_proposta({"CPF": cpf, "VALOR (R$)": 4000, "EQUIPAMENTO": "Plantadeira", "BANCO": "Banco B", "STATUS": "Em Análise"})
    i_negada = propostas_mod.adicionar_proposta({"CPF": cpf, "VALOR (R$)": 4000, "EQUIPAMENTO": "Plantadeira", "BANCO": "Banco C", "STATUS": "Negado"})

    parent = QWidget()
    chamou_exec = []
    orig_exec = QDialog.exec
    QDialog.exec = lambda self: (chamou_exec.append(True), QDialog.DialogCode.Accepted)[1]
    try:
        # sem nenhuma outra proposta em aberto pro mesmo equipamento: nem abre o diálogo
        perguntar_e_encerrar(parent, cpf, "Equipamento Que Não Existe", i_efetivada)
    finally:
        QDialog.exec = orig_exec
    assert chamou_exec == [], "sem candidata, o diálogo não pode nem abrir"

    QDialog.exec = lambda self: QDialog.DialogCode.Rejected
    try:
        perguntar_e_encerrar(parent, cpf, "Plantadeira", i_efetivada)
    finally:
        QDialog.exec = orig_exec
    assert bd.ler_propostas(arquivo).loc[i_aberta, "STATUS"] == "Em Análise", "cancelar não encerra nada"

    QDialog.exec = lambda self: QDialog.DialogCode.Accepted
    try:
        perguntar_e_encerrar(parent, cpf, "Plantadeira", i_efetivada)
    finally:
        QDialog.exec = orig_exec
    depois = bd.ler_propostas(arquivo)
    assert depois.loc[i_aberta, "STATUS"] == "Encerrada", "aceitar com a caixa pré-marcada encerra"
    assert depois.loc[i_negada, "STATUS"] == "Negado", "a negada nunca aparece no diálogo nem é tocada"
    print("OK: sem outra proposta em aberto o diálogo nem abre; cancelar não muda nada; aceitar (caixa "
          "pré-marcada) encerra só quem estava em aberto, nunca a negada.")


def testar_expansor_liga_o_sinal(arquivo: Path) -> None:
    linha("5) ExpansorDeProposta liga 'efetivada_agora' ao diálogo, com os dados certos")
    cpf = _cpf(4)
    _cliente(cpf, "CLIENTE EXPANSOR")
    indice = propostas_mod.adicionar_proposta({"CPF": cpf, "VALOR (R$)": 1000, "EQUIPAMENTO": "EQ EXP", "BANCO": "Banco A", "STATUS": "Aprovado"})

    lista = ListaCartoes()
    modelo = ModeloCartoes()
    lista.setModel(modelo)
    modelo.definir_itens([{"indice": indice, "cliente": "CLIENTE EXPANSOR", "status": "Aprovado", "data": "01/01/2026"}])

    def _obter(i: int):
        p = bd.ler_propostas(arquivo)
        return (cpf, "CLIENTE EXPANSOR", p.loc[i].to_dict()) if i in p.index else None

    chamados = []
    original = expansor_mod.perguntar_e_encerrar
    expansor_mod.perguntar_e_encerrar = lambda *a: chamados.append(a)
    try:
        expansor = ExpansorDeProposta(lista, modelo, _obter, lambda i: None)
        expansor._expandir_indice(indice)
        expansor._formulario._habilitar_edicao()
        expansor._formulario._status.setCurrentText("Efetivado")
        expansor._formulario._salvar()
    finally:
        expansor_mod.perguntar_e_encerrar = original
    assert len(chamados) == 1 and chamados[0][1:] == (cpf, "EQ EXP", indice), chamados
    print("OK: o Expansor chama o diálogo com (pai, cpf, equipamento, índice) certos, antes de recarregar a lista.")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    registro_antes = fx.instantaneo_do_registro()
    tmp = Path(tempfile.mkdtemp(prefix="_smoke_mesma_venda_"))
    fx.isolar_preferencias(tmp)
    try:
        arquivo = tmp / "controle.xlsx"
        _criar_planilha_vazia(arquivo)
        bancos_mod.CAMINHO_XLSX = clientes_mod.CAMINHO_XLSX = propostas_mod.CAMINHO_XLSX = vendedores_mod.CAMINHO_XLSX = equipamentos_mod.CAMINHO_XLSX = arquivo
        sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
        vendedores_mod.adicionar_vendedor("ANA")

        testar_transicao(arquivo)
        testar_mesma_venda(arquivo)
        testar_sinal_efetivada_agora(arquivo)
        testar_dialogo_perguntar_e_encerrar(arquivo)
        testar_expansor_liga_o_sinal(arquivo)

        linha("TUDO OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        assert fx.instantaneo_do_registro() == registro_antes, "não pode ter mexido no registro real"


if __name__ == "__main__":
    main()
