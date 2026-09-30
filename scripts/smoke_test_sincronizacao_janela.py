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
                escolhas.responder(1)  # Agora nao
                janela._tratar_situacao_ao_abrir(S.SituacaoAoAbrir(S.SITUACAO_SEM_CONTROLE, meta))
                assert nuvem.escritas == [] and sheets_sync.estado_atual().conflito == sheets_sync.TIPO_SEM_CONTROLE
                sheets_sync.limpar_conflito()
                escolhas.responder(0)  # Enviar
                janela._tratar_situacao_ao_abrir(S.SituacaoAoAbrir(S.SITUACAO_SEM_CONTROLE, meta))
                t._esperar_envios()
                assert nuvem.revisao() >= 5 and t._normalizado(amb.caminho) is not None
                print("OK: sem controle: 'Agora nao' nao escreve nada; 'Enviar' liga o controle e manda as 4 abas.")

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
