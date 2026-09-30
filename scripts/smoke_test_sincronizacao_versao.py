"""Testa a sincronizacao entre DOIS computadores (trava de versao, baixar da nuvem, aviso de
"outro computador ativo"): core/sheets_sync.py, core/sincronizacao.py, core/estado_sincronizacao.py.

O Google e SUBSTITUIDO por uma nuvem falsa em memoria (NuvemFalsa: abas, celulas, JSON de ida e
volta como a API de verdade, contagem de escritas); nenhum byte sai da maquina. Cada
"computador" e uma pasta temporaria propria, com o seu arquivo de dados e o seu estado local.
A flag da sincronizacao so e ligada com a nuvem falsa no lugar e sempre desligada no fim.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_sincronizacao_versao.py
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sys
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gspread
import pandas as pd

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
from core import backup as backup_mod
from core import clientes as clientes_mod
from core import data_store as bd
from core import data_store_sheets as leitura_sheets
from core import estado_sincronizacao as estado_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import sheets_sync
from core import sincronizacao as sincronizacao_mod
from fixture_ficticia import ColetorDeLog

CNPJ_COM_ZERO = "00000000000191"  # CNPJ valido que comeca com zeros, digitado so com numeros
CPF_1, CPF_2, CPF_3, CPF_4, CPF_5 = (fx.cpf_ficticio(400_000_000 + i * 7919) for i in range(5))  # validos e fora da fixture


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _esperar(condicao, limite_s: float = 5.0) -> None:
    fim = time.monotonic() + limite_s
    while not condicao():
        assert time.monotonic() < fim, "tempo esgotado esperando a sincronizacao falsa terminar"
        time.sleep(0.01)


def _esperar_envios() -> None:
    _esperar(lambda: sheets_sync.estado_atual().em_andamento == 0)


# ------------------------------------------------------------------------------------------
# A nuvem falsa
# ------------------------------------------------------------------------------------------

def _celula(referencia: str) -> tuple[int, int]:
    coluna = ord(referencia[0].upper()) - ord("A") + 1
    return int(referencia[1:]), coluna


def _faixa(faixa: str) -> tuple[tuple[int, int], tuple[int, int]]:
    inicio, _, fim = faixa.partition(":")
    return _celula(inicio), _celula(fim or inicio)


class _AbaFalsa:
    def __init__(self, nuvem: "NuvemFalsa", titulo: str):
        self._nuvem = nuvem
        self.title = titulo
        self.celulas: dict[tuple[int, int], object] = {}

    def clear(self) -> None:
        self._nuvem.registrar_escrita("clear", self.title)
        self.celulas.clear()

    def update(self, valores, range_name=None, raw=True, **_kw) -> None:
        self._nuvem.registrar_escrita("update", self.title, range_name)
        assert raw is True, "todo envio tem que ir em modo RAW (texto exatamente como esta)"
        valores = json.loads(json.dumps(valores))  # a API de verdade so aceita JSON: numpy/Timestamp nao passam
        linha0, coluna0 = _celula(range_name or "A1") if ":" not in (range_name or "") else _faixa(range_name)[0]
        for i, linha_ in enumerate(valores):
            for j, valor in enumerate(linha_):
                self.celulas[(linha0 + i, coluna0 + j)] = valor

    def get(self, range_name, value_render_option=None):
        self._nuvem.registrar_leitura(self.title, value_render_option)
        if self.title == sheets_sync.ABA_META and self._nuvem.gancho_leitura_meta is not None:
            self._nuvem.gancho_leitura_meta(self._nuvem)
        (l0, c0), (l1, c1) = _faixa(range_name)
        resultado = []
        for r in range(l0, l1 + 1):
            valores = [self.celulas.get((r, c)) for c in range(c0, c1 + 1)]
            while valores and valores[-1] in (None, ""):
                valores.pop()  # o Sheets omite as celulas vazias do fim da linha
            resultado.append(["" if v is None else v for v in valores])
        return resultado

    def get_all_values(self, value_render_option=None, **_kw):
        self._nuvem.registrar_leitura(self.title, value_render_option)
        if self.title in self._nuvem.abas_que_falham_ao_ler:
            raise RuntimeError(f"falha ao ler {self.title} (falso)")
        if not self.celulas:
            return []
        maior_l = max(r for r, _ in self.celulas)
        maior_c = max(c for _, c in self.celulas)
        return [
            ["" if self.celulas.get((r, c)) is None else self.celulas[(r, c)] for c in range(1, maior_c + 1)]
            for r in range(1, maior_l + 1)
        ]


class _PlanilhaFalsa:
    def __init__(self, nuvem: "NuvemFalsa"):
        self._nuvem = nuvem

    def worksheet(self, nome: str):
        if self._nuvem.sem_rede:  # a planilha aberta e reaproveitada: cada chamada fala com a rede de novo
            raise ConnectionError("sem internet (falso)")
        if nome not in self._nuvem.abas:
            raise gspread.WorksheetNotFound(nome)
        return self._nuvem.abas[nome]

    def add_worksheet(self, title, rows, cols):
        self._nuvem.registrar_escrita("add", title)
        aba = _AbaFalsa(self._nuvem, title)
        self._nuvem.abas[title] = aba
        return aba


class NuvemFalsa:
    """O Google Sheets em memoria: abas de celulas, o que foi escrito/lido, e botoes pra simular problemas."""

    def __init__(self):
        self.abas: dict[str, _AbaFalsa] = {}
        self.escritas: list[tuple] = []
        self.opcoes_de_leitura: set = set()
        self.sem_rede = False
        self.falha_ao_escrever = False
        self.abas_que_falham_ao_ler: set[str] = set()
        self.gancho_leitura_meta = None
        self._trava = threading.Lock()

    def registrar_escrita(self, *que) -> None:
        if self.falha_ao_escrever:
            raise ConnectionError("sem internet ao escrever (falso)")
        with self._trava:
            self.escritas.append(que)

    def registrar_leitura(self, aba, opcao) -> None:
        with self._trava:
            self.opcoes_de_leitura.add(opcao)

    def open_by_key(self, chave):
        if self.sem_rede:
            raise ConnectionError("sem internet (falso)")
        return _PlanilhaFalsa(self)

    # ---- apoio dos testes ----
    def meta(self) -> dict:
        aba = self.abas.get(sheets_sync.ABA_META)
        if aba is None:
            return {}
        return {
            "revisao": aba.celulas.get((2, 2)),
            "escritor": aba.celulas.get((3, 2)),
            "editando_por": aba.celulas.get((5, 2)),
            "ultimo_sinal": aba.celulas.get((6, 2)),
        }

    def revisao(self) -> int:
        return int(self.meta().get("revisao") or 0)

    def instantaneo(self) -> dict:
        return {nome: dict(aba.celulas) for nome, aba in self.abas.items() if nome != sheets_sync.ABA_META}

    def cabecalho_e_linhas(self, nome: str) -> int:
        return len(self.abas[nome].get_all_values()) - 1


class _Ambiente:
    """Liga a flag com a nuvem falsa no lugar (leitura E envio); desfaz tudo ao sair."""

    def __init__(self, nuvem: NuvemFalsa):
        self.nuvem = nuvem
        self.log = ColetorDeLog()

    def __enter__(self):
        self._registradores = [logging.getLogger(m.__name__) for m in (sheets_sync, sincronizacao_mod, estado_mod)]
        self._propagavam = [r.propagate for r in self._registradores]
        for registrador in self._registradores:
            registrador.addHandler(self.log)
            registrador.propagate = False
        self._envio_cliente = sheets_sync._obter_cliente
        self._leitura_cliente = leitura_sheets._obter_cliente
        sheets_sync._obter_cliente = lambda: self.nuvem
        leitura_sheets._obter_cliente = lambda: self.nuvem
        sheets_sync._reiniciar_estado()
        config.SINCRONIZACAO_GOOGLE_ATIVADA = True
        return self

    def __exit__(self, *_exc):
        config.SINCRONIZACAO_GOOGLE_ATIVADA = False
        sheets_sync._obter_cliente = self._envio_cliente
        leitura_sheets._obter_cliente = self._leitura_cliente
        sheets_sync._reiniciar_estado()
        sheets_sync._NOME_DA_MAQUINA = None
        for registrador, propagava in zip(self._registradores, self._propagavam):
            registrador.removeHandler(self.log)
            registrador.propagate = propagava


class Maquina:
    """Um computador: pasta propria, arquivo de dados proprio e (por consequencia) estado local proprio."""

    def __init__(self, nome: str, raiz: Path):
        self.nome = nome
        self.pasta = raiz / nome
        self.pasta.mkdir()
        self.arquivo = fx.criar(self.pasta)  # com a flag DESLIGADA: nada vai pra nuvem aqui

    def ativar(self) -> "Maquina":
        fx.apontar_modulos_para(self.arquivo)
        sheets_sync._NOME_DA_MAQUINA = self.nome
        return self

    def estado(self) -> estado_mod.EstadoLocal:
        return estado_mod.ler(self.arquivo)

    def hash(self) -> str:
        return hashlib.sha256(self.arquivo.read_bytes()).hexdigest()


def _normalizado(arquivo: Path) -> dict:
    """As 4 abas de um arquivo, comparaveis (ausente vira None, data vira texto)."""

    def _n(v):
        if v is pd.NaT or v is None:
            return None
        if isinstance(v, float) and v != v:
            return None
        if isinstance(v, pd.Timestamp):
            return v.strftime("%Y-%m-%d")
        return v

    resultado = {}
    for aba, leitor in (
        (bd.ABA_CLIENTES, bd.ler_clientes),
        (bd.ABA_EQUIPAMENTOS, bd.ler_equipamentos),
        (bd.ABA_VENDEDORES, bd.ler_vendedores),
        (bd.ABA_PROPOSTAS, bd.ler_propostas),
    ):
        df = leitor(arquivo)
        resultado[aba] = (tuple(df.columns), [tuple(_n(v) for v in reg.values()) for reg in df.to_dict("records")])
    return resultado


def _cadastrar_dados_dificeis() -> None:
    """Dados que um envio/baixada mal feito estraga: CNPJ so com numeros e zeros na frente, texto que
    comeca com "=", quebra de linha, acento, decimal, campo vazio."""
    clientes_mod.adicionar_cliente(
        {"CPF/CNPJ": CNPJ_COM_ZERO, "CLIENTE": "José D'Ávila Ltda", "TIPO": "Cliente", "VENDEDOR": "Vendedor Exemplo", "CEP": "01310-100"}
    )
    propostas_mod.adicionar_proposta(
        {
            "CPF": CNPJ_COM_ZERO,
            "STATUS": propostas_mod.STATUS_APROVADO,
            "BANCO": "Banco Exemplo",
            "EQUIPAMENTO": "Equipamento Modelo X",
            "VALOR (R$)": 31004.62,
            "MESES": 36,
            "OBSERVAÇÕES": "=1+1\nsegunda linha com acentuação",
        }
    )
    propostas_mod.adicionar_proposta(
        {"CPF": CNPJ_COM_ZERO, "STATUS": propostas_mod.STATUS_EM_ANALISE, "BANCO": "Banco Exemplo",
         "EQUIPAMENTO": "Equipamento Modelo Y", "VALOR (R$)": 1000}
    )  # sem MESES e sem observacao: celulas vazias


def _adicionar_cliente_simples(nome: str, cpf: str) -> None:
    clientes_mod.adicionar_cliente({"CPF/CNPJ": cpf, "CLIENTE": nome, "TIPO": "Cliente", "VENDEDOR": "Vendedor Exemplo"})


# ------------------------------------------------------------------------------------------
# Cenarios
# ------------------------------------------------------------------------------------------

def testar_sem_controle_nao_envia(a: Maquina, nuvem: NuvemFalsa) -> None:
    linha("1) Nuvem sem controle de versao: o envio NAO acontece calado (e nada e escrito la)")
    with _Ambiente(nuvem):
        a.ativar()
        _adicionar_cliente_simples("CLIENTE SEM CONTROLE", CPF_1)
        _esperar_envios()
        estado = sheets_sync.estado_atual()
        assert estado.nivel == sheets_sync.NIVEL_CONFLITO, estado
        assert estado.conflito == sheets_sync.TIPO_SEM_CONTROLE
        assert nuvem.escritas == [], f"nada pode ser escrito na nuvem: {nuvem.escritas}"
        assert bd.CLIENTES_COLUNAS and any(c == "CLIENTE SEM CONTROLE" for c in bd.ler_clientes(a.arquivo)["CLIENTE"])
        assert bd.ABA_CLIENTES in a.estado().abas_pendentes, "a gravacao local fica marcada como pendente, em disco"
        print("OK: sem a aba META o envio e recusado, a alteracao fica salva so aqui e marcada como pendente.")

        _adicionar_cliente_simples("OUTRO CLIENTE", CPF_2)
        _esperar_envios()
        assert nuvem.escritas == [], "com o conflito aberto, novos envios ficam adiados (sem tocar na rede)"
        print("OK: enquanto o conflito espera decisao, novas gravacoes nao tentam a rede.")


def testar_envio_forcado_liga_o_controle(a: Maquina, nuvem: NuvemFalsa) -> None:
    linha("2) Envio deliberado: cria a META, manda as 4 abas, baixa o alarme")
    with _Ambiente(nuvem):
        a.ativar()
        sheets_sync._registrar_conflito(sheets_sync.ConflitoDeSincronizacao(
            sheets_sync.TIPO_SEM_CONTROLE, sheets_sync.MetaNuvem(), None, "x"))
        copia = sincronizacao_mod.enviar_para_a_nuvem_substituindo(a.arquivo, copia_obrigatoria=False)
        _esperar_envios()
        assert copia is None, "nuvem vazia: nao ha o que copiar"
        assert set(nuvem.abas) == {"META", "CLIENTES", "EQUIPAMENTOS", "PROPOSTAS", "VENDEDORES"}, set(nuvem.abas)
        assert nuvem.revisao() == 5, f"1 (criacao) + 4 abas enviadas = 5, veio {nuvem.revisao()}"
        assert a.estado().revisao_conhecida == 5 and a.estado().abas_pendentes == ()
        assert sheets_sync.estado_atual().nivel == sheets_sync.NIVEL_OK
        print("OK: META criada, 4 abas enviadas, este PC sabe a versao 5 e nao tem nada pendente.")

        _adicionar_cliente_simples("CLIENTE NORMAL", CPF_3)
        _esperar_envios()
        assert nuvem.revisao() == 6 and a.estado().revisao_conhecida == 6
        assert sheets_sync.estado_atual().nivel == sheets_sync.NIVEL_OK
        print("OK: com o controle ligado, cada gravacao envia e sobe a versao (6).")


def testar_segundo_computador_nao_sobrescreve(a: Maquina, b: Maquina, nuvem: NuvemFalsa) -> None:
    linha("3) O outro computador NAO consegue sobrescrever a nuvem (a trava de versao)")
    with _Ambiente(nuvem):
        b.ativar()
        antes = nuvem.instantaneo()
        rev_antes = nuvem.revisao()
        _adicionar_cliente_simples("CLIENTE DO PC B", CPF_4)
        _esperar_envios()
        estado = sheets_sync.estado_atual()
        assert estado.nivel == sheets_sync.NIVEL_CONFLITO and estado.conflito == sheets_sync.TIPO_DIVERGENTE, estado
        assert nuvem.instantaneo() == antes and nuvem.revisao() == rev_antes, "a nuvem ficou IDENTICA"
        assert not any("CLIENTE DO PC B" in str(v) for v in nuvem.abas["CLIENTES"].celulas.values())
        assert any(r["CLIENTE"] == "CLIENTE DO PC B" for r in bd.ler_clientes(b.arquivo).to_dict("records")), "e o dado local ficou salvo"
        assert bd.ABA_CLIENTES in b.estado().abas_pendentes
        print("OK: o envio do PC B foi recusado, a nuvem ficou intacta e o dado dele segue salvo (pendente).")

    linha("3b) MUTACAO: sem a trava, o mesmo cenario apaga o trabalho do outro PC")
    with _Ambiente(nuvem):
        b.ativar()
        original = sheets_sync._conferir_versao
        sheets_sync._conferir_versao = lambda meta, local: None  # tira a trava
        try:
            _adicionar_cliente_simples("CLIENTE MUTACAO", CPF_5)
            _esperar_envios()
        finally:
            sheets_sync._conferir_versao = original
        # o PC B (que nao conhece o CLIENTE NORMAL do PC A) sobrescreveu a aba: o do PC A sumiu
        nomes_na_nuvem = {str(v) for v in nuvem.abas["CLIENTES"].celulas.values()}
        assert "CLIENTE NORMAL" not in nomes_na_nuvem, "sem a trava, o cliente do PC A some da nuvem (e por isso ela existe)"
        print("OK: sem a trava o cliente do PC A SOME da nuvem - a mutacao e pega, a trava e o que protege.")


def _restaurar_nuvem_de_a(a: Maquina, nuvem: NuvemFalsa) -> None:
    """Depois da mutacao acima a nuvem ficou 'suja': refaz o estado com o PC A como dono da verdade."""
    with _Ambiente(nuvem):
        a.ativar()
        estado_mod.definir_revisao(nuvem.revisao(), a.arquivo)
        sincronizacao_mod.sincronizar_tudo_agora(a.arquivo)
        _esperar_envios()


def testar_verificar_ao_abrir(a: Maquina, b: Maquina, nuvem: NuvemFalsa) -> None:
    linha("4) verificar_ao_abrir: cada situacao")
    S = sincronizacao_mod
    with _Ambiente(nuvem):
        a.ativar()
        estado_mod.definir_revisao(nuvem.revisao(), a.arquivo)
        estado_mod.registrar_download(nuvem.revisao(), a.arquivo)
        assert S.verificar_ao_abrir(a.arquivo).tipo == S.SITUACAO_EM_DIA
        estado_mod.marcar_pendente(bd.ABA_CLIENTES, a.arquivo)
        assert S.verificar_ao_abrir(a.arquivo).tipo == S.SITUACAO_LOCAL_PENDENTE
        print("OK: mesma versao: 'em dia', ou 'local pendente' se tem aba nao enviada.")

        b.ativar()
        estado_mod.registrar_download(nuvem.revisao() - 1, b.arquivo)  # o B conhece uma versao antiga
        assert S.verificar_ao_abrir(b.arquivo).tipo == S.SITUACAO_NUVEM_MAIS_NOVA
        estado_mod.marcar_pendente(bd.ABA_PROPOSTAS, b.arquivo)
        assert S.verificar_ao_abrir(b.arquivo).tipo == S.SITUACAO_CONFLITO
        print("OK: versao diferente: 'nuvem mais nova' (limpo) ou 'conflito' (com pendencia).")

        nuvem.sem_rede = True
        situacao = S.verificar_ao_abrir(b.arquivo)
        assert situacao.tipo == S.SITUACAO_SEM_REDE and "sem internet" in situacao.detalhe
        nuvem.sem_rede = False
        print("OK: sem internet devolve 'sem rede' (o app abre normal), sem levantar erro.")

        config.SINCRONIZACAO_GOOGLE_ATIVADA = False
        assert S.verificar_ao_abrir(b.arquivo).tipo == S.SITUACAO_DESATIVADA
        config.SINCRONIZACAO_GOOGLE_ATIVADA = True

        vazia = NuvemFalsa()
        sheets_sync._obter_cliente = lambda: vazia
        assert S.verificar_ao_abrir(b.arquivo).tipo == S.SITUACAO_SEM_CONTROLE
        sheets_sync._obter_cliente = lambda: nuvem
        print("OK: desativada -> 'desativada'; nuvem sem META -> 'sem controle'.")


def testar_baixar_da_nuvem(a: Maquina, b: Maquina, nuvem: NuvemFalsa) -> None:
    linha("5) Baixar da nuvem: o PC B fica igual ao que a nuvem tem, com backup, sem mandar nada de volta")
    with _Ambiente(nuvem):
        b.ativar()
        estado_mod.registrar_download(nuvem.revisao() - 2, b.arquivo)
        estado_mod.marcar_pendente(bd.ABA_CLIENTES, b.arquivo)
        hash_antes = b.hash()
        escritas_antes = len(nuvem.escritas)
        assert _normalizado(b.arquivo) != _normalizado(a.arquivo)
        sheets_sync._pendentes[bd.ABA_CLIENTES] = bd.ler_clientes(b.arquivo)  # um envio velho esperando na fila
        epoca_antes = sheets_sync._epoca

        resultado = sincronizacao_mod.baixar_da_nuvem(b.arquivo)
        _esperar_envios()

        assert _normalizado(b.arquivo) == _normalizado(a.arquivo), "o PC B ficou IGUAL ao PC A (incluindo os dados dificeis)"
        print("OK: depois de baixar, as 4 abas do PC B sao identicas as do PC A (CNPJ com zeros, '=1+1', acentos, decimal, vazios).")

        assert resultado.backup.exists() and resultado.backup.parent.name == "backups"
        assert f".{backup_mod.MOTIVO_PRE_NUVEM}-" in resultado.backup.name
        assert hashlib.sha256(resultado.backup.read_bytes()).hexdigest() == hash_antes, "o backup e o arquivo de ANTES"
        assert any(b_.motivo == backup_mod.MOTIVO_PRE_NUVEM for b_ in backup_mod.listar_backups(b.arquivo))
        print("OK: um backup 'pre-nuvem' com o arquivo de antes foi guardado e aparece na lista de backups.")

        assert len(nuvem.escritas) == escritas_antes, "baixar NAO pode escrever nada na nuvem"
        assert not sheets_sync._pendentes and sheets_sync.estado_atual().em_andamento == 0
        assert sheets_sync._epoca == epoca_antes + 1, "baixar tem que descartar os envios velhos (nova epoca)"
        assert b.estado().revisao_conhecida == nuvem.revisao() and b.estado().abas_pendentes == ()
        assert sheets_sync.estado_atual().conflito == ""
        print("OK: nenhuma escrita na nuvem, nada na fila, o estado local adotou a versao da nuvem.")

        assert "UNFORMATTED_VALUE" in nuvem.opcoes_de_leitura, "a leitura tem que ser SEM formatacao (senao decimal/zero vira texto errado)"
        print("OK: a leitura da nuvem usa 'sem formatacao'.")

        cnpj = bd.ler_clientes(b.arquivo)
        assert CNPJ_COM_ZERO in set(cnpj["CPF/CNPJ"]), "o CNPJ so com numeros voltou com os zeros da frente"


def testar_baixar_recusas(a: Maquina, b: Maquina, nuvem: NuvemFalsa) -> None:
    linha("6) Baixar RECUSA (sem alterar nada) quando nao e seguro")
    E = sincronizacao_mod.ErroNuvem
    with _Ambiente(nuvem):
        b.ativar()
        # 6a nuvem sem controle
        vazia = NuvemFalsa()
        sheets_sync._obter_cliente = lambda: vazia
        h = b.hash()
        try:
            sincronizacao_mod.baixar_da_nuvem(b.arquivo)
            raise AssertionError("deveria recusar: nuvem sem controle")
        except E as exc:
            assert "controle de versão" in str(exc)
        assert b.hash() == h
        sheets_sync._obter_cliente = lambda: nuvem
        print("OK: nuvem sem controle de versao -> recusa, arquivo intacto.")

        # 6b a nuvem muda no meio do download
        def _muda_no_meio(n: NuvemFalsa) -> None:
            if getattr(_muda_no_meio, "feito", False):
                return
            if len(n.opcoes_de_leitura) and n.abas["CLIENTES"].celulas and _muda_no_meio.leituras_de_meta >= 1:
                n.abas[sheets_sync.ABA_META].celulas[(2, 2)] = n.revisao() + 1
                _muda_no_meio.feito = True
            _muda_no_meio.leituras_de_meta += 1

        _muda_no_meio.leituras_de_meta = 0
        rev = nuvem.revisao()
        nuvem.gancho_leitura_meta = _muda_no_meio
        h = b.hash()
        try:
            sincronizacao_mod.baixar_da_nuvem(b.arquivo)
            raise AssertionError("deveria recusar: a nuvem mudou durante o download")
        except E as exc:
            assert "enquanto baixava" in str(exc)
        finally:
            nuvem.gancho_leitura_meta = None
        assert b.hash() == h
        nuvem.abas[sheets_sync.ABA_META].celulas[(2, 2)] = rev  # desfaz a mudanca simulada
        print("OK: a nuvem mudou durante o download -> recusa, arquivo intacto.")

        # 6c aba vazia na nuvem com linhas aqui (envio interrompido)
        guardado = dict(nuvem.abas["PROPOSTAS"].celulas)
        nuvem.abas["PROPOSTAS"].celulas.clear()
        nuvem.abas["PROPOSTAS"].celulas[(1, 1)] = "DATA"  # so o cabecalho
        h = b.hash()
        try:
            sincronizacao_mod.baixar_da_nuvem(b.arquivo)
            raise AssertionError("deveria recusar: aba vazia na nuvem")
        except E as exc:
            assert "PROPOSTAS" in str(exc) and "interrompido" in str(exc)
        assert b.hash() == h
        nuvem.abas["PROPOSTAS"].celulas.update(guardado)
        print("OK: aba vazia na nuvem (envio interrompido) com linhas aqui -> recusa, arquivo intacto.")

        # 6d Excel com o arquivo aberto
        trava = bd._caminho_arquivo_bloqueio(b.arquivo)
        trava.write_bytes(b"")
        try:
            sincronizacao_mod.baixar_da_nuvem(b.arquivo)
            raise AssertionError("deveria recusar: arquivo aberto no Excel")
        except bd.ErroArquivoBloqueado:
            pass
        finally:
            trava.unlink()
        assert b.hash() == h
        print("OK: arquivo aberto no Excel -> recusa, arquivo intacto.")

        # 6e uma aba que falha ao ler: tudo-ou-nada
        nuvem.abas_que_falham_ao_ler = {"VENDEDORES"}
        try:
            sincronizacao_mod.baixar_da_nuvem(b.arquivo)
            raise AssertionError("deveria falhar")
        except RuntimeError:
            pass
        finally:
            nuvem.abas_que_falham_ao_ler = set()
        assert b.hash() == h and not [x for x in backup_mod.listar_backups(b.arquivo) if x.motivo == backup_mod.MOTIVO_PRE_NUVEM][1:]
        print("OK: uma aba que falha ao ler -> nada e trocado (tudo ou nada).")


def testar_manter_o_meu(a: Maquina, b: Maquina, nuvem: NuvemFalsa) -> None:
    linha("7) Conflito resolvido com 'manter o meu': guarda a copia da nuvem e sobrescreve de proposito")
    with _Ambiente(nuvem):
        b.ativar()
        estado_mod.registrar_download(nuvem.revisao() - 1, b.arquivo)  # conheco uma versao velha: vai dar conflito
        _adicionar_cliente_simples("CLIENTE DO PC B 2", fx.cpf_ficticio(400_100_000))
        _esperar_envios()
        assert sheets_sync.estado_atual().nivel == sheets_sync.NIVEL_CONFLITO
        conteudo_da_nuvem_antes = _normalizado(a.arquivo)

        copia = sincronizacao_mod.enviar_para_a_nuvem_substituindo(b.arquivo, copia_obrigatoria=True)
        _esperar_envios()
        assert copia is not None and f".{backup_mod.MOTIVO_COPIA_DA_NUVEM}-" in copia.name
        assert _normalizado(copia) == conteudo_da_nuvem_antes, "a copia tem o que a nuvem tinha ANTES"
        assert sheets_sync.estado_atual().nivel == sheets_sync.NIVEL_OK and sheets_sync.estado_atual().conflito == ""
        assert b.estado().revisao_conhecida == nuvem.revisao() and b.estado().abas_pendentes == ()
        assert any(str(v) == "CLIENTE DO PC B 2" for v in nuvem.abas["CLIENTES"].celulas.values())
        print("OK: copia da nuvem guardada, o que esta no PC B foi pra nuvem, conflito resolvido, nada pendente.")

        # a copia obrigatoria que nao da pra fazer aborta ANTES de sobrescrever
        estado_mod.registrar_download(nuvem.revisao() - 1, b.arquivo)
        snapshot = nuvem.instantaneo()
        nuvem.abas_que_falham_ao_ler = {"CLIENTES"}
        try:
            sincronizacao_mod.enviar_para_a_nuvem_substituindo(b.arquivo, copia_obrigatoria=True)
            raise AssertionError("deveria abortar sem a copia")
        except sincronizacao_mod.ErroNuvem as exc:
            assert "Nada foi enviado" in str(exc)
        finally:
            nuvem.abas_que_falham_ao_ler = set()
        _esperar_envios()
        assert nuvem.instantaneo() == snapshot
        print("OK: se nao da pra guardar a copia da nuvem, aborta e a nuvem nao e tocada.")


def testar_pendentes_em_disco(a: Maquina, nuvem: NuvemFalsa) -> None:
    linha("8) Pendencias sobrevivem a fechar o app (estado em disco)")
    with _Ambiente(nuvem) as amb:
        a.ativar()
        estado_mod.registrar_download(nuvem.revisao(), a.arquivo)
        nuvem.falha_ao_escrever = True
        _adicionar_cliente_simples("OFFLINE 1", fx.cpf_ficticio(400_200_000))
        _esperar_envios()
        assert sheets_sync.estado_atual().nivel == sheets_sync.NIVEL_FALHOU
        assert bd.ABA_CLIENTES in a.estado().abas_pendentes
        assert len(amb.log.avisos_com_traceback()) >= 1, "a falha vai pro log"
        print("OK: sem internet o envio falha, e a aba continua pendente EM DISCO.")

        # "fecha o app": some a fila em memoria; ao reabrir, so o disco lembra
        sheets_sync._reiniciar_estado()
        nuvem.falha_ao_escrever = False
        situacao = sincronizacao_mod.verificar_ao_abrir(a.arquivo)
        assert situacao.tipo == sincronizacao_mod.SITUACAO_LOCAL_PENDENTE, situacao
        assert sincronizacao_mod.enviar_pendentes_do_estado(a.arquivo) == [bd.ABA_CLIENTES]
        _esperar_envios()
        assert a.estado().abas_pendentes == () and a.estado().revisao_conhecida == nuvem.revisao()
        assert any(str(v) == "OFFLINE 1" for v in nuvem.abas["CLIENTES"].celulas.values())
        print("OK: ao reabrir, 'local pendente' -> reenvia so o que faltava e limpa a pendencia.")


def testar_sucesso_antigo_nao_limpa_pendencia_nova(a: Maquina, nuvem: NuvemFalsa) -> None:
    linha("9) O sucesso tardio de uma tentativa ANTIGA nao apaga a pendencia de uma tentativa mais NOVA")
    with _Ambiente(nuvem):
        a.ativar()
        estado_mod.registrar_download(nuvem.revisao(), a.arquivo)
        liberar_antiga, liberar_nova = threading.Event(), threading.Event()
        chegou_antiga, chegou_nova = threading.Event(), threading.Event()
        antigo, novo = pd.DataFrame({"A": [1]}), pd.DataFrame({"A": [2]})

        def envio(aba, df):
            if df is antigo:
                chegou_antiga.set()
                assert liberar_antiga.wait(5)
            else:
                chegou_nova.set()
                assert liberar_nova.wait(5)

        original = sheets_sync._sincronizar_agora
        sheets_sync._sincronizar_agora = envio
        try:
            sheets_sync.sincronizar_em_background("ABA_X", antigo)
            assert chegou_antiga.wait(5)
            sheets_sync.sincronizar_em_background("ABA_X", novo)
            assert chegou_nova.wait(5)
            liberar_antiga.set()  # a ANTIGA termina com sucesso, DEPOIS de a nova ja estar pendente
            _esperar(lambda: sheets_sync.estado_atual().em_andamento == 1)
            assert "ABA_X" in a.estado().abas_pendentes, "a pendencia da tentativa NOVA nao pode ser apagada pela antiga"
            liberar_nova.set()
            _esperar_envios()
            assert "ABA_X" not in a.estado().abas_pendentes
        finally:
            sheets_sync._sincronizar_agora = original
        print("OK: so a ultima tentativa, ao confirmar, limpa a pendencia em disco.")


def testar_envio_velho_e_descartado_depois_de_baixar(a: Maquina, nuvem: NuvemFalsa) -> None:
    linha("10) Um envio que ja estava na fila e DESCARTADO depois de baixar (nao sobrescreve a nuvem com dado velho)")
    with _Ambiente(nuvem):
        a.ativar()
        estado_mod.registrar_download(nuvem.revisao(), a.arquivo)
        snapshot = nuvem.instantaneo()
        escritas_antes, revisao_antes = len(nuvem.escritas), nuvem.revisao()
        abriu = threading.Event()
        original_abrir = nuvem.open_by_key

        def abrir_e_avisar(chave):
            abriu.set()
            return original_abrir(chave)

        nuvem.open_by_key = abrir_e_avisar
        try:
            with sheets_sync.bloqueio_de_envio():  # segura o envio no portao, como um download em andamento
                sheets_sync.sincronizar_em_background(bd.ABA_CLIENTES, bd.ler_clientes(a.arquivo))
                assert abriu.wait(5)
                time.sleep(0.1)  # a thread ja esta esperando pelo portao
                sheets_sync.descartar_envios_velhos()  # o "baixar" terminou: o que estava na fila ficou velho
            _esperar_envios()
        finally:
            nuvem.open_by_key = original_abrir
        assert nuvem.instantaneo() == snapshot, "o envio velho nao pode ter escrito na nuvem"
        assert len(nuvem.escritas) == escritas_antes and nuvem.revisao() == revisao_antes, "nem uma escrita, nem a versao subiu"
        assert sheets_sync.estado_atual().nivel != sheets_sync.NIVEL_FALHOU
        print("OK: o envio disparado antes do download e descartado (nem escreve, nem conta como falha).")


def testar_sinal_de_outro_computador(a: Maquina, b: Maquina, nuvem: NuvemFalsa) -> None:
    linha("11) Aviso de 'outro computador ativo' (sinal de vida na META)")
    with _Ambiente(nuvem):
        # sem META nao escreve nada
        vazia = NuvemFalsa()
        sheets_sync._obter_cliente = lambda: vazia
        a.ativar()
        sheets_sync.registrar_sinal()
        assert vazia.escritas == [] and sheets_sync.estado_atual().aviso == ""
        sheets_sync._obter_cliente = lambda: nuvem
        print("OK: sem controle de versao, o sinal nao escreve nada.")

        a.ativar()
        sheets_sync.registrar_sinal()
        assert nuvem.meta()["editando_por"] == "A"
        b.ativar()
        estado_mod.registrar_download(nuvem.revisao(), b.arquivo)
        meta = sheets_sync.registrar_sinal()  # o B enxerga o A
        outro = sheets_sync.outro_computador_ativo(meta)
        assert outro is not None and outro[0] == "A"
        estado = sheets_sync.estado_atual()
        assert estado.aviso == "Outro computador ativo" and "A" in estado.aviso_detalhe and estado.nivel == sheets_sync.NIVEL_ATENCAO
        assert nuvem.meta()["editando_por"] == "B", "e o B registra o proprio sinal"
        print("OK: o PC B ve que o A esta ativo (aviso + nivel 'atencao') e registra o dele.")

        # o A, ao sair, so limpa o que e SEU
        a.ativar()
        sheets_sync.limpar_sinal()
        assert nuvem.meta()["editando_por"] == "B", "o A nao apaga o sinal do B"
        b.ativar()
        sheets_sync.limpar_sinal()
        assert nuvem.meta()["editando_por"] in ("", None)
        print("OK: limpar o sinal so apaga o proprio (nunca o de outro computador).")

        # expira sozinho
        a.ativar()
        sheets_sync.registrar_sinal()
        b.ativar()
        original = sheets_sync._agora_utc
        sheets_sync._agora_utc = lambda: original() + sheets_sync.JANELA_DO_SINAL + timedelta(seconds=30)
        try:
            meta = sheets_sync.registrar_sinal()
            assert sheets_sync.outro_computador_ativo(meta) is None
            assert sheets_sync.estado_atual().aviso != "Outro computador ativo"
        finally:
            sheets_sync._agora_utc = original
        print("OK: um sinal antigo (PC fechado/travado) expira sozinho e nao gera aviso.")

        # nuvem mais nova, sem nada pendente, vira aviso (sem ser modal)
        b.ativar()
        estado_mod.registrar_download(nuvem.revisao() - 1, b.arquivo)
        sheets_sync.limpar_sinal()
        a.ativar()
        sheets_sync.limpar_sinal()
        b.ativar()
        sheets_sync.registrar_sinal()
        assert sheets_sync.estado_atual().aviso == "Nuvem com dados mais novos"
        print("OK: nuvem em versao mais nova + nada pendente vira o aviso 'Nuvem com dados mais novos'.")


def testar_restaurar_backup_marca_pendente(a: Maquina, nuvem: NuvemFalsa) -> None:
    linha("12) Restaurar um backup marca as 4 abas como pendentes (o arquivo mudou por fora dos envios)")
    with _Ambiente(nuvem):
        a.ativar()
        estado_mod.registrar_download(nuvem.revisao(), a.arquivo)
        manual = backup_mod.fazer_backup(backup_mod.MOTIVO_MANUAL, a.arquivo)
        backup_mod.restaurar_backup(manual, a.arquivo)
        assert set(a.estado().abas_pendentes) == {bd.ABA_CLIENTES, bd.ABA_EQUIPAMENTOS, bd.ABA_PROPOSTAS, bd.ABA_VENDEDORES}
        print("OK: depois de Restaurar, as 4 abas ficam marcadas como pendentes em disco.")


def testar_estado_corrompido_e_atomico(a: Maquina) -> None:
    linha("13) Estado local: arquivo ilegivel vira 'nunca sincronizou' (sem quebrar) e nunca fica pela metade")
    with _Ambiente(NuvemFalsa()) as amb:
        a.ativar()
        arquivo_estado = estado_mod._arquivo(a.arquivo)
        arquivo_estado.write_text("{isto nao e json", encoding="utf-8")
        assert estado_mod.ler(a.arquivo) == estado_mod.EstadoLocal()
        assert any("ilegivel" in r.getMessage() for r in amb.log.registros)
        estado_mod.marcar_pendente(bd.ABA_CLIENTES, a.arquivo)
        assert estado_mod.ler(a.arquivo).abas_pendentes == (bd.ABA_CLIENTES,)
        assert not list(a.pasta.glob("*.tmp")), "nenhum temporario sobrando"
        arquivo_estado.unlink()
        assert estado_mod.ler(a.arquivo) == estado_mod.EstadoLocal()
        print("OK: JSON ilegivel -> estado vazio + aviso no log; a gravacao e atomica (sem .tmp sobrando).")


def _copia_sem_controle(nuvem: NuvemFalsa) -> NuvemFalsa:
    """Uma nuvem com as MESMAS abas de dados, mas sem a META (como a planilha real antes da versao nova)."""
    outra = NuvemFalsa()
    for nome, aba in nuvem.abas.items():
        if nome == sheets_sync.ABA_META:
            continue
        copia = _AbaFalsa(outra, nome)
        copia.celulas = dict(aba.celulas)
        outra.abas[nome] = copia
    return outra


def _usar_nuvem(nuvem: NuvemFalsa) -> None:
    sheets_sync._obter_cliente = lambda: nuvem
    leitura_sheets._obter_cliente = lambda: nuvem


def testar_planilha_vazia(raiz: Path) -> None:
    linha("14) Planilha vazia: 4 abas com os cabecalhos certos, e nunca por cima de um arquivo existente")
    pasta = raiz / "vazia"
    arquivo = pasta / "controle_financiamentos.dat"
    bd.criar_planilha_vazia(arquivo)
    assert arquivo.exists()
    assert list(bd.ler_clientes(arquivo).columns) == bd.CLIENTES_COLUNAS and len(bd.ler_clientes(arquivo)) == 0
    assert len(bd.ler_equipamentos(arquivo)) == 0 and len(bd.ler_vendedores(arquivo)) == 0
    assert list(bd.ler_propostas(arquivo).columns) == bd.PROPOSTAS_COLUNAS and len(bd.ler_propostas(arquivo)) == 0
    bd.ler_aba(arquivo, bd.ABA_CLIENTES, bd.CLIENTES_COLUNAS, conferir_cabecalho=True)  # cabecalho no formato esperado
    print("OK: a planilha nova le sem erro, com as 4 abas vazias e os cabecalhos que o app confere.")

    h = hashlib.sha256(arquivo.read_bytes()).hexdigest()
    try:
        bd.criar_planilha_vazia(arquivo)
        raise AssertionError("deveria recusar: o arquivo ja existe")
    except FileExistsError:
        pass
    assert hashlib.sha256(arquivo.read_bytes()).hexdigest() == h
    print("OK: com arquivo ja existente, recusa e nao toca nele.")


def testar_baixar_ligando_o_controle(a: Maquina, b: Maquina, nuvem: NuvemFalsa) -> None:
    linha("15) Nuvem SEM controle: 'baixar da nuvem' (ligando o controle) traz os dados e liga a trava, sem reenviar nada")
    sem_controle = _copia_sem_controle(nuvem)
    with _Ambiente(sem_controle):
        _usar_nuvem(sem_controle)
        b.ativar()
        hash_antes = b.hash()
        assert _normalizado(b.arquivo) != _normalizado(a.arquivo)

        resultado = sincronizacao_mod.baixar_da_nuvem(b.arquivo, ligar_controle=True)
        assert _normalizado(b.arquivo) == _normalizado(a.arquivo), "o PC B ficou igual ao que a nuvem tem"
        assert resultado.ligou_controle and resultado.meta.revisao == 1
        assert sem_controle.revisao() == 1, "a META foi criada (versao 1)"
        abas_escritas = {e[1] for e in sem_controle.escritas}
        assert abas_escritas == {sheets_sync.ABA_META}, f"so a META pode ter sido escrita, nao os dados: {sem_controle.escritas}"
        assert b.estado().revisao_conhecida == 1 and b.estado().abas_pendentes == ()
        assert resultado.backup is not None and hashlib.sha256(resultado.backup.read_bytes()).hexdigest() == hash_antes
        print("OK: dados baixados, META criada (versao 1) sem reenviar nenhuma aba, backup do arquivo de antes guardado.")

        _adicionar_cliente_simples("DEPOIS DE LIGAR O CONTROLE", fx.cpf_ficticio(400_300_000))
        _esperar_envios()
        assert sheets_sync.estado_atual().nivel == sheets_sync.NIVEL_OK and sem_controle.revisao() == 2
        assert b.estado().revisao_conhecida == 2
        print("OK: a gravacao seguinte envia normalmente pela trava (versao 2).")

    linha("15b) Outro computador liga o controle NO MEIO do download: recusa, nada muda")
    sem_controle = _copia_sem_controle(nuvem)
    with _Ambiente(sem_controle):
        _usar_nuvem(sem_controle)
        b.ativar()
        original = sincronizacao_mod._ler_dados_da_nuvem

        def ler_e_outro_pc_liga(*args, **kw):
            dados = original(*args, **kw)
            sheets_sync._garantir_meta(_PlanilhaFalsa(sem_controle))
            return dados

        sincronizacao_mod._ler_dados_da_nuvem = ler_e_outro_pc_liga
        h = b.hash()
        try:
            sincronizacao_mod.baixar_da_nuvem(b.arquivo, ligar_controle=True)
            raise AssertionError("deveria recusar: a nuvem ganhou controle durante o download")
        except sincronizacao_mod.ErroNuvem as exc:
            assert "enquanto baixava" in str(exc)
        finally:
            sincronizacao_mod._ler_dados_da_nuvem = original
        assert b.hash() == h
        print("OK: a META apareceu durante o download -> recusa, arquivo intacto.")


def testar_baixar_sem_planilha_local(a: Maquina, nuvem: NuvemFalsa, raiz: Path) -> None:
    linha("16) Primeira abertura: sem arquivo local, baixar CRIA o arquivo com os dados da nuvem")
    pasta = raiz / "C"
    pasta.mkdir()
    arquivo = pasta / "controle_financiamentos.dat"
    with _Ambiente(nuvem):
        fx.apontar_modulos_para(arquivo)
        sheets_sync._NOME_DA_MAQUINA = "C"
        escritas_antes = len(nuvem.escritas)
        resultado = sincronizacao_mod.baixar_da_nuvem(arquivo)
        assert arquivo.exists() and _normalizado(arquivo) == _normalizado(a.arquivo)
        assert resultado.backup is None and not resultado.ligou_controle
        assert estado_mod.ler(arquivo).revisao_conhecida == nuvem.revisao()
        assert len(nuvem.escritas) == escritas_antes
        assert not (pasta / "backups").exists() or not list((pasta / "backups").iterdir())
        print("OK: arquivo criado igual ao da nuvem, sem backup (nao havia o que guardar), nada escrito na nuvem.")

        arquivo.unlink()
        estado_mod._arquivo(arquivo).unlink(missing_ok=True)
        original = sincronizacao_mod._gravar_dados_no_arquivo
        sincronizacao_mod._gravar_dados_no_arquivo = lambda *_a: (_ for _ in ()).throw(OSError("disco cheio (falso)"))
        try:
            sincronizacao_mod.baixar_da_nuvem(arquivo)
            raise AssertionError("deveria falhar")
        except OSError:
            pass
        finally:
            sincronizacao_mod._gravar_dados_no_arquivo = original
        assert not arquivo.exists(), "se a gravacao falha, nao pode sobrar uma planilha vazia no lugar"
        print("OK: se gravar falha, a planilha recem-criada e apagada (nao fica uma vazia 'de verdade').")

    sem_controle = _copia_sem_controle(nuvem)
    with _Ambiente(sem_controle):
        _usar_nuvem(sem_controle)
        fx.apontar_modulos_para(arquivo)
        resultado = sincronizacao_mod.baixar_da_nuvem(arquivo, ligar_controle=True)
        assert arquivo.exists() and resultado.ligou_controle and sem_controle.revisao() == 1
        assert estado_mod.ler(arquivo).revisao_conhecida == 1
        print("OK: sem arquivo local E nuvem sem controle: baixa, cria o arquivo e liga o controle.")


def testar_consulta_da_primeira_abertura(a: Maquina, nuvem: NuvemFalsa, raiz: Path) -> None:
    linha("17) Consulta da primeira abertura: desativada / sem chave / vazia / com dados / sem internet")
    S = sincronizacao_mod
    chave_falsa = raiz / "chave_falsa.json"
    chave_falsa.write_text("{}", encoding="utf-8")
    chave_original = config.CAMINHO_CREDENCIAIS_GOOGLE
    try:
        with _Ambiente(nuvem):
            config.SINCRONIZACAO_GOOGLE_ATIVADA = False
            assert S.consultar_nuvem_para_primeira_abertura().tipo == S.NUVEM_DESATIVADA
            config.SINCRONIZACAO_GOOGLE_ATIVADA = True

            config.CAMINHO_CREDENCIAIS_GOOGLE = raiz / "nao_existe.json"
            assert S.consultar_nuvem_para_primeira_abertura().tipo == S.NUVEM_SEM_CHAVE
            config.CAMINHO_CREDENCIAIS_GOOGLE = chave_falsa

            _usar_nuvem(NuvemFalsa())
            assert S.consultar_nuvem_para_primeira_abertura().tipo == S.NUVEM_VAZIA
            _usar_nuvem(nuvem)
            consulta = S.consultar_nuvem_para_primeira_abertura()
            assert consulta.tipo == S.NUVEM_COM_DADOS
            assert consulta.linhas[bd.ABA_CLIENTES] == len(bd.ler_clientes(a.arquivo))
            assert consulta.linhas[bd.ABA_PROPOSTAS] == len(bd.ler_propostas(a.arquivo))

            nuvem.sem_rede = True
            consulta = S.consultar_nuvem_para_primeira_abertura()
            nuvem.sem_rede = False
            assert consulta.tipo == S.NUVEM_SEM_REDE and "sem internet" in consulta.detalhe
            print("OK: cada situacao vira o tipo certo (com dados: as contagens batem com as da nuvem; sem rede: nunca levanta).")
    finally:
        config.CAMINHO_CREDENCIAIS_GOOGLE = chave_original


def main() -> None:
    raiz = Path(tempfile.mkdtemp(prefix="_smoke_sync_versao_"))
    registro_antes = fx.instantaneo_do_registro()
    listagem_real = sorted(p.name for p in config.DIRETORIO_DADOS.glob("*")) if config.DIRETORIO_DADOS.exists() else []
    try:
        sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
        a = Maquina("A", raiz)
        b = Maquina("B", raiz)
        a.ativar()
        _cadastrar_dados_dificeis()
        nuvem = NuvemFalsa()

        testar_sem_controle_nao_envia(a, nuvem)
        testar_envio_forcado_liga_o_controle(a, nuvem)
        testar_segundo_computador_nao_sobrescreve(a, b, nuvem)
        _restaurar_nuvem_de_a(a, nuvem)
        testar_verificar_ao_abrir(a, b, nuvem)
        testar_baixar_da_nuvem(a, b, nuvem)
        testar_baixar_recusas(a, b, nuvem)
        testar_manter_o_meu(a, b, nuvem)
        testar_pendentes_em_disco(a, nuvem)
        testar_sucesso_antigo_nao_limpa_pendencia_nova(a, nuvem)
        testar_envio_velho_e_descartado_depois_de_baixar(a, nuvem)
        testar_sinal_de_outro_computador(a, b, nuvem)
        testar_restaurar_backup_marca_pendente(a, nuvem)
        testar_estado_corrompido_e_atomico(a)
        testar_planilha_vazia(raiz)
        _restaurar_nuvem_de_a(a, nuvem)
        testar_baixar_ligando_o_controle(a, b, nuvem)
        testar_baixar_sem_planilha_local(a, nuvem, raiz)
        testar_consulta_da_primeira_abertura(a, nuvem, raiz)

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
