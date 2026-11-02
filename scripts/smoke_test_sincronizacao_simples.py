"""Testa a sincronizacao simples (etapa 2.1): core.sincronizacao.sincronizar (o botao unico) e
baixar_sozinho_se_seguro (baixar sozinho ao abrir). O que tem de valer: so baixa sozinho com a nuvem mais nova,
NADA pendente aqui e nenhum outro computador ativo; conflito, pendencia, nuvem sem controle, sem rede, aba vazia por
engano e arquivo aberto no Excel nunca trocam um byte do arquivo; baixar sempre deixa o backup 'pre-nuvem'.

O Google e a nuvem falsa de smoke_test_sincronizacao_versao.py (nenhum byte sai da maquina); cada "computador" e uma
pasta temporaria propria. A tela do botao esta em smoke_test_administracao_sincronizacao.py e a janela principal
(baixar ao abrir + faixa) em smoke_test_sincronizacao_janela.py.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_sincronizacao_simples.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

linha = t.linha


def _backups_pre_nuvem(maquina: t.Maquina) -> list:
    return [x for x in backup_mod.listar_backups(maquina.arquivo) if x.motivo == backup_mod.MOTIVO_PRE_NUVEM]


def _a_manda_mais_um(a: t.Maquina, b: t.Maquina, nuvem: t.NuvemFalsa, nome: str, numero: int) -> None:
    """O computador A grava mais um cliente: a nuvem passa a ser uma versao a frente do que o B conhece."""
    a.ativar()
    estado_mod.definir_revisao(nuvem.revisao(), a.arquivo)
    t._adicionar_cliente_simples(nome, fx.cpf_ficticio(800_000 + numero))
    t._esperar_envios()
    b.ativar()


def _nada_mudou(b: t.Maquina, nuvem: t.NuvemFalsa, hash_antes: str, escritas: int, backups: int, contexto: str) -> None:
    assert b.hash() == hash_antes, f"{contexto}: o arquivo mudou"
    assert len(nuvem.escritas) == escritas, f"{contexto}: escreveu na nuvem"
    assert len(_backups_pre_nuvem(b)) == backups, f"{contexto}: apareceu backup sem baixar"


class _PendenciaDepoisDaPrimeiraLeitura:
    """Simula a gravacao que entra ENTRE a decisao de baixar (primeira leitura do estado local) e o download:
    a primeira leitura ve o estado limpo e logo depois a aba CLIENTES passa a pendente."""

    def __init__(self, caminho: Path):
        self.caminho = caminho
        self.feito = False

    def __enter__(self):
        self._original = estado_mod.ler

        def _ler(caminho=None):
            resultado = self._original(caminho)
            if not self.feito:
                self.feito = True
                estado_mod.marcar_pendente(bd.ABA_CLIENTES, self.caminho)
            return resultado

        estado_mod.ler = _ler
        return self

    def __exit__(self, *_exc):
        estado_mod.ler = self._original


def testar_sincronizar(a: t.Maquina, b: t.Maquina, nuvem: t.NuvemFalsa) -> None:
    linha("1) sincronizar(): em dia / pendente aqui / nuvem mais nova / conflito / sem controle / sem rede / desativada")
    with t._Ambiente(nuvem):
        a.ativar()
        S.enviar_para_a_nuvem_substituindo(a.arquivo, copia_obrigatoria=False)
        t._esperar_envios()
        b.ativar()
        estado_mod.registrar_download(nuvem.revisao(), b.arquivo)

        # em dia
        h, e, n = b.hash(), len(nuvem.escritas), len(_backups_pre_nuvem(b))
        r = S.sincronizar(b.arquivo)
        assert r.acao == S.ACAO_EM_DIA and r.situacao.tipo == S.SITUACAO_EM_DIA and "tudo certo" in r.texto.lower()
        _nada_mudou(b, nuvem, h, e, n, "em dia")
        print("OK: em dia -> ACAO_EM_DIA, nada muda.")

        # so pendencia aqui: reenvia
        estado_mod.marcar_pendente(bd.ABA_CLIENTES, b.arquivo)
        rev = nuvem.revisao()
        r = S.sincronizar(b.arquivo)
        t._esperar_envios()
        assert r.acao == S.ACAO_ENVIOU and r.abas_enviadas == (bd.ABA_CLIENTES,), r
        assert nuvem.revisao() == rev + 1 and b.estado().abas_pendentes == () and len(_backups_pre_nuvem(b)) == n
        print("OK: so pendencia aqui -> reenviou a aba pendente, sem baixar e sem backup.")

        # nuvem mais nova, nada pendente: baixa
        _a_manda_mais_um(a, b, nuvem, "CLIENTE NOVO DO A", 1)
        antes_baixar, e = b.hash(), len(nuvem.escritas)
        r = S.sincronizar(b.arquivo)
        assert r.acao == S.ACAO_BAIXOU and r.download is not None and r.download.backup is not None
        assert t._normalizado(b.arquivo) == t._normalizado(a.arquivo) and len(nuvem.escritas) == e
        pre = _backups_pre_nuvem(b)
        assert len(pre) == n + 1 and t.hashlib.sha256(r.download.backup.read_bytes()).hexdigest() == antes_baixar
        assert b.estado().revisao_conhecida == nuvem.revisao() and "Backups" in r.texto
        print("OK: nuvem mais nova + nada pendente -> baixou, backup 'pre-nuvem' do arquivo de antes, estado adotou a versao.")

        # uma gravacao entra no meio da decisao: o download confere de novo e recusa (nada e perdido)
        _a_manda_mais_um(a, b, nuvem, "CLIENTE DO A, A CAMINHO", 9)
        h, e, n = b.hash(), len(nuvem.escritas), len(_backups_pre_nuvem(b))
        with _PendenciaDepoisDaPrimeiraLeitura(b.arquivo):
            try:
                S.sincronizar(b.arquivo)
                raise AssertionError("deveria recusar: entrou uma pendencia no meio")
            except S.ErroNuvem as exc:
                assert "ainda não foram enviadas" in str(exc)
        _nada_mudou(b, nuvem, h, e, n, "pendencia no meio da decisao (sincronizar)")
        assert b.estado().abas_pendentes == (bd.ABA_CLIENTES,)
        estado_mod.registrar_download(nuvem.revisao() - 1, b.arquivo)
        print("OK: gravacao que entra no meio da decisao -> sincronizar() recusa o download, nada e perdido.")

        # conflito: nao mexe em nada
        _a_manda_mais_um(a, b, nuvem, "CLIENTE DO A, DE NOVO", 2)
        estado_mod.marcar_pendente(bd.ABA_PROPOSTAS, b.arquivo)
        h, e, n = b.hash(), len(nuvem.escritas), len(_backups_pre_nuvem(b))
        r = S.sincronizar(b.arquivo)
        assert r.acao == S.ACAO_DECIDIR and r.situacao.tipo == S.SITUACAO_CONFLITO
        _nada_mudou(b, nuvem, h, e, n, "conflito")
        assert b.estado().abas_pendentes == (bd.ABA_PROPOSTAS,)
        print("OK: conflito -> ACAO_DECIDIR; arquivo, nuvem, backups e pendencia intactos.")

        # sem controle
        vazia = t.NuvemFalsa()
        t._usar_nuvem(vazia)
        r = S.sincronizar(b.arquivo)
        assert r.acao == S.ACAO_DECIDIR and r.situacao.tipo == S.SITUACAO_SEM_CONTROLE
        assert vazia.escritas == [] and b.hash() == h
        t._usar_nuvem(nuvem)
        print("OK: nuvem sem controle -> ACAO_DECIDIR, nada escrito.")

        # sem rede
        nuvem.sem_rede = True
        r = S.sincronizar(b.arquivo)
        nuvem.sem_rede = False
        assert r.acao == S.ACAO_SEM_REDE and "sem conexão" in r.texto.lower()
        _nada_mudou(b, nuvem, h, e, n, "sem rede")
        print("OK: sem rede -> ACAO_SEM_REDE, nada muda (e nao levanta).")

        # desativada
        config.SINCRONIZACAO_GOOGLE_ATIVADA = False
        try:
            S.sincronizar(b.arquivo)
            raise AssertionError("deveria levantar ErroNuvem")
        except S.ErroNuvem as exc:
            assert "desativada" in str(exc)
        finally:
            config.SINCRONIZACAO_GOOGLE_ATIVADA = True
        print("OK: sincronizacao desativada -> ErroNuvem com texto claro.")


def testar_baixar_sozinho(a: t.Maquina, b: t.Maquina, nuvem: t.NuvemFalsa) -> None:
    linha("2) baixar_sozinho_se_seguro(): so baixa quando e seguro (e devolve None, sem tocar em nada, quando nao)")
    with t._Ambiente(nuvem):
        a.ativar()
        estado_mod.definir_revisao(nuvem.revisao(), a.arquivo)
        b.ativar()
        estado_mod.registrar_download(nuvem.revisao() - 1, b.arquivo)  # o B conhece uma versao antiga, nada pendente
        mais_nova = S.verificar_ao_abrir(b.arquivo)
        assert mais_nova.tipo == S.SITUACAO_NUVEM_MAIS_NOVA
        h, e, n = b.hash(), len(nuvem.escritas), len(_backups_pre_nuvem(b))

        # outro computador ativo
        com_outro = S.SituacaoAoAbrir(S.SITUACAO_NUVEM_MAIS_NOVA, mais_nova.meta, outro_computador="PC-DO-A")
        assert S.baixar_sozinho_se_seguro(com_outro, b.arquivo) is None
        _nada_mudou(b, nuvem, h, e, n, "outro computador ativo")
        print("OK: outro computador ativo -> None, nada muda.")

        # outras situacoes: em dia, local pendente, conflito, sem controle, sem rede
        for tipo in (S.SITUACAO_EM_DIA, S.SITUACAO_LOCAL_PENDENTE, S.SITUACAO_CONFLITO, S.SITUACAO_SEM_CONTROLE,
                     S.SITUACAO_SEM_REDE, S.SITUACAO_DESATIVADA):
            assert S.baixar_sozinho_se_seguro(S.SituacaoAoAbrir(tipo, mais_nova.meta), b.arquivo) is None, tipo
        _nada_mudou(b, nuvem, h, e, n, "outras situacoes")
        print("OK: em dia, pendente, conflito, sem controle, sem rede e desativada -> None.")

        # a situacao diz "nuvem mais nova", mas entrou uma pendencia depois: confere de novo e nao baixa
        estado_mod.marcar_pendente(bd.ABA_CLIENTES, b.arquivo)
        assert S.baixar_sozinho_se_seguro(mais_nova, b.arquivo) is None
        _nada_mudou(b, nuvem, h, e, n, "pendencia surgida depois")
        assert b.estado().abas_pendentes == (bd.ABA_CLIENTES,)
        # e o proprio download recusa dentro do bloqueio, se chamado assim
        try:
            S.baixar_da_nuvem(b.arquivo, exigir_sem_pendencias=True)
            raise AssertionError("deveria recusar: ha pendencia")
        except S.ErroNuvem as exc:
            assert "ainda não foram enviadas" in str(exc)
        _nada_mudou(b, nuvem, h, e, n, "exigir_sem_pendencias")
        print("OK: pendencia local (mesmo surgida depois da decisao) -> nao baixa, arquivo e pendencia intactos.")

        # aba vazia por engano na nuvem: o download recusa e nada muda
        estado_mod.registrar_download(nuvem.revisao() - 1, b.arquivo)
        guardado = dict(nuvem.abas["PROPOSTAS"].celulas)
        nuvem.abas["PROPOSTAS"].celulas.clear()
        nuvem.abas["PROPOSTAS"].celulas[(1, 1)] = "DATA"
        try:
            S.baixar_sozinho_se_seguro(mais_nova, b.arquivo)
            raise AssertionError("deveria recusar: aba vazia por engano")
        except S.ErroNuvem as exc:
            assert "PROPOSTAS" in str(exc) and "interrompido" in str(exc)
        finally:
            nuvem.abas["PROPOSTAS"].celulas.update(guardado)
        _nada_mudou(b, nuvem, h, e, n, "aba vazia por engano")
        print("OK: aba vazia por engano na nuvem -> ErroNuvem, nada muda.")

        # a pendencia entra depois da conferencia de baixar_sozinho_se_seguro: o proprio download recusa
        with _PendenciaDepoisDaPrimeiraLeitura(b.arquivo):
            try:
                S.baixar_sozinho_se_seguro(mais_nova, b.arquivo)
                raise AssertionError("deveria recusar: entrou uma pendencia no meio")
            except S.ErroNuvem as exc:
                assert "ainda não foram enviadas" in str(exc)
        _nada_mudou(b, nuvem, h, e, n, "pendencia no meio da decisao (baixar sozinho)")
        estado_mod.registrar_download(nuvem.revisao() - 1, b.arquivo)
        print("OK: gravacao que entra entre a conferencia e o download -> o download recusa, arquivo intacto.")

        # arquivo aberto no Excel
        trava = bd._caminho_arquivo_bloqueio(b.arquivo)
        trava.write_bytes(b"")
        try:
            S.baixar_sozinho_se_seguro(mais_nova, b.arquivo)
            raise AssertionError("deveria recusar: arquivo aberto no Excel")
        except bd.ErroArquivoBloqueado:
            pass
        finally:
            trava.unlink()
        _nada_mudou(b, nuvem, h, e, n, "arquivo no Excel")
        print("OK: arquivo aberto no Excel -> ErroArquivoBloqueado, nada muda.")

        # agora e seguro: baixa, com backup do arquivo de antes, sem escrever na nuvem
        resultado = S.baixar_sozinho_se_seguro(mais_nova, b.arquivo)
        assert resultado is not None and resultado.backup is not None
        assert t._normalizado(b.arquivo) == t._normalizado(a.arquivo)
        assert t.hashlib.sha256(resultado.backup.read_bytes()).hexdigest() == h
        assert len(_backups_pre_nuvem(b)) == n + 1 and len(nuvem.escritas) == e
        assert b.estado().revisao_conhecida == nuvem.revisao() and b.estado().abas_pendentes == ()
        print("OK: seguro -> baixou, backup 'pre-nuvem' com o arquivo de antes, nada escrito na nuvem.")

        # outro computador ativo de verdade, vindo da META (sinal recente)
        _a_manda_mais_um(a, b, nuvem, "CLIENTE DO A, TERCEIRO", 3)
        sheets_sync._NOME_DA_MAQUINA = "A"
        sheets_sync.registrar_sinal()
        sheets_sync._NOME_DA_MAQUINA = "B"
        situacao = S.verificar_ao_abrir(b.arquivo)
        assert situacao.tipo == S.SITUACAO_NUVEM_MAIS_NOVA and situacao.outro_computador == "A", situacao
        h2 = b.hash()
        assert S.baixar_sozinho_se_seguro(situacao, b.arquivo) is None and b.hash() == h2
        print("OK: o sinal real de outro computador (META) tambem impede baixar sozinho.")


def main() -> None:
    raiz = Path(tempfile.mkdtemp(prefix="_smoke_sync_simples_"))
    registro_antes = fx.instantaneo_do_registro()
    listagem_real = sorted(p.name for p in config.DIRETORIO_DADOS.glob("*")) if config.DIRETORIO_DADOS.exists() else []
    try:
        sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
        a = t.Maquina("A", raiz)
        b = t.Maquina("B", raiz)
        a.ativar()
        t._cadastrar_dados_dificeis()
        nuvem = t.NuvemFalsa()

        testar_sincronizar(a, b, nuvem)
        testar_baixar_sozinho(a, b, nuvem)

        assert config.SINCRONIZACAO_GOOGLE_ATIVADA is False
        linha("TUDO OK")
    finally:
        fx.restaurar_modulos()
        sessao_mod.encerrar()
        sheets_sync._NOME_DA_MAQUINA = None
        config.SINCRONIZACAO_GOOGLE_ATIVADA = False
        shutil.rmtree(raiz, ignore_errors=True)
        assert fx.instantaneo_do_registro() == registro_antes, "nao pode ter mexido no registro real"
        depois = sorted(p.name for p in config.DIRETORIO_DADOS.glob("*")) if config.DIRETORIO_DADOS.exists() else []
        assert depois == listagem_real, f"o teste mexeu na pasta de dados real: {set(depois) ^ set(listagem_real)}"


if __name__ == "__main__":
    main()
