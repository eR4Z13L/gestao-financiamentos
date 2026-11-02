"""Testa o botao unico "Sincronizar" e o menu "Avancado" da aba "Sincronizacao e backup" da tela Administracao
(desktop/screens/usuarios_screen.py): cada situacao da nuvem (em dia, pendente aqui, nuvem mais nova, conflito,
nuvem sem controle, sem rede, erro) mostra em texto claro o que foi feito, e o que e arriscado (conflito) so abre a
pergunta - nunca altera nada. O Google e a nuvem falsa de smoke_test_sincronizacao_versao.py: nenhum byte sai da
maquina. Planilhas ficticias em pastas temporarias, nunca em data/.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_administracao_sincronizacao.py
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

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
import smoke_test_sincronizacao_versao as t
from core import backup as backup_mod
from core import data_store as bd
from core import estado_sincronizacao as estado_mod
from core import sessao as sessao_mod
from core import sheets_sync
from core import sincronizacao as S
from desktop.screens.usuarios_screen import UsuariosScreen

linha = t.linha


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    registro_antes = fx.instantaneo_do_registro()
    listagem_real = sorted(p.name for p in config.DIRETORIO_DADOS.glob("*")) if config.DIRETORIO_DADOS.exists() else []
    raiz = Path(tempfile.mkdtemp(prefix="_smoke_admin_sync_"))
    fx.isolar_preferencias(raiz)

    mensagens: list[tuple[str, str, str]] = []
    resposta = {"pergunta": QMessageBox.StandardButton.No}

    def _stub(tipo):
        def _f(*args, **kwargs):
            mensagens.append((tipo, args[1] if len(args) > 1 else "", args[2] if len(args) > 2 else ""))
            return resposta["pergunta"] if tipo == "question" else QMessageBox.StandardButton.Ok
        return staticmethod(_f)

    originais = {n: getattr(QMessageBox, n) for n in ("warning", "critical", "information", "question")}
    for nome in originais:
        setattr(QMessageBox, nome, _stub(nome))

    try:
        sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
        a = t.Maquina("A", raiz)  # o computador que ja mandou os dados pra nuvem
        b = t.Maquina("B", raiz)  # o computador onde a tela esta aberta
        a.ativar()
        t._cadastrar_dados_dificeis()
        nuvem = t.NuvemFalsa()

        linha("1) A tela: um botao 'Sincronizar' e o menu 'Avancado' (sem 'Sincronizar agora' nem 'Baixar da nuvem' soltos)")
        b.ativar()
        tela = UsuariosScreen()
        rotulos = [x.text() for x in tela.findChildren(QPushButton)]
        assert rotulos.count("Sincronizar") == 1 and "Avançado" in rotulos, rotulos
        assert "Sincronizar agora" not in rotulos and "Baixar da nuvem" not in rotulos, rotulos
        assert tela._acao_baixar_avancado.text().startswith("Baixar da nuvem")
        assert tela._acao_enviar_avancado.text().startswith("Enviar os meus dados")
        pedidos: list[tuple[str, object]] = []
        tela.decisao_pedida.connect(lambda tipo, meta: pedidos.append((tipo, meta)))
        avisos_de_dados: list[int] = []
        tela.dados_atualizados.connect(lambda: avisos_de_dados.append(1))
        botao = tela._botao_sincronizar
        print("OK: botao 'Sincronizar' + 'Avançado' com 'Baixar da nuvem...' e 'Enviar os meus dados...'.")

        linha("2) Sincronizacao desativada: o botao e as duas acoes avisam e nao tentam nada")
        assert config.SINCRONIZACAO_GOOGLE_ATIVADA is False
        for acionar in (botao.click, tela._acao_baixar_avancado.trigger, tela._acao_enviar_avancado.trigger):
            antes = len(mensagens)
            acionar()
            assert len(mensagens) == antes + 1 and mensagens[-1][0] == "information" and "desativada" in mensagens[-1][2].lower()
        assert sheets_sync.estado_atual().em_andamento == 0
        print("OK: com a sincronizacao desligada, as tres acoes so avisam.")

        with t._Ambiente(nuvem):
            a.ativar()
            S.enviar_para_a_nuvem_substituindo(a.arquivo, copia_obrigatoria=False)
            t._esperar_envios()

            def como_b() -> None:
                b.ativar()

            def como_a_enviar(nome: str, numero: int) -> None:
                """O computador A grava mais um cliente (e a nuvem fica uma versao a frente do B)."""
                a.ativar()
                estado_mod.definir_revisao(nuvem.revisao(), a.arquivo)
                t._adicionar_cliente_simples(nome, fx.cpf_ficticio(700_000 + numero))
                t._esperar_envios()
                como_b()

            como_b()
            estado_mod.registrar_download(nuvem.revisao(), b.arquivo)

            linha("3) Em dia: nao faz nada e diz isso")
            hash_b, escritas = b.hash(), len(nuvem.escritas)
            mensagens.clear()
            botao.click()
            assert "tudo certo" in tela._rotulo_resultado_sync.text().lower()
            assert b.hash() == hash_b and len(nuvem.escritas) == escritas and not avisos_de_dados and not pedidos
            assert not mensagens, mensagens
            print("OK: em dia -> 'Tudo certo', nada escrito, nada baixado, sem janelinha.")

            linha("4) So ha pendencia aqui: reenvia (a nuvem avanca) e diz isso")
            estado_mod.marcar_pendente(bd.ABA_CLIENTES, b.arquivo)
            rev = nuvem.revisao()
            botao.click()
            t._esperar_envios()
            assert "enviei" in tela._rotulo_resultado_sync.text().lower()
            assert nuvem.revisao() == rev + 1 and b.estado().abas_pendentes == (), (nuvem.revisao(), b.estado())
            assert not pedidos and not avisos_de_dados
            print("OK: pendencia local -> enviou so o que faltava, a nuvem avancou uma versao e nada mais ficou pendente.")

            linha("5) Nuvem mais nova e nada pendente: baixa, com backup 'pre-nuvem', e avisa as outras telas")
            como_a_enviar("CLIENTE NOVO DO A", 1)
            assert t._normalizado(b.arquivo) != t._normalizado(a.arquivo)
            hash_antes, escritas = b.hash(), len(nuvem.escritas)
            botao.click()
            assert t._normalizado(b.arquivo) == t._normalizado(a.arquivo), "o B ficou igual a nuvem (= A)"
            assert len(nuvem.escritas) == escritas, "baixar nao escreve na nuvem"
            copias = [x for x in backup_mod.listar_backups(b.arquivo) if x.motivo == backup_mod.MOTIVO_PRE_NUVEM]
            assert copias and fx_hash(copias[0].caminho) == hash_antes, "o backup e o arquivo de ANTES"
            assert avisos_de_dados == [1], "as outras telas foram avisadas uma vez"
            texto = tela._rotulo_resultado_sync.text()
            assert "mais novos" in texto and "cliente(s)" in texto and str(copias[0].caminho) in texto, texto
            assert b.estado().revisao_conhecida == nuvem.revisao() and not mensagens, mensagens
            print("OK: nuvem mais nova -> baixou sozinho, backup 'pre-nuvem' do arquivo de antes, texto claro, telas avisadas.")

            linha("6) Conflito (nuvem mais nova E pendencia aqui): NAO mexe em nada, so abre a pergunta")
            como_a_enviar("CLIENTE DO A, DE NOVO", 2)
            estado_mod.marcar_pendente(bd.ABA_PROPOSTAS, b.arquivo)
            hash_antes, escritas, backups = b.hash(), len(nuvem.escritas), len(backup_mod.listar_backups(b.arquivo))
            avisos_de_dados.clear()
            botao.click()
            assert [p[0] for p in pedidos] == [S.SITUACAO_CONFLITO] and pedidos[0][1].com_controle
            assert b.hash() == hash_antes and len(nuvem.escritas) == escritas, "nada mudou, em lado nenhum"
            assert len(backup_mod.listar_backups(b.arquivo)) == backups and not avisos_de_dados
            assert b.estado().abas_pendentes == (bd.ABA_PROPOSTAS,)
            assert "nada foi alterado" in tela._rotulo_resultado_sync.text().lower()
            print("OK: conflito -> pergunta pedida (decisao_pedida), arquivo, nuvem, backups e pendencias intactos.")

            linha("7) Nuvem sem controle de versao: tambem so pergunta")
            pedidos.clear()
            vazia = t.NuvemFalsa()
            t._usar_nuvem(vazia)
            botao.click()
            assert [p[0] for p in pedidos] == [S.SITUACAO_SEM_CONTROLE] and vazia.escritas == [] and b.hash() == hash_antes
            t._usar_nuvem(nuvem)
            print("OK: nuvem sem controle -> pergunta pedida, nada escrito.")

            linha("8) Sem rede e erro no meio: explica, nunca em silencio, nada alterado")
            pedidos.clear()
            nuvem.sem_rede = True
            mensagens.clear()
            botao.click()
            nuvem.sem_rede = False
            assert "sem conexão" in tela._rotulo_resultado_sync.text().lower() and b.hash() == hash_antes and not pedidos
            estado_mod.registrar_download(nuvem.revisao() - 1, b.arquivo)  # nuvem mais nova e nada pendente
            nuvem.abas_que_falham_ao_ler = {"VENDEDORES"}
            botao.click()
            nuvem.abas_que_falham_ao_ler = set()
            assert mensagens[-1][0] == "critical" and mensagens[-1][1] == "Erro ao sincronizar" and "nada foi alterado" in mensagens[-1][2].lower(), mensagens
            assert b.hash() == hash_antes
            print("OK: sem rede -> 'Sem conexao'; erro na leitura -> mensagem de erro, arquivo igual.")

            linha("9) Avancado > Enviar os meus dados: pergunta antes; 'Nao' nao faz nada; 'Sim' guarda a copia da nuvem e envia")
            estado_mod.registrar_download(nuvem.revisao(), b.arquivo)
            mensagens.clear()
            resposta["pergunta"] = QMessageBox.StandardButton.No
            escritas = len(nuvem.escritas)
            tela._acao_enviar_avancado.trigger()
            assert mensagens[-1][0] == "question" and len(nuvem.escritas) == escritas
            resposta["pergunta"] = QMessageBox.StandardButton.Yes
            tela._acao_enviar_avancado.trigger()
            t._esperar_envios()
            assert any(x.motivo == backup_mod.MOTIVO_COPIA_DA_NUVEM for x in backup_mod.listar_backups(b.arquivo))
            assert any(m[1] == "Envio iniciado" for m in mensagens), mensagens
            assert nuvem.cabecalho_e_linhas("CLIENTES") == len(bd.ler_clientes(b.arquivo)), "a nuvem ficou com os dados do B"
            assert b.estado().abas_pendentes == () and b.estado().revisao_conhecida == nuvem.revisao()
            print("OK: 'Nao' nao faz nada; 'Sim' guarda a copia da nuvem em Backups e envia os dados daqui.")

        linha("TUDO OK")
    finally:
        for nome, original in originais.items():
            setattr(QMessageBox, nome, original)
        fx.restaurar_modulos()
        sessao_mod.encerrar()
        sheets_sync._NOME_DA_MAQUINA = None
        config.SINCRONIZACAO_GOOGLE_ATIVADA = False
        shutil.rmtree(raiz, ignore_errors=True)
        assert fx.instantaneo_do_registro() == registro_antes, "não pode ter mexido no registro real"
        depois = sorted(p.name for p in config.DIRETORIO_DADOS.glob("*")) if config.DIRETORIO_DADOS.exists() else []
        assert depois == listagem_real, f"o teste mexeu na pasta de dados real: {set(depois) ^ set(listagem_real)}"


def fx_hash(caminho: Path) -> str:
    import hashlib

    return hashlib.sha256(Path(caminho).read_bytes()).hexdigest()


if __name__ == "__main__":
    main()
