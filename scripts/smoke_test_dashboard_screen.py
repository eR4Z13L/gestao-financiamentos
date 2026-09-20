"""Testa a tela do Dashboard (desktop/screens/dashboard_screen.py e os widgets dela) sem abrir uma janela de
verdade (QT_QPA_PLATFORM=offscreen), no estilo do Windows 11, nos DOIS temas, como ADMIN e como VENDEDOR
(as duas fontes de leitura simuladas, sem rede).

Tudo com uma planilha 100% FICTICIA (scripts/fixture_ficticia.py, versao volumosa), preferencias num .ini
temporario e o Google desligado (ver scripts/ambiente_de_teste.py) - nada real. Os numeros esperados vem de
core/dashboard.py (testado a parte, sem Qt): aqui se confere que a TELA mostra exatamente isso, que cada linha
clicavel leva a pessoa ao lugar certo e o que so o ADMIN (ou so o VENDEDOR) ve.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_dashboard_screen.py
"""

from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")  # sem tela o Qt nao acha fontes

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QWidget

import fixture_ficticia as fx
from ambiente_de_teste import Ambiente, Mensagens
from core import clientes as clientes_mod
from core import dashboard as dash
from core import propostas as propostas_mod
from core.formatting import formatar_reais
from core.validators import apenas_digitos
from desktop.theme import CORES_STATUS, PALETAS, TEMA_CLARO, TEMA_ESCURO
from desktop.widgets.linha_clicavel import LinhaClicavel
from desktop.widgets.lista_cartoes import chave_cor_etapa
from desktop.widgets.linha_de_qualidade import LinhaDeQualidade
from desktop.widgets.linha_para_reenviar import LinhaParaReenviar
from desktop.widgets.tabela_de_painel import COR_AVISO, COR_ERRO

TEMAS = (TEMA_ESCURO, TEMA_CLARO)
NOME_DA_OUTRA_VENDEDORA = "Vendedora Teste Dois"


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


# -- auxiliares ------------------------------------------------------------------------------------


def _widgets(cartao) -> list[QWidget]:
    return [cartao.corpo.itemAt(i).widget() for i in range(cartao.corpo.count()) if cartao.corpo.itemAt(i).widget() is not None]


def _do_periodo(propostas: pd.DataFrame, periodo: str, hoje) -> pd.DataFrame:
    return dash.filtrar_por_periodo(propostas, dash.intervalo_do_periodo(periodo, hoje))


def _indices_da_lista(tela_propostas) -> set[int]:
    return {int(item["indice"]) for item in tela_propostas._modelo._todos}


def _clicar(widget: QWidget, ponto: QPoint | None = None) -> None:
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto if ponto is not None else widget.rect().center())


def _cliques_no_cabecalho(tabela, coluna: int) -> None:
    cabecalho = tabela.horizontalHeader()
    _clicar(cabecalho.viewport(), QPoint(cabecalho.sectionViewportPosition(coluna) + 8, cabecalho.height() // 2))


def _contar_pixels(imagem: QImage, cor: QColor, area: QRect, tolerancia: int = 6) -> int:
    total = 0
    for y in range(max(area.top(), 0), min(area.bottom() + 1, imagem.height())):
        for x in range(max(area.left(), 0), min(area.right() + 1, imagem.width())):
            c = imagem.pixelColor(x, y)
            if abs(c.red() - cor.red()) <= tolerancia and abs(c.green() - cor.green()) <= tolerancia and abs(c.blue() - cor.blue()) <= tolerancia:
                total += 1
    return total


def _pct(valor: float) -> str:
    """Como o Dashboard escreve um percentual (uma casa, virgula): "27,0%". Independente do codigo da tela, de proposito."""
    return f"{valor:.1f}".replace(".", ",") + "%"


def _taxa_do_texto(texto: str) -> float:
    return -1.0 if texto == "—" else float(texto.rstrip("%").replace(",", "."))


def _dashboard(janela):
    return janela._tela_dashboard


def bd_todas(amb: Ambiente) -> pd.DataFrame:
    """Todas as propostas da planilha fictícia, sem filtro de vendedor (pra comparar com o que o vendedor ve)."""
    from core import data_store as bd

    return bd.ler_propostas(amb.caminho)


# -- testes ---------------------------------------------------------------------------------------------


def testar_numeros_do_topo(amb: Ambiente, msgs: Mensagens, tema: str) -> None:
    linha(f"1) Numeros do topo [{tema}]")
    janela = amb.nova_janela("admin", tema)
    tela = _dashboard(janela)
    propostas = propostas_mod.listar_propostas()
    topo = dash.indicadores_do_topo(propostas)

    ea = topo["em_analise"]
    assert tela._card_em_analise.valor() == str(ea["quantidade"])
    detalhe = formatar_reais(ea["valor"]) + (f" · só {ea['com_valor']} têm valor" if 0 < ea["com_valor"] < ea["quantidade"] else "")
    assert tela._card_em_analise.detalhe() == detalhe
    print(f"OK: Em análise = {ea['quantidade']} ({detalhe}).")

    efetivadas = topo["a_efetivar"]["efetivadas"]
    assert tela._card_a_efetivar.valor() == str(topo["a_efetivar"]["quantidade"])
    assert tela._card_a_efetivar.detalhe() == f"{efetivadas} {'efetivada' if efetivadas == 1 else 'efetivadas'} até agora"
    assert tela._card_a_efetivar.detalhe_em_aviso() == (efetivadas == 0)
    taxa = topo["taxa_aprovacao"]
    assert tela._card_taxa.valor() == _pct(taxa["percentual"]) and tela._card_taxa.detalhe() == f"{taxa['aprovadas']} de {taxa['decididas']} decididas"
    assert "aprovadas + negadas" in tela._card_taxa.toolTip() and "pré-aprovado" in tela._card_taxa.toolTip()
    mediano = topo["valor_mediano"]
    assert tela._card_mediano.valor() == formatar_reais(mediano["mediana"]) and tela._card_mediano.detalhe() == f"{mediano['com_valor']} de {mediano['total']} com valor"
    assert "Taxa de reprovação" not in [c.titulo() for c in (tela._card_em_analise, tela._card_a_efetivar, tela._card_taxa, tela._card_mediano)]
    assert all(c.comparacao() == "" for c in (tela._card_em_analise, tela._card_a_efetivar, tela._card_taxa, tela._card_mediano)), "Tudo nao compara"
    print("OK: os 4 numeros (a efetivar x efetivadas, taxa sobre as decididas com a formula no tooltip, mediana), sem 'taxa de reprovacao'.")

    # o aviso "0 efetivadas": ambar e em destaque, de verdade (a cor sai do QSS do tema)
    tela._propostas = fx.montar_propostas(dict(STATUS="Aprovado"), dict(STATUS="Negado"))
    tela._atualizar()
    assert tela._card_a_efetivar.detalhe() == "0 efetivadas até agora" and tela._card_a_efetivar.detalhe_em_aviso()
    rotulo = tela._card_a_efetivar._detalhe
    esperado = QColor(CORES_STATUS[tema]["em_analise"]["texto"])
    assert _contar_pixels(rotulo.grab().toImage(), esperado, QRect(0, 0, rotulo.width(), rotulo.height()), 40) > 10, "o aviso deveria estar na cor ambar do tema"
    tela._propostas = propostas
    tela._atualizar()
    print("OK: '0 efetivadas até agora' aparece em destaque de aviso (ambar do tema).")

    # a pagina ROLA (tabelas nao ficam espremidas)
    janela.resize(1200, 800)
    QApplication.processEvents()
    assert tela._rolagem.verticalScrollBar().maximum() > 0, "o conteudo e maior que a tela: tem que rolar"
    print("OK: a pagina rola dentro de uma area de rolagem.")
    msgs.exigir_sem_erros("numeros do topo")


def testar_periodo_e_comparacao(amb: Ambiente, msgs: Mensagens, tema: str) -> None:
    linha(f"2) Periodo (vale pra todos os blocos) e comparacao [{tema}]")
    janela = amb.nova_janela("admin", tema)
    tela = _dashboard(janela)
    propostas = propostas_mod.listar_propostas()
    hoje = tela._hoje()
    assert tela.periodo() == dash.PERIODO_PADRAO == dash.PERIODO_TUDO and tela._seletor.botao("tudo").isChecked()

    for periodo, referencia in (("7d", "os 7 dias anteriores"), ("30d", "os 30 dias anteriores"), ("mes", "o mês anterior"), ("hoje", "ontem")):
        _clicar(tela._seletor.botao(periodo))
        assert tela.periodo() == periodo and tela._seletor.botao(periodo).isChecked() and not tela._seletor.botao("tudo").isChecked()
        no_periodo = _do_periodo(propostas, periodo, hoje)
        topo = dash.indicadores_do_topo(no_periodo)
        # o numero do topo, o funil, o resumo e o por banco vem TODOS do mesmo recorte
        assert tela._card_em_analise.valor() == str(topo["em_analise"]["quantidade"])
        assert [(e.etapa, e.quantidade) for e in tela._funil.etapas()] == [(e.etapa, e.quantidade) for e in dash.funil_por_etapa(no_periodo)]
        assert tela._texto_do_resumo == dash.resumo_para_copiar(no_periodo, periodo)
        assert tela._tabela_bancos.total_de_linhas() == len(dash.por_banco(no_periodo))
        assert [w.text() for w in _widgets(tela._cartao_atencao) if isinstance(w, LinhaClicavel)] == [i.texto for i in dash.precisa_de_atencao(no_periodo, hoje=hoje)]

        anterior = dash.filtrar_por_periodo(propostas, dash.intervalo_anterior(periodo, hoje))
        comparavel = dash.comparar_periodos(topo, dash.indicadores_do_topo(anterior))
        texto = tela._card_em_analise.comparacao()
        if comparavel is None:
            assert texto == "", f"{periodo}: sem dados nos dois periodos nao ha comparacao (veio {texto!r})"
        else:
            d = comparavel["em_analise"]
            esperado = f"= sem mudança vs. {referencia}" if d == 0 else f"{'▲' if d > 0 else '▼'} {d:+d} vs. {referencia}"
            assert texto == esperado, (texto, esperado)
    print("OK: 7 dias / 30 dias / mes / hoje: numeros, funil, resumo, atencao e por banco mudam juntos; a comparacao so aparece com dados nos dois periodos.")

    # comparacao com valores conhecidos: 3 em analise agora contra 1 antes -> ▲ +2
    hoje_fixo = hoje
    tela._propostas = fx.montar_propostas(
        *[dict(STATUS="Em Análise", DATA=pd.Timestamp(hoje_fixo - timedelta(days=1))) for _ in range(3)],
        dict(STATUS="Em Análise", DATA=pd.Timestamp(hoje_fixo - timedelta(days=8))),
        dict(STATUS="Negado", DATA=pd.Timestamp(hoje_fixo - timedelta(days=9))),
    )
    tela.definir_periodo("7d")
    assert tela._card_em_analise.comparacao() == "▲ +2 vs. os 7 dias anteriores", tela._card_em_analise.comparacao()
    assert tela._card_taxa.comparacao() == "", "sem propostas decididas nos 7 dias atuais a taxa nao compara"
    tela._propostas = fx.montar_propostas(dict(DATA=pd.Timestamp(hoje_fixo - timedelta(days=1))), dict(DATA=pd.Timestamp(hoje_fixo - timedelta(days=8))))
    tela._atualizar()
    assert tela._card_em_analise.comparacao() == "= sem mudança vs. os 7 dias anteriores"
    print("OK: a comparacao (mais 2 / sem mudanca) e a taxa que nao compara quando falta dado.")

    # periodo SEM nenhuma proposta: tudo zerado, sem quebrar, com as mensagens certas
    tela._propostas = propostas
    tela._hoje = lambda: hoje + timedelta(days=400)
    tela._atualizar()  # (o periodo continua "7 dias": definir_periodo("7d") aqui seria um no-op)
    assert tela._card_em_analise.valor() == "0" and tela._card_em_analise.detalhe() == "Nenhuma proposta em análise"
    assert tela._card_taxa.valor() == "—" and tela._card_mediano.valor() == "—" and tela._card_mediano.detalhe() == "0 de 0 com valor"
    assert tela._texto_do_resumo == "Nenhuma proposta nos últimos 7 dias."
    assert all(e.quantidade == 0 for e in tela._funil.etapas()) and tela._tabela_bancos.total_de_linhas() == 0
    mensagem = _widgets(tela._cartao_atencao)[0]
    assert isinstance(mensagem, QLabel) and mensagem.text() == "Tudo em dia: nenhuma proposta pedindo atenção nos últimos 7 dias."
    assert mensagem.property("role") == "positivo"
    assert all(c.percentual is None for c in dash.qualidade_dos_dados(tela._no_periodo))
    assert [w.text() for w in _widgets(tela._cartao_reenviar)] == ["Nenhum cliente com todas as propostas negadas nos últimos 7 dias."]
    tela._hoje = lambda: hoje
    tela.definir_periodo("tudo")
    print("OK: periodo sem dados -> zeros, '—', 'Tudo em dia' e as mensagens vazias de cada bloco.")
    msgs.exigir_sem_erros("periodo")


def testar_atencao_e_cliques(amb: Ambiente, msgs: Mensagens, tema: str) -> None:
    linha(f"3) Precisa de atencao, funil, por banco e qualidade: cada clique leva pra Todas as Propostas ja filtrada [{tema}]")
    janela = amb.nova_janela("admin", tema)
    tela = _dashboard(janela)
    propostas = propostas_mod.listar_propostas()
    hoje = tela._hoje()
    tela_propostas = janela._tela_propostas
    itens = dash.precisa_de_atencao(propostas, hoje=hoje)
    assert len(itens) >= 4, "a fixture volumosa deveria ter pelo menos 4 grupos pedindo atencao"

    linhas = [w for w in _widgets(tela._cartao_atencao) if isinstance(w, LinhaClicavel)]
    assert [l.text() for l in linhas] == [i.texto for i in itens]
    assert linhas[0].tom() == dash.TOM_PROCESSO and linhas[-1].tom() == dash.TOM_DADOS
    for item, linha_clicavel in zip(itens, linhas):
        janela.ir_para("dashboard")
        linha_clicavel.click()
        assert janela.chave_atual() == "propostas", "clicar leva a Todas as Propostas"
        assert tela_propostas.chip_do_filtro_visivel()
        assert tela_propostas._rotulo_do_chip.text() == f"Filtro do dashboard: {item.rotulo_do_filtro}"
        assert _indices_da_lista(tela_propostas) == set(item.indices), f"{item.chave}: a lista tem que ter EXATAMENTE as propostas do item"
        assert tela_propostas._contador.text().startswith(f"{item.quantidade} proposta(s)")
    print(f"OK: cada um dos {len(itens)} itens abre Todas as Propostas so com as propostas dele (mesma contagem) e mostra o chip do filtro.")

    # o clique ZERA a busca e os demais filtros (senao a lista podia vir vazia sem a pessoa saber por que)
    janela.ir_para("propostas")
    tela_propostas._busca.setText("texto que nao existe em nenhuma proposta")
    tela_propostas._filtro_banco.setCurrentIndex(1)
    assert len(tela_propostas._modelo._todos) == 0
    janela.ir_para("dashboard")
    linhas[0].click()
    assert tela_propostas._busca.text() == "" and tela_propostas._filtro_banco.currentIndex() == 0
    assert _indices_da_lista(tela_propostas) == set(itens[0].indices), "so o filtro do dashboard vale"
    print("OK: o clique zera a busca e os demais filtros: a lista mostra exatamente o que o item promete.")

    # tirar o filtro: o chip so remove ELE; 'Limpar filtros' tambem
    total = len(tela_propostas._todas)
    tela_propostas._botao_remover_chip.click()
    assert not tela_propostas.chip_do_filtro_visivel() and tela_propostas.filtro_do_dashboard() is None
    assert len(tela_propostas._modelo._todos) == total
    janela.ir_para("dashboard")
    linhas[0].click()
    assert tela_propostas.chip_do_filtro_visivel() and tela_propostas._botao_limpar_filtros.isEnabled()
    tela_propostas._botao_limpar_filtros.click()
    assert not tela_propostas.chip_do_filtro_visivel() and len(tela_propostas._modelo._todos) == total
    print("OK: 'Remover filtro' e 'Limpar filtros' tiram o filtro do dashboard e a lista volta inteira.")

    # o periodo escolhido vai junto, nos campos de data de Todas as Propostas
    janela.ir_para("dashboard")
    tela.definir_periodo("30d")
    item30 = dash.precisa_de_atencao(_do_periodo(propostas, "30d", hoje), hoje=hoje)[0]
    [w for w in _widgets(tela._cartao_atencao) if isinstance(w, LinhaClicavel)][0].click()
    inicio, fim = dash.intervalo_do_periodo("30d", hoje)
    assert tela_propostas._filtro_de.texto() == inicio.strftime("%d/%m/%Y") and tela_propostas._filtro_ate.texto() == fim.strftime("%d/%m/%Y")
    assert _indices_da_lista(tela_propostas) == set(item30.indices), "com o periodo, so as propostas do periodo"
    tela_propostas._botao_limpar_filtros.click()
    assert tela_propostas._filtro_de.texto() == "" and tela_propostas._filtro_ate.texto() == ""
    janela.ir_para("dashboard")
    tela.definir_periodo("tudo")
    print("OK: o periodo do dashboard vira 'Período de / até' em Todas as Propostas (e some ao limpar).")

    # funil: clicar na barra de uma etapa
    funil = tela._funil
    for etapa in (propostas_mod.ETAPA_NEGADO, propostas_mod.ETAPA_EM_ANALISE):
        janela.ir_para("dashboard")
        retangulo = funil.retangulo_da_etapa(etapa)
        _clicar(funil, QPoint(int(retangulo.center().x()), int(retangulo.center().y())))
        esperado = {int(i) for i in propostas.index[propostas["STATUS"].map(propostas_mod.etapa_status) == etapa]}
        assert janela.chave_atual() == "propostas" and _indices_da_lista(tela_propostas) == esperado, etapa
        assert tela_propostas._rotulo_do_chip.text() == f"Filtro do dashboard: Etapa: {dash.ROTULOS_DE_ETAPA[etapa]}"
    tela_propostas._botao_limpar_filtros.click()
    print("OK: clicar numa barra do funil abre a lista so com as propostas daquela etapa.")

    # so as etapas com propostas sao clicaveis; teclado tambem funciona
    emitidas: list[str] = []
    funil.etapa_clicada.connect(emitidas.append)
    janela.ir_para("dashboard")
    funil.definir_etapas([dash.EtapaDoFunil(propostas_mod.ETAPA_EM_ANALISE, "Em análise", 0, 0.0, 0), dash.EtapaDoFunil(propostas_mod.ETAPA_NEGADO, "Negado", 2, 0.0, 0)])
    zero = funil.retangulo_da_etapa(propostas_mod.ETAPA_EM_ANALISE)
    _clicar(funil, QPoint(int(zero.center().x()), int(zero.center().y())))
    assert emitidas == [] and janela.chave_atual() == "dashboard", "etapa sem propostas nao leva a lugar nenhum"
    funil.setFocus()
    QTest.keyClick(funil, Qt.Key.Key_Down)
    QTest.keyClick(funil, Qt.Key.Key_Return)
    assert emitidas == [propostas_mod.ETAPA_NEGADO], "pelo teclado: seta pra baixo e Enter"
    funil.etapa_clicada.disconnect(emitidas.append)
    tela._atualizar()
    print("OK: etapa vazia nao e clicavel; o funil responde a seta e Enter.")

    # por banco: clicar numa linha filtra pelo banco
    janela.ir_para("dashboard")
    tabela = tela._tabela_bancos
    banco_clicado = None
    for linha_da_tabela in range(tabela.total_de_linhas()):
        chave, nome = tabela.payload_da_linha(linha_da_tabela)
        if chave and nome.upper() != "TODOS":
            banco_clicado = (chave, nome, linha_da_tabela)
            break
    chave, nome, posicao = banco_clicado
    _clicar(tabela.viewport(), tabela.centro_da_linha(posicao))
    esperado = {int(i) for i in propostas.index[propostas["BANCO"].fillna("").str.strip().str.upper() == chave]}
    assert janela.chave_atual() == "propostas" and _indices_da_lista(tela_propostas) == esperado
    assert tela_propostas._rotulo_do_chip.text() == f"Filtro do dashboard: Banco: {nome}"
    tela_propostas._botao_limpar_filtros.click()
    # ... e a linha "(sem banco)" filtra as sem banco
    janela.ir_para("dashboard")
    for linha_da_tabela in range(tabela.total_de_linhas()):
        if tabela.payload_da_linha(linha_da_tabela)[0] == "":
            _clicar(tabela.viewport(), tabela.centro_da_linha(linha_da_tabela))
            break
    sem_banco = {int(i) for i in propostas.index[propostas["BANCO"].fillna("").str.strip() == ""]}
    assert _indices_da_lista(tela_propostas) == sem_banco and tela_propostas._rotulo_do_chip.text() == "Filtro do dashboard: Sem banco informado"
    tela_propostas._botao_limpar_filtros.click()
    print("OK: clicar num banco (ou em '(sem banco)') abre so as propostas dele.")

    # qualidade dos dados: 'Ver N' abre as pendentes
    janela.ir_para("dashboard")
    linhas_q = [w for w in _widgets(tela._cartao_qualidade) if isinstance(w, LinhaDeQualidade)]
    assert [l.chave() for l in linhas_q] == [dash.ATENCAO_SEM_VALOR, dash.FILTRO_SEM_MESES, dash.FILTRO_SEM_BANCO, dash.FILTRO_SEM_STATUS]
    campos = {c.chave: c for c in dash.qualidade_dos_dados(propostas)}
    for l in linhas_q:
        campo = campos[l.chave()]
        assert l.texto_do_valor() == (f"{campo.percentual:.0f}% · {campo.preenchidos} de {campo.total}")
        assert l.botao_de_pendentes().isHidden() == (not campo.indices_pendentes)
        if campo.indices_pendentes:
            janela.ir_para("dashboard")
            l.botao_de_pendentes().click()
            assert _indices_da_lista(tela_propostas) == set(campo.indices_pendentes) and janela.chave_atual() == "propostas", l.chave()
            tela_propostas._botao_limpar_filtros.click()
    print("OK: 'Ver N' de cada campo abre so as propostas com aquele campo em branco.")

    # com edicao NAO salva em algum card: pergunta antes de sair do que esta editando
    janela.ir_para("propostas")
    tela_propostas.abrir_nova_proposta()
    tela_propostas._expansor.formulario()._observacoes.setPlainText("rascunho de teste")
    assert janela.tem_edicao_pendente()
    janela.ir_para("dashboard")
    msgs.limpar()
    msgs.resposta_pergunta = QMessageBox.StandardButton.No
    linhas[0].click()
    assert janela.chave_atual() == "dashboard" and msgs.ultima()[0] == "question" and "não foram salvas" in msgs.ultima()[2]
    msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
    linhas[0].click()
    assert janela.chave_atual() == "propostas" and not janela.tem_edicao_pendente()
    tela_propostas._botao_limpar_filtros.click()
    print("OK: com uma edicao nao salva, o clique pergunta antes (Não = continua no Dashboard, Sim = segue e descarta).")
    msgs.exigir_sem_erros("cliques")


def testar_por_banco(amb: Ambiente, msgs: Mensagens, tema: str) -> None:
    linha(f"4) Por banco: ordenavel, avisos e mini-barra [{tema}]")
    janela = amb.nova_janela("admin", tema)
    tela = _dashboard(janela)
    tabela = tela._tabela_bancos
    propostas = propostas_mod.listar_propostas()
    esperado = dash.por_banco(propostas)

    enviadas = [int(t) for t in tabela.textos_da_coluna(1)]
    assert sorted(enviadas, reverse=True) == enviadas and sum(enviadas) == len(propostas), "mais enviadas primeiro; nenhuma proposta some"
    assert sorted(tabela.textos_da_coluna(0)) == sorted(esperado["Banco"]), "as 3 grafias de 'Hubcred BV' viram uma linha so"
    print("OK: as linhas do core, mais enviadas primeiro, e a soma das enviadas fecha com o total de propostas.")

    _cliques_no_cabecalho(tabela, 0)
    nomes = [n.casefold() for n in tabela.textos_da_coluna(0)]
    assert nomes == sorted(nomes), "1o clique no cabecalho: A-Z"
    _cliques_no_cabecalho(tabela, 0)
    nomes = [n.casefold() for n in tabela.textos_da_coluna(0)]
    assert nomes == sorted(nomes, reverse=True), "2o clique: Z-A"
    _cliques_no_cabecalho(tabela, 5)
    taxas = [_taxa_do_texto(t) for t in tabela.textos_da_coluna(5)]
    assert taxas == sorted(taxas), f"a taxa ordena como NUMERO ('100,0%' depois de '9,5%'), veio {taxas}"
    _cliques_no_cabecalho(tabela, 5)
    taxas = [_taxa_do_texto(t) for t in tabela.textos_da_coluna(5)]
    assert taxas == sorted(taxas, reverse=True)
    print("OK: clicar no cabecalho ordena (texto A-Z / Z-A, e a taxa como numero nos dois sentidos).")

    # "Todos" e "(sem banco)" viram 'revisar' e ficam fora da taxa; sem-aprovacao com 5+ enviadas e sinalizado
    linhas = {tabela.texto_da_celula(i, 0): i for i in range(tabela.total_de_linhas())}
    for nome in ("Todos", dash.ROTULO_SEM_BANCO):
        i = linhas[nome]
        assert tabela.texto_da_celula(i, 6) == "Revisar" and tabela.texto_da_celula(i, 5) == "—" and tabela.barra_da_celula(i, 5) is None
        assert tabela.cor_da_celula(i, 6) == COR_ERRO
    tela._propostas = fx.montar_propostas(
        *[dict(BANCO="Portobank", STATUS="Negado") for _ in range(5)], dict(BANCO="Santander", STATUS="Aprovado"), dict(BANCO="Santander", STATUS="Negado"), dict(BANCO="Mova HTM", STATUS="Aprovado")
    )
    tela._atualizar()
    linhas = {tabela.texto_da_celula(i, 0): i for i in range(tabela.total_de_linhas())}
    porto, santander, mova = linhas["Portobank"], linhas["Santander"], linhas["Mova HTM"]
    assert tabela.texto_da_celula(porto, 6) == "Sem aprovações" and tabela.cor_da_celula(porto, 6) == COR_AVISO
    assert tabela.texto_da_celula(santander, 6) == "" and tabela.texto_da_celula(mova, 5) == "100,0%" and tabela.texto_da_celula(santander, 5) == "50,0%"
    print("OK: 'Todos' e '(sem banco)' = Revisar (fora da taxa); 5 enviadas sem nenhuma aprovada = 'Sem aprovações' em ambar.")

    # a mini-barra e DESENHADA: verde proporcional na celula da taxa; sem taxa nao ha barra
    QApplication.processEvents()
    assert tabela.isVisible(), "a tela do Dashboard tem que estar na frente (senao a foto do widget sai incompleta)"
    imagem = tabela.viewport().grab().toImage()
    verde = QColor(CORES_STATUS[tema]["aprovado"]["faixa"])

    def barra_em(linha_: int) -> int:
        retangulo = tabela.visualRect(tabela._modelo.index(linha_, 5))
        return _contar_pixels(imagem, verde, QRect(retangulo.left(), retangulo.bottom() - 12, retangulo.width(), 10), 8)

    assert barra_em(mova) > barra_em(santander) > barra_em(porto) == 0, (barra_em(mova), barra_em(santander), barra_em(porto))
    print("OK: a mini-barra da taxa tem o tamanho proporcional (100% > 50% > 0%), na cor de 'aprovado' do tema.")
    msgs.exigir_sem_erros("por banco")


def testar_para_reenviar(amb: Ambiente, msgs: Mensagens, tema: str) -> None:
    linha(f"5) Para reenviar: 'Duplicar' abre a Ficha com a Nova proposta preenchida [{tema}]")
    janela = amb.nova_janela("admin", tema)
    tela = _dashboard(janela)
    propostas = propostas_mod.listar_propostas()
    esperados = dash.para_reenviar(propostas)
    assert len(esperados) >= 9, "a fixture tem (por construcao) 9 ou mais clientes com todas as propostas negadas"

    linhas = [w for w in _widgets(tela._cartao_reenviar) if isinstance(w, LinhaParaReenviar)]
    extra = [w for w in _widgets(tela._cartao_reenviar) if isinstance(w, QLabel)]
    assert len(linhas) == 8 and len(extra) == 1 and extra[0].text().startswith(f"e mais {len(esperados) - 8}"), "8 linhas e 'e mais N'"
    assert [l.item().cpf for l in linhas] == [e.cpf for e in esperados[:8]]
    primeira = linhas[0]
    assert "negada" in primeira.texto_das_negadas() and primeira.texto_das_sugestoes().startswith("Ainda não tentou: ")
    assert f"{len(esperados)} clientes com todas as propostas negadas" in tela._cartao_reenviar.legenda()
    print("OK: os clientes de core (mais recentes primeiro), bancos tentados e os que faltam, e 'e mais N' depois de 8.")

    # Duplicar: abre a ficha do cliente com o card "Nova proposta" preenchido pela regra de duplicar
    item = primeira.item()
    original = propostas.loc[item.indice_da_proposta]
    primeira.botao_duplicar().click()
    assert janela.chave_atual() == "ficha"
    ficha = janela._tela_ficha
    assert apenas_digitos(ficha._cpf_selecionado) == item.cpf and ficha._nome_label.text() == item.cliente
    assert ficha._expansor.eh_rascunho() and ficha._modelo_historico.tem_rascunho()
    formulario = ficha._expansor.formulario()
    assert formulario._equipamento.currentText() == original["EQUIPAMENTO"] and formulario._banco.currentText() == "", "o banco fica em branco: quem duplica escolhe"
    assert formulario._status.currentText() == propostas_mod.STATUS_EM_ANALISE, "nunca herda 'Negado'"
    if not pd.isna(original["VALOR (R$)"]):
        assert formulario._valor.value() == original["VALOR (R$)"]
    assert len(propostas_mod.listar_propostas()) == len(propostas), "duplicar nao grava nada ate confirmar"
    print("OK: Duplicar abre a Ficha do cliente com 'Nova proposta' (equipamento e valor da mais recente, sem banco, em análise) e nada e gravado.")

    # confirmar: cria uma proposta NOVA e a original continua negada; o cliente sai da lista de reenvio
    if formulario._valor.value() == 0:
        formulario._valor.setValue(10000)
    formulario._banco.setCurrentText("Smart")
    formulario._salvar()
    depois = propostas_mod.listar_propostas()
    assert len(depois) == len(propostas) + 1
    nova = depois.loc[max(depois.index)]
    assert nova["BANCO"] == "Smart" and nova["STATUS"] == propostas_mod.STATUS_EM_ANALISE and nova["CPF"] == original["CPF"]
    assert depois.loc[item.indice_da_proposta, "STATUS"] == propostas_mod.STATUS_NEGADO, "a original nao muda"
    janela.ir_para("dashboard")  # voltar ao Dashboard rele os dados (as outras telas gravaram)
    assert item.cpf not in [l.item().cpf for l in _widgets(tela._cartao_reenviar) if isinstance(l, LinhaParaReenviar)], "agora tem proposta em analise: sai da lista"
    propostas_mod.remover_proposta(max(depois.index))  # devolve a fixture ao que era (o proximo tema usa a mesma)
    print("OK: gravar cria uma proposta nova (Smart, em análise), a original segue negada e o cliente sai de 'Para reenviar' ao voltar ao Dashboard.")

    # clicar no nome abre a ficha; cliente sem cadastro nao duplica
    janela.ir_para("dashboard")
    tela._carregar_dados()
    outra = [w for w in _widgets(tela._cartao_reenviar) if isinstance(w, LinhaParaReenviar)][0]
    outra.botao_cliente().click()
    assert janela.chave_atual() == "ficha" and apenas_digitos(janela._tela_ficha._cpf_selecionado) == outra.item().cpf and not janela._tela_ficha._expansor.eh_rascunho()
    orfa = LinhaParaReenviar(dash.ClienteParaReenviar("12345678900", "", False, 0, 1, ("Santander",), (), None))
    assert not orfa.botao_duplicar().isEnabled() and not orfa.botao_cliente().isEnabled() and "sem cadastro" in orfa.botao_cliente().text().lower()
    assert orfa.texto_das_sugestoes() == "Já tentou todos os bancos conhecidos" and "não tem cliente cadastrado" in orfa.botao_duplicar().toolTip()
    print("OK: o nome abre a ficha; sem cadastro, os botoes ficam desativados com o motivo no tooltip.")

    # o periodo olha a ULTIMA proposta do cliente
    janela.ir_para("dashboard")
    tela.definir_periodo("7d")
    hoje = tela._hoje()
    esperados_7d = dash.para_reenviar(propostas, dash.intervalo_do_periodo("7d", hoje))
    assert [l.item().cpf for l in _widgets(tela._cartao_reenviar) if isinstance(l, LinhaParaReenviar)] == [e.cpf for e in esperados_7d[:8]]
    tela.definir_periodo("tudo")

    # o VENDEDOR nao cria proposta: nem o bloco existe, e a rota "Duplicar" por codigo nao faz nada
    vendedor = amb.nova_janela("vendedor", tema)
    assert not hasattr(_dashboard(vendedor), "_cartao_reenviar")
    vendedor.ir_para("dashboard")
    vendedor.abrir_nova_proposta_duplicada(item.cpf, 0)
    assert vendedor.chave_atual() == "dashboard" and not vendedor._tela_ficha._expansor.eh_rascunho()
    print("OK: VENDEDOR nao tem o bloco 'Para reenviar' nem consegue duplicar por codigo.")
    msgs.exigir_sem_erros("para reenviar")


def testar_qualidade_e_resumo(amb: Ambiente, msgs: Mensagens, tema: str) -> None:
    linha(f"6) Qualidade dos dados e resumo para copiar [{tema}]")
    janela = amb.nova_janela("admin", tema)
    tela = _dashboard(janela)
    paleta = PALETAS[tema]
    propostas = propostas_mod.listar_propostas()

    campos = dash.qualidade_dos_dados(propostas)
    linhas = [w for w in _widgets(tela._cartao_qualidade) if isinstance(w, LinhaDeQualidade)]
    assert [l.trilho.percentual() for l in linhas] == [c.percentual for c in campos]
    for l, campo in zip(linhas, campos):
        esperado = paleta["sucesso"] if campo.percentual >= 100 else CORES_STATUS[tema]["em_analise"]["faixa"] if campo.percentual < 50 else paleta["destaque"]
        assert l.trilho.cor_do_preenchimento().name() == QColor(esperado).name(), (campo.rotulo, campo.percentual)
        area = l.trilho.rect()
        imagem = l.trilho.grab().toImage()
        assert _contar_pixels(imagem, QColor(esperado), QRect(0, 0, max(int(area.width() * campo.percentual / 100) - 12, 2), area.height()), 6) > 10, "a barra e desenhada na cor da gravidade"
    print("OK: uma barra por campo com o percentual do core; verde = tudo preenchido, ambar = menos da metade, destaque = o resto (e desenhada).")

    # resumo: o texto do core, o botao copia exatamente ele e acompanha o periodo
    assert tela._rotulo_do_resumo.text() == dash.resumo_para_copiar(propostas)
    QApplication.clipboard().setText("antes")
    tela._botao_copiar_resumo.click()
    assert QApplication.clipboard().text() == dash.resumo_para_copiar(propostas)
    tela.definir_periodo("7d")
    tela._botao_copiar_resumo.click()
    copiado = QApplication.clipboard().text()
    assert copiado == dash.resumo_para_copiar(_do_periodo(propostas, "7d", tela._hoje()), "7d") and "nos últimos 7 dias" in copiado
    tela.definir_periodo("tudo")
    print("OK: o resumo e a frase do core, o botao Copiar copia exatamente ela e ela respeita o periodo.")
    msgs.exigir_sem_erros("qualidade e resumo")


def testar_visao_do_vendedor(amb: Ambiente, msgs: Mensagens, tema: str) -> None:
    linha(f"7) Visao do VENDEDOR: so o dele, sem nome de outro vendedor [{tema}]")
    for nome, outro in (("Vendedor Exemplo", NOME_DA_OUTRA_VENDEDORA), (NOME_DA_OUTRA_VENDEDORA, "Vendedor Exemplo")):
        janela = amb.nova_janela("vendedor", tema, nome=nome)
        tela = _dashboard(janela)
        minhas = propostas_mod.listar_propostas()  # ja filtrada pelo vendedor logado (a "rede" e simulada pelo Ambiente)
        assert 0 < len(minhas) < len(bd_todas(amb)), "o vendedor so ve as proprias propostas"

        for ausente in ("_cartao_atencao", "_cartao_reenviar", "_cartao_qualidade", "_tabela_vendedores", "_cartao_vendedores"):
            assert not hasattr(tela, ausente), f"o vendedor nao tem {ausente}"
        topo = dash.indicadores_do_topo(minhas)
        assert tela._card_em_analise.valor() == str(topo["em_analise"]["quantidade"]) and tela._card_a_efetivar.valor() == str(topo["a_efetivar"]["quantidade"])

        # as tres listas dele
        for cartao, etapa in ((tela._cartao_minhas_em_analise, propostas_mod.ETAPA_EM_ANALISE), (tela._cartao_minhas_a_efetivar, propostas_mod.ETAPA_APROVADO)):
            itens = dash.propostas_da_etapa(minhas, etapa)
            linhas = [w for w in _widgets(cartao) if isinstance(w, LinhaClicavel)]
            assert len(linhas) == min(len(itens), 8)
            if itens:
                assert linhas[0].text().startswith(itens[0].cliente), "a mais parada primeiro"
                assert itens[0].equipamento in linhas[0].toolTip(), "o equipamento vai no tooltip"
        sem_proposta = dash.clientes_sem_proposta(clientes_mod.listar_clientes(), minhas)
        linhas_clientes = [w for w in _widgets(tela._cartao_meus_clientes) if isinstance(w, LinhaClicavel)]
        assert [l.text() for l in linhas_clientes] == [n for _, n in sem_proposta[:8]]

        # NENHUM texto da tela cita o outro vendedor
        textos = [l.text() for l in tela.findChildren(QLabel)] + [l.text() for l in tela.findChildren(LinhaClicavel)] + [l.toolTip() for l in tela.findChildren(LinhaClicavel)]
        tabela = tela._tabela_bancos
        for coluna in range(7):
            textos += tabela.textos_da_coluna(coluna)
        assert not [t for t in textos if outro.upper() in t.upper()], f"{nome}: a tela cita '{outro}'"
        print(f"OK: {nome}: 3 numeros dele, as listas dele ('minhas em analise', 'aprovadas a efetivar', 'clientes sem proposta') e nenhuma citacao a '{outro}'.")

        # cliques do vendedor: 'Ver todas', uma linha (abre a ficha do cliente) e o funil
        if dash.propostas_da_etapa(minhas, propostas_mod.ETAPA_EM_ANALISE):
            tela._botao_ver_em_analise.click()
            esperado = {int(i) for i in minhas.index[minhas["STATUS"].map(propostas_mod.etapa_status) == propostas_mod.ETAPA_EM_ANALISE]}
            assert janela.chave_atual() == "propostas" and _indices_da_lista(janela._tela_propostas) == esperado
            janela._tela_propostas._botao_limpar_filtros.click()
            janela.ir_para("dashboard")
            [w for w in _widgets(tela._cartao_minhas_em_analise) if isinstance(w, LinhaClicavel)][0].click()
            assert janela.chave_atual() == "ficha" and janela._tela_ficha._cpf_selecionado is not None
        if linhas_clientes:
            janela.ir_para("dashboard")
            linhas_clientes[0].click()
            assert janela.chave_atual() == "ficha" and janela._tela_ficha._nome_label.text() == sem_proposta[0][1]
        print("OK: 'Ver todas' filtra por etapa (sem reler a 'rede'); uma linha abre a ficha do cliente.")
        janela.ir_para("dashboard")
    msgs.exigir_sem_erros("visao do vendedor")


def testar_vendedor_sem_nada_e_planilha_vazia(amb: Ambiente, msgs: Mensagens, tema: str) -> None:
    linha(f"8) Bordas: vendedor sem nenhuma proposta e planilha sem propostas [{tema}]")
    # o app inteiro abre pra um vendedor recem-cadastrado (antes o Dashboard quebrava e a janela nao abria)
    janela = amb.nova_janela("vendedor", tema, nome="Fulano Sem Propostas")
    tela = _dashboard(janela)
    assert tela._card_em_analise.valor() == "0" and tela._card_taxa.valor() == "—" and tela._card_mediano.valor() == "—"
    assert tela._texto_do_resumo == "Nenhuma proposta." and tela._tabela_bancos.total_de_linhas() == 0
    assert [w.text() for w in _widgets(tela._cartao_meus_clientes) if isinstance(w, QLabel)] == ["Todos os seus clientes têm proposta"]
    assert tela._botao_ver_em_analise.isHidden(), "sem propostas nao ha 'Ver todas'"
    print("OK: um vendedor sem nenhuma proposta abre a janela e o Dashboard mostra tudo zerado.")

    admin = amb.nova_janela("admin", tema)
    tela = _dashboard(admin)
    tela._propostas = fx.propostas_vazias()
    tela._atualizar()
    assert tela._card_em_analise.valor() == "0" and tela._tabela_vendedores.total_de_linhas() == 0
    assert [w.text() for w in _widgets(tela._cartao_reenviar)] == ["Nenhum cliente com todas as propostas negadas."]
    assert all(isinstance(w, LinhaDeQualidade) and w.texto_do_valor() == "—" for w in _widgets(tela._cartao_qualidade))
    print("OK: sem propostas nenhum bloco quebra e cada um mostra a sua mensagem.")
    msgs.exigir_sem_erros("bordas")


def testar_tema_e_recarga(amb: Ambiente, msgs: Mensagens, tema: str) -> None:
    linha(f"9) Fundo dos rotulos, cores do funil, troca de tema e recarga [{tema}]")
    janela = amb.nova_janela("admin", tema)
    tela = _dashboard(janela)
    paleta = PALETAS[tema]

    sem_fundo = [
        l.text()
        for l in tela.findChildren(QLabel)
        if l.width() > 4 and l.property("role") not in ("campo_rotulo", "campo_valor") and l.grab().toImage().pixelColor(0, 0).alpha() != 0
    ]
    assert not sem_fundo, f"rotulos com fundo proprio (faixa escura atras do texto): {sem_fundo[:5]}"

    # as barras do funil usam as cores de status do tema (as mesmas dos cards de proposta)
    QApplication.processEvents()
    assert tela.isVisible()
    funil = tela._funil
    imagem = funil.grab().toImage()
    for e in funil.etapas():
        if not e.quantidade:
            continue
        r = funil.retangulo_da_etapa(e.etapa)
        cor = funil.cor_da_etapa(e.etapa)
        assert cor.name() == QColor(CORES_STATUS[tema][chave_cor_etapa(e.etapa)]["faixa"]).name(), "a cor da barra e a de status da etapa"
        assert _contar_pixels(imagem, cor, QRect(int(r.left()) + 118, int(r.center().y()) - 6, 12, 12), 3) > 30, f"a barra de {e.etapa} nao foi desenhada na cor do status"
    print("OK: nenhum rotulo tem fundo proprio e as barras do funil estao nas cores de status do tema.")

    # trocar o tema refaz as cores dos desenhos
    inicial = janela._tema_atual
    janela._alternar_tema()
    novo = TEMA_CLARO if inicial == TEMA_ESCURO else TEMA_ESCURO
    assert funil._paleta is PALETAS[novo] and tela._tabela_bancos._delegado._paleta is PALETAS[novo]
    assert all(l.trilho._paleta is PALETAS[novo] for l in _widgets(tela._cartao_qualidade) if isinstance(l, LinhaDeQualidade))
    janela._alternar_tema()
    print("OK: trocar o tema refaz a paleta do funil, das barras e da tabela.")

    # gravar em outra tela marca o Dashboard como desatualizado; voltar a ele relê os dados
    paradas = next(i for i in dash.precisa_de_atencao(propostas_mod.listar_propostas(), hoje=tela._hoje()) if i.chave == dash.ATENCAO_PARADAS)
    assert paradas.quantidade >= 2
    janela.ir_para("dashboard")
    [w for w in _widgets(tela._cartao_atencao) if isinstance(w, LinhaClicavel)][0].click()  # so as paradas: cabem na 1a pagina
    tela_propostas = janela._tela_propostas
    indice = paradas.indices[0]
    tela_propostas._expansor.alternar(tela_propostas._modelo.linha_do_indice_real(indice))
    formulario = tela_propostas._expansor.formulario()
    status_original = propostas_mod.listar_propostas().loc[indice, "STATUS"]
    formulario._habilitar_edicao()
    formulario._status.setCurrentText(propostas_mod.STATUS_NEGADO)
    formulario._salvar()
    assert tela._desatualizado, "gravar em Todas as Propostas marca o Dashboard"
    janela.ir_para("dashboard")
    assert not tela._desatualizado, "ao voltar, o Dashboard releu os dados"
    primeira_linha = [w for w in _widgets(tela._cartao_atencao) if isinstance(w, LinhaClicavel)][0]
    assert primeira_linha.text() == f"{paradas.quantidade - 1} proposta{'s' if paradas.quantidade - 1 > 1 else ''} em aberto há mais de 7 dias", primeira_linha.text()
    propostas_mod.atualizar_proposta(indice, {"STATUS": status_original})  # devolve a fixture ao que era
    tela_propostas._botao_limpar_filtros.click()
    print("OK: gravar em outra tela marca o Dashboard e, ao voltar, os numeros ja refletem a mudanca (paradas: 1 a menos).")
    msgs.exigir_sem_erros("tema e recarga")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    estilo_original = app.style().objectName()
    app.setStyle("windows11")  # o app real usa este estilo; o padrao sem tela (Fusion) esconderia diferencas
    amb = Ambiente(volumoso=True)
    try:
        with Mensagens() as msgs:
            for tema in TEMAS:
                for teste in (
                    testar_numeros_do_topo,
                    testar_periodo_e_comparacao,
                    testar_atencao_e_cliques,
                    testar_por_banco,
                    testar_para_reenviar,
                    testar_qualidade_e_resumo,
                    testar_visao_do_vendedor,
                    testar_vendedor_sem_nada_e_planilha_vazia,
                    testar_tema_e_recarga,
                ):
                    msgs.limpar()
                    msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
                    amb.resetar_preferencias()  # senao a "ultima tela" do teste anterior abre a janela em outra tela
                    teste(amb, msgs, tema)
                    amb.limpar_janelas()
        linha("TUDO OK")
    finally:
        amb.encerrar()
        app.setStyle(estilo_original)
        app.setStyleSheet("")


if __name__ == "__main__":
    main()
