"""Testa a INTERFACE da sincronizacao entre dois computadores: o indicador da barra lateral (conflito e
aviso), o botao "Baixar da nuvem" em Administracao, o que a janela faz em cada situacao ao abrir
(sem controle / nuvem mais nova / conflito / outro computador ativo), o sinal de atividade e o
fechamento. A janela e a de verdade (sem tela); o Google e a nuvem falsa de
smoke_test_sincronizacao_versao.py e as perguntas ao usuario (escolha_dialog.escolher) sao
respondidas por um roteiro - nenhum byte sai da maquina.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_sincronizacao_janela.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
import smoke_test_sincronizacao_versao as t
from ambiente_de_teste import Ambiente, Mensagens
from core import backup as backup_mod
from core import data_store as bd
from core import estado_sincronizacao as estado_mod
from core import sheets_sync
from core import sincronizacao as S
from desktop.dialogs import escolha_dialog
from desktop.theme import CORES_STATUS, PALETAS, TEMA_ESCURO
from desktop.widgets.indicador_sincronizacao import descrever_sincronizacao

linha = t.linha


class Escolhas:
    """Responde as perguntas da janela com um roteiro: `respostas` e a lista de indices, na ordem."""

    def __init__(self):
        self.respostas: list[int | None] = []
        self.vistas: list[tuple[str, str, list[str]]] = []

    def __enter__(self):
        self._original = escolha_dialog.escolher

        def _falso(parent, titulo, texto, opcoes, *, aviso=False, padrao=0):
            self.vistas.append((titulo, texto, list(opcoes)))
            assert self.respostas, f"a janela fez uma pergunta que o teste nao esperava: {titulo!r}"
            return self.respostas.pop(0)

        escolha_dialog.escolher = _falso
        return self

    def __exit__(self, *_exc):
        escolha_dialog.escolher = self._original

    def responder(self, *indices):
        self.respostas[:] = list(indices)
        self.vistas.clear()


def _botao(tela, texto: str) -> QPushButton:
    achados = [b for b in tela.findChildren(QPushButton) if b.text() == texto]
    assert len(achados) == 1, f"esperava 1 botao {texto!r}, achei {len(achados)}"
    return achados[0]


def _esperar_processando(condicao, limite_s: float = 5.0) -> None:
    fim = time.monotonic() + limite_s
    while not condicao():
        QApplication.processEvents()
        assert time.monotonic() < fim, "tempo esgotado"
        time.sleep(0.01)


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    estilo_original = app.style().objectName()
    app.setStyle("windows11")
    raiz = Path(tempfile.mkdtemp(prefix="_smoke_sync_janela_"))
    listagem_real = sorted(p.name for p in config.DIRETORIO_DADOS.glob("*")) if config.DIRETORIO_DADOS.exists() else []
    # a fixture do "dono" da nuvem e criada ANTES do Ambiente: ele redireciona a leitura das propostas pro arquivo dele
    dono = t.Maquina("PC-DO-A", raiz)  # o computador que "ja mandou" os dados pra nuvem
    amb = Ambiente(volumoso=True)
    nuvem = t.NuvemFalsa()
    try:
        with Mensagens() as msgs, Escolhas() as escolhas:
            with t._Ambiente(nuvem):
                original_do_app = amb.caminho.read_bytes()

                def repor_nuvem_do_dono() -> None:
                    nuvem.abas.clear()
                    nuvem.escritas.clear()
                    dono.ativar()
                    S.enviar_para_a_nuvem_substituindo(dono.arquivo, copia_obrigatoria=False)
                    t._esperar_envios()

                def preparar_app(*, versao_conhecida: int | None, pendentes: tuple[str, ...] = ()) -> None:
                    """O computador do app com o arquivo de antes, e um estado local escolhido."""
                    amb.caminho.write_bytes(original_do_app)
                    fx.apontar_modulos_para(amb.caminho)
                    sheets_sync._NOME_DA_MAQUINA = "PC-DO-APP"
                    sheets_sync._reiniciar_estado()
                    estado_mod._arquivo(amb.caminho).unlink(missing_ok=True)
                    if versao_conhecida is not None:
                        estado_mod.registrar_download(versao_conhecida, amb.caminho)
                    for aba in pendentes:
                        estado_mod.marcar_pendente(aba, amb.caminho)

                def igual_ao_dono() -> bool:
                    return t._normalizado(amb.caminho) == t._normalizado(dono.arquivo)

                repor_nuvem_do_dono()
                rev = nuvem.revisao()

                # ------------------------------------------------------------------------------------
                linha("1) Indicador: conflito (vermelho) e aviso (ambar), com o texto certo")
                preparar_app(versao_conhecida=rev - 1)
                janela = amb.nova_janela("admin", TEMA_ESCURO)
                indicador = janela._indicador_sincronizacao
                paleta = PALETAS[TEMA_ESCURO]
                meta_qualquer = sheets_sync.MetaNuvem(True, rev, "PC-DO-A", None, "", None)

                sheets_sync._registrar_conflito(sheets_sync.ConflitoDeSincronizacao(
                    sheets_sync.TIPO_DIVERGENTE, meta_qualquer, rev - 1, "x"))
                janela._atualizar_indicador_de_sincronizacao()
                d = indicador.descricao()
                assert (d.nivel, d.texto) == (sheets_sync.NIVEL_CONFLITO, "Conflito com a nuvem — clique"), d
                assert indicador.text() == d.texto and "não apagar o trabalho" in indicador.toolTip()
                assert indicador.cor_da_bolinha().name() == QColor(paleta["erro"]).name()
                sheets_sync.limpar_conflito()
                sheets_sync._registrar_conflito(sheets_sync.ConflitoDeSincronizacao(
                    sheets_sync.TIPO_SEM_CONTROLE, sheets_sync.MetaNuvem(), None, "x"))
                assert descrever_sincronizacao(sheets_sync.estado_atual(), __import__("datetime").datetime.now()).texto == "Nuvem sem controle — clique"
                sheets_sync.limpar_conflito()
                print("OK: conflito -> vermelho + 'Conflito com a nuvem — clique'; sem controle -> 'Nuvem sem controle — clique'.")

                sheets_sync._aviso = ("Outro computador ativo", "detalhe de teste")
                janela._atualizar_indicador_de_sincronizacao()
                d = indicador.descricao()
                assert (d.nivel, d.texto, d.detalhe) == (sheets_sync.NIVEL_ATENCAO, "Outro computador ativo", "detalhe de teste")
                assert indicador.cor_da_bolinha().name() == QColor(CORES_STATUS[TEMA_ESCURO]["em_analise"]["faixa"]).name()
                msgs.limpar()
                indicador.click()
                assert msgs.ultima()[0] == "information" and "detalhe de teste" in msgs.ultima()[2]
                sheets_sync._aviso = ("", "")
                print("OK: aviso -> ambar com a frase; clicar mostra o detalhe.")

                # ------------------------------------------------------------------------------------
                linha("2) Clicar no indicador em CONFLITO abre a decisao (e 'Decidir depois' nao muda nada)")
                preparar_app(versao_conhecida=rev - 1, pendentes=(bd.ABA_CLIENTES,))
                sheets_sync._registrar_conflito(sheets_sync.ConflitoDeSincronizacao(
                    sheets_sync.TIPO_DIVERGENTE, sheets_sync.ler_meta_da_nuvem(), rev - 1, "x"))
                janela._atualizar_indicador_de_sincronizacao()
                hash_antes = amb.caminho.read_bytes()
                escolhas.responder(2)  # Decidir depois
                indicador.click()
                titulo, texto, opcoes = escolhas.vistas[0]
                assert titulo == "Conflito com a nuvem" and opcoes[-1] == "Decidir depois" and len(opcoes) == 3
                assert amb.caminho.read_bytes() == hash_antes and sheets_sync.estado_atual().conflito == sheets_sync.TIPO_DIVERGENTE
                print("OK: o clique abre a decisao de 3 opcoes; 'Decidir depois' deixa tudo como estava (conflito segue aberto).")
                sheets_sync.limpar_conflito()

                # ------------------------------------------------------------------------------------
                linha("3) Administracao: botao 'Baixar da nuvem'")
                preparar_app(versao_conhecida=rev - 1)
                adm = janela._tela_administracao
                avisos = []
                adm.dados_atualizados.connect(lambda: avisos.append(1))
                botao = _botao(adm, "Baixar da nuvem")
                assert not igual_ao_dono()

                msgs.limpar(); msgs.resposta_pergunta = QMessageBox.StandardButton.No
                botao.click()
                assert not igual_ao_dono() and not avisos, "respondendo Nao, nada muda"
                print("OK: respondendo 'Nao' na confirmacao, nada muda.")

                msgs.limpar(); msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
                botao.click()
                assert igual_ao_dono(), "depois de baixar, o app tem os dados da nuvem"
                assert avisos, "as outras telas foram avisadas (dados_atualizados)"
                assert any(m[1] == "Dados baixados" for m in msgs.registro), msgs.registro
                rotulos = [adm._modelo_backups.data(adm._modelo_backups.index(i, 1)) for i in range(adm._modelo_backups.rowCount())]
                assert "Antes de baixar da nuvem" in rotulos, rotulos
                assert estado_mod.ler(amb.caminho).revisao_conhecida == nuvem.revisao()
                print("OK: baixou, as telas foram avisadas, o backup aparece em Backups como 'Antes de baixar da nuvem'.")

                msgs.limpar()
                config.SINCRONIZACAO_GOOGLE_ATIVADA = False
                botao.click()
                assert "desativada" in msgs.ultima()[2].lower()
                config.SINCRONIZACAO_GOOGLE_ATIVADA = True
                print("OK: com a sincronizacao desligada, o botao so avisa.")

                msgs.limpar()
                nuvem.abas.clear()  # nuvem sem nada
                msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
                botao.click()
                assert msgs.ultima()[0] in ("warning", "critical") and msgs.ultima()[1] in (
                    "Não foi possível baixar da nuvem", "Erro ao baixar da nuvem"), msgs.registro
                print("OK: se nao da pra baixar, a janela explica (nunca em silencio).")

                # ------------------------------------------------------------------------------------
                linha("4) Ao abrir: cada situacao da nuvem")
                repor_nuvem_do_dono()
                rev = nuvem.revisao()

                # 4a nuvem mais nova
                preparar_app(versao_conhecida=rev - 1)
                meta = sheets_sync.ler_meta_da_nuvem()
                escolhas.responder(1)  # Agora nao
                assert janela._tratar_situacao_ao_abrir(S.SituacaoAoAbrir(S.SITUACAO_NUVEM_MAIS_NOVA, meta)) is True
                assert escolhas.vistas[0][0] == "Dados mais novos na nuvem" and "PC-DO-A" in escolhas.vistas[0][1]
                assert not igual_ao_dono()
                escolhas.responder(0)  # Baixar
                msgs.limpar()
                janela._tratar_situacao_ao_abrir(S.SituacaoAoAbrir(S.SITUACAO_NUVEM_MAIS_NOVA, meta))
                assert igual_ao_dono()
                print("OK: 'nuvem mais nova': 'Agora nao' nao muda nada; 'Baixar da nuvem' deixa o app igual a nuvem.")

                # 4b conflito
                repor_nuvem_do_dono(); rev = nuvem.revisao()
                for escolha, esperado in ((0, "baixou"), (1, "manteve"), (2, "adiou")):
                    preparar_app(versao_conhecida=rev - 1, pendentes=(bd.ABA_CLIENTES,))
                    t._adicionar_cliente_simples(f"SO NO APP {escolha}", fx.cpf_ficticio(600_000 + escolha))
                    t._esperar_envios()  # o envio e recusado (conflito), fica pendente
                    sheets_sync.limpar_conflito()
                    meta = sheets_sync.ler_meta_da_nuvem()
                    escolhas.responder(escolha)
                    msgs.limpar()
                    janela._tratar_situacao_ao_abrir(S.SituacaoAoAbrir(S.SITUACAO_CONFLITO, meta))
                    t._esperar_envios()
                    if esperado == "baixou":
                        assert igual_ao_dono() and estado_mod.ler(amb.caminho).abas_pendentes == ()
                    elif esperado == "manteve":
                        assert any(str(v) == f"SO NO APP {escolha}" for v in nuvem.abas["CLIENTES"].celulas.values())
                        assert estado_mod.ler(amb.caminho).abas_pendentes == ()
                        assert [b for b in backup_mod.listar_backups(amb.caminho) if b.motivo == backup_mod.MOTIVO_COPIA_DA_NUVEM]
                    else:
                        assert sheets_sync.estado_atual().nivel == sheets_sync.NIVEL_CONFLITO, "adiar deixa o indicador em conflito"
                    if esperado != "baixou":
                        repor_nuvem_do_dono(); rev = nuvem.revisao()
                print("OK: conflito: 'Baixar' fica igual a nuvem; 'Manter o meu' sobrescreve a nuvem e guarda a copia; 'Decidir depois' so deixa o indicador em conflito.")

                # 4c sem controle
                sheets_sync._reiniciar_estado()
                nuvem.abas.clear(); nuvem.escritas.clear()
                preparar_app(versao_conhecida=None)
                meta = sheets_sync.ler_meta_da_nuvem()
                assert not meta.com_controle
                escolhas.responder(2)  # Agora nao
                janela._tratar_situacao_ao_abrir(S.SituacaoAoAbrir(S.SITUACAO_SEM_CONTROLE, meta))
                assert escolhas.vistas[0][2] == ["Baixar da nuvem para este computador", "Enviar os dados deste computador", "Agora não"]
                assert nuvem.escritas == [] and sheets_sync.estado_atual().conflito == sheets_sync.TIPO_SEM_CONTROLE
                sheets_sync.limpar_conflito()
                escolhas.responder(1)  # Enviar
                janela._tratar_situacao_ao_abrir(S.SituacaoAoAbrir(S.SITUACAO_SEM_CONTROLE, meta))
                t._esperar_envios()
                assert nuvem.revisao() >= 5 and t._normalizado(amb.caminho) is not None
                print("OK: sem controle: 3 opcoes; 'Agora nao' nao escreve nada; 'Enviar' liga o controle e manda as 4 abas.")

                # 4c' sem controle, e a nuvem e que tem os dados certos: 'Baixar' traz os dados e liga o controle
                repor_nuvem_do_dono()
                sem_controle = t._copia_sem_controle(nuvem)
                t._usar_nuvem(sem_controle)
                sheets_sync._reiniciar_estado()
                preparar_app(versao_conhecida=None)
                meta = sheets_sync.ler_meta_da_nuvem()
                assert not meta.com_controle and not igual_ao_dono()
                escolhas.responder(0)  # Baixar da nuvem
                msgs.limpar()
                janela._tratar_situacao_ao_abrir(S.SituacaoAoAbrir(S.SITUACAO_SEM_CONTROLE, meta))
                assert igual_ao_dono(), "o app ficou com os dados da nuvem"
                assert sem_controle.revisao() == 1 and estado_mod.ler(amb.caminho).revisao_conhecida == 1
                assert {e[1] for e in sem_controle.escritas} == {sheets_sync.ABA_META}, "so a META e escrita"
                assert any(m[1] == "Dados baixados" and "controle de versão da nuvem foi ligado" in m[2] for m in msgs.registro), msgs.registro
                assert sheets_sync.estado_atual().conflito == ""
                t._usar_nuvem(nuvem)
                print("OK: sem controle + 'Baixar': o app fica igual a nuvem, a META e criada (versao 1) e a mensagem explica.")

                # 4d pendencias que sobreviveram a fechar o app: reenvia sem perguntar
                repor_nuvem_do_dono(); rev = nuvem.revisao()
                preparar_app(versao_conhecida=rev, pendentes=(bd.ABA_CLIENTES,))
                escolhas.responder()
                antes = nuvem.revisao()
                janela._tratar_situacao_ao_abrir(S.SituacaoAoAbrir(S.SITUACAO_LOCAL_PENDENTE, sheets_sync.ler_meta_da_nuvem()))
                t._esperar_envios()
                assert not escolhas.vistas and nuvem.revisao() == antes + 1
                print("OK: 'local pendente' reenvia so o que faltava, sem incomodar com pergunta.")

                # ------------------------------------------------------------------------------------
                linha("5) Outro computador ativo: aviso na abertura, e 'Fechar' fecha de verdade")
                repor_nuvem_do_dono(); rev = nuvem.revisao()
                preparar_app(versao_conhecida=rev)
                meta = sheets_sync.ler_meta_da_nuvem()
                aberta = amb.nova_janela("admin", TEMA_ESCURO)
                situacao = S.SituacaoAoAbrir(S.SITUACAO_EM_DIA, meta, outro_computador="PC-DO-A", outro_desde=__import__("datetime").datetime(2026, 9, 29, 14, 5))
                escolhas.responder(1)  # Continuar
                assert aberta._tratar_situacao_ao_abrir(situacao) is True
                titulo, texto, opcoes = escolhas.vistas[0]
                assert titulo == "Outro computador ativo" and "PC-DO-A" in texto and "14:05" in texto
                assert opcoes == ["Fechar o aplicativo", "Continuar mesmo assim"]
                escolhas.responder(0)  # Fechar
                assert aberta._tratar_situacao_ao_abrir(situacao) is False
                assert not aberta.isVisible(), "'Fechar o aplicativo' fecha a janela"
                print("OK: o aviso diz quem esta ativo e desde quando; 'Continuar' segue, 'Fechar' fecha a janela.")

                # ------------------------------------------------------------------------------------
                linha("6) Fluxo completo: iniciar_sincronizacao_da_nuvem -> pergunta -> sinal de atividade -> sair limpa o sinal")
                repor_nuvem_do_dono(); rev = nuvem.revisao()
                preparar_app(versao_conhecida=rev - 1)
                completa = amb.nova_janela("admin", TEMA_ESCURO)
                escolhas.responder(1)  # Agora nao (na pergunta de "dados mais novos")
                completa.iniciar_sincronizacao_da_nuvem()
                _esperar_processando(lambda: completa._situacao_ao_abrir is not None)
                completa._atualizar_indicador_de_sincronizacao()  # o tique do temporizador
                assert completa._situacao_ao_abrir is None and escolhas.vistas[0][0] == "Dados mais novos na nuvem"
                assert completa._temporizador_do_sinal.isActive(), "depois de tratar a situacao, o sinal de atividade liga"
                _esperar_processando(lambda: nuvem.meta().get("editando_por") == "PC-DO-APP")
                _esperar_processando(lambda: sheets_sync.estado_atual().aviso == "Nuvem com dados mais novos")
                completa._atualizar_indicador_de_sincronizacao()
                assert completa._indicador_sincronizacao.descricao().nivel == sheets_sync.NIVEL_ATENCAO
                print("OK: abriu -> perguntou -> ligou o sinal (a nuvem ve 'PC-DO-APP') -> o indicador avisa que a nuvem e mais nova.")

                completa.desligar()
                assert not completa._temporizador_do_sinal.isActive()
                assert nuvem.meta().get("editando_por") in ("", None), "ao sair, o sinal deste computador some da nuvem"
                print("OK: ao sair, o temporizador para e o sinal e apagado da nuvem.")

                # ------------------------------------------------------------------------------------
                linha("7) Nao faz nada onde nao deve: vendedor e sincronizacao desligada")
                escolhas.responder()
                nuvem.escritas.clear()
                vendedor = amb.nova_janela("vendedor", TEMA_ESCURO)
                vendedor.iniciar_sincronizacao_da_nuvem()
                time.sleep(0.2); QApplication.processEvents()
                assert vendedor._situacao_ao_abrir is None and not vendedor._temporizador_do_sinal.isActive()
                config.SINCRONIZACAO_GOOGLE_ATIVADA = False
                admin_off = amb.nova_janela("admin", TEMA_ESCURO)
                admin_off.iniciar_sincronizacao_da_nuvem()
                time.sleep(0.2); QApplication.processEvents()
                assert admin_off._situacao_ao_abrir is None
                config.SINCRONIZACAO_GOOGLE_ATIVADA = True
                assert nuvem.escritas == [] and not escolhas.vistas
                print("OK: o VENDEDOR e a sincronizacao desligada nao consultam a nuvem nem ligam o sinal.")

                # ------------------------------------------------------------------------------------
                linha("8) Primeira abertura SEM planilha: criar vazia, baixar da nuvem, sem internet, sem chave")
                from desktop import primeira_abertura as pa

                repor_nuvem_do_dono()
                chave_original = config.CAMINHO_CREDENCIAIS_GOOGLE
                chave_falsa = raiz / "chave_falsa.json"
                chave_falsa.write_text("{}", encoding="utf-8")
                pasta_nova = raiz / "instalacao_nova"
                nova = pasta_nova / "data" / "controle_financiamentos.dat"
                try:
                    # 8a sem chave do Google: "Fechar" nao cria nada; "Comecar vazia" cria
                    config.CAMINHO_CREDENCIAIS_GOOGLE = raiz / "nao_existe.json"
                    escolhas.responder(1)
                    assert pa.garantir_planilha(None, nova) is False and not nova.exists()
                    titulo, texto, opcoes = escolhas.vistas[0]
                    assert titulo == "Planilha de dados não encontrada" and "chave do Google" in texto and str(nova.parent) in texto
                    assert opcoes == ["Começar com uma planilha vazia", "Fechar o aplicativo"]
                    msgs.limpar(); escolhas.responder(0)
                    assert pa.garantir_planilha(None, nova) is True and nova.exists()
                    assert len(bd.ler_clientes(nova)) == 0 and msgs.ultima()[1] == "Planilha criada"
                    print("OK: sem chave: explica, 'Fechar' nao cria nada, 'Comecar vazia' cria a planilha (e avisa).")

                    escolhas.responder()
                    assert pa.garantir_planilha(None, nova) is True and not escolhas.vistas, "com planilha, nao pergunta nada"
                    print("OK: com a planilha no lugar, a primeira abertura nao pergunta nada.")

                    # 8b nuvem com dados (com controle): baixa e cria o arquivo igual a nuvem
                    config.CAMINHO_CREDENCIAIS_GOOGLE = chave_falsa
                    nova.unlink()
                    msgs.limpar(); escolhas.responder(0)
                    assert pa.garantir_planilha(None, nova) is True
                    titulo, texto, _ = escolhas.vistas[0]
                    assert titulo == "Baixar os dados da nuvem" and f"{len(bd.ler_clientes(dono.arquivo))} cliente(s)" in texto
                    assert t._normalizado(nova) == t._normalizado(dono.arquivo)
                    assert msgs.ultima()[1] == "Dados baixados" and "guardado" not in msgs.ultima()[2], "nao havia arquivo de antes"
                    print("OK: nuvem com dados: mostra quanto tem, baixa e o arquivo novo fica igual a nuvem.")

                    # 8c sem internet: 'Tentar de novo' pergunta de novo; 'Comecar vazia' cria
                    nova.unlink(); estado_mod._arquivo(nova).unlink(missing_ok=True)
                    nuvem.sem_rede = True
                    escolhas.responder(0, 1)
                    assert pa.garantir_planilha(None, nova) is True
                    nuvem.sem_rede = False
                    assert [v[0] for v in escolhas.vistas] == ["Sem conexão com a nuvem"] * 2 and "sem internet" in escolhas.vistas[0][1]
                    assert nova.exists() and len(bd.ler_clientes(nova)) == 0
                    print("OK: sem internet: 'Tentar de novo' consulta de novo; 'Comecar vazia' cria a planilha.")

                    # 8d nuvem SEM controle com dados: baixa e liga o controle
                    nova.unlink(); estado_mod._arquivo(nova).unlink(missing_ok=True)
                    sem_controle = t._copia_sem_controle(nuvem)
                    t._usar_nuvem(sem_controle)
                    escolhas.responder(0)
                    assert pa.garantir_planilha(None, nova) is True
                    assert t._normalizado(nova) == t._normalizado(dono.arquivo) and sem_controle.revisao() == 1
                    assert estado_mod.ler(nova).revisao_conhecida == 1
                    print("OK: nuvem sem controle: baixa, cria o arquivo e liga o controle (versao 1).")

                    # 8e nuvem vazia
                    nova.unlink(); estado_mod._arquivo(nova).unlink(missing_ok=True)
                    t._usar_nuvem(t.NuvemFalsa())
                    escolhas.responder(0)
                    assert pa.garantir_planilha(None, nova) is True and nova.exists()
                    assert "A nuvem também não tem dados" in escolhas.vistas[0][1]
                    print("OK: nuvem vazia: explica e cria a planilha vazia.")

                    # 8f erro ao baixar: avisa e pergunta de novo (nunca em silencio)
                    nova.unlink(); estado_mod._arquivo(nova).unlink(missing_ok=True)
                    t._usar_nuvem(nuvem)
                    nuvem.abas_que_falham_ao_ler = {"VENDEDORES"}
                    consulta_original = S.consultar_nuvem_para_primeira_abertura
                    S.consultar_nuvem_para_primeira_abertura = lambda: S.NuvemParaPrimeiraAbertura(S.NUVEM_COM_DADOS, {bd.ABA_CLIENTES: 1})
                    msgs.limpar(); escolhas.responder(0, 1)  # Baixar (falha) -> Fechar
                    try:
                        assert pa.garantir_planilha(None, nova) is False
                    finally:
                        S.consultar_nuvem_para_primeira_abertura = consulta_original
                        nuvem.abas_que_falham_ao_ler = set()
                    assert any(m[0] == "critical" and m[1] == "Erro ao baixar da nuvem" for m in msgs.registro), msgs.registro
                    assert not nova.exists() and len(escolhas.vistas) == 2
                    print("OK: se o download falha, a janela explica, nao deixa arquivo pela metade e pergunta de novo.")
                finally:
                    config.CAMINHO_CREDENCIAIS_GOOGLE = chave_original
                    t._usar_nuvem(nuvem)
                    nuvem.sem_rede = False

            linha("TUDO OK")
    finally:
        amb.encerrar()
        app.setStyle(estilo_original)
        app.setStyleSheet("")
        sheets_sync._NOME_DA_MAQUINA = None
        config.SINCRONIZACAO_GOOGLE_ATIVADA = False
        shutil.rmtree(raiz, ignore_errors=True)
        depois = sorted(p.name for p in config.DIRETORIO_DADOS.glob("*")) if config.DIRETORIO_DADOS.exists() else []
        assert depois == listagem_real, f"o teste mexeu na pasta de dados real: {set(depois) ^ set(listagem_real)}"


if __name__ == "__main__":
    main()
