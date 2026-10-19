"""Testa a consulta de CEP (ViaCEP) e de CNPJ (BrasilAPI) que preenche o cadastro do cliente (Fase 3).

Parte 1 (core/consulta_externa.py): sucesso, CEP inexistente, sem internet, tempo esgotado, resposta estranha, CNPJ
invalido, e a garantia de que CPF/entrada invalida nunca chega ao ponto de HTTP. Parte 2 (Ficha de Cliente): o botao
"Buscar" so ao clicar, preenchendo so o que esta vazio e perguntando antes de trocar texto ja digitado; falha vira
aviso e o formulario segue usavel; nada e gravado sozinho.

A internet NUNCA e usada: o HTTP e simulado e `urlopen`/`socket.connect` reais derrubam o teste. Planilha 100%
ficticia em pasta temporaria, preferencias isoladas e o Google desligado.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_consulta_externa.py
"""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False
import fixture_ficticia as fx
from ambiente_de_teste import Mensagens
from core import clientes as clientes_mod
from core import consulta_externa as ce
from core import data_store as bd
from core import data_store_sheets as nuvem
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import sheets_sync
from desktop.screens.ficha_cliente_screen import FichaClienteScreen
from desktop.theme import TEMA_ESCURO, build_stylesheet

ADMIN = sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador")
CNPJ_FICTICIO = "11.222.333/0001-81"
CEP_FICTICIO = "12345-678"

VIACEP_OK = {
    "cep": "12345-678", "logradouro": "Rua Exemplo", "complemento": "lado par", "bairro": "Bairro Exemplo",
    "localidade": "Cidade Exemplo", "uf": "ce", "ibge": "0000000",
}
BRASILAPI_OK = {
    "cnpj": "11222333000181", "razao_social": "EMPRESA EXEMPLO LTDA", "nome_fantasia": "EXEMPLO",
    "descricao_tipo_de_logradouro": "AVENIDA", "logradouro": "DAS FLORES", "numero": "100",
    "complemento": "SALA 2", "bairro": "CENTRO EXEMPLO", "municipio": "CIDADE EXEMPLO", "uf": "CE", "cep": "12345678",
}


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _processar() -> None:
    for _ in range(4):
        QApplication.processEvents()


class RedeSimulada:
    """Troca `ce._http_get` por uma resposta de mentira e anota as URLs pedidas."""

    def __init__(self):
        self.urls: list[str] = []
        self.resposta: object = b"{}"
        self._original = ce._http_get

    def __enter__(self):
        def _falso(url: str, timeout: float) -> bytes:
            self.urls.append(url)
            if isinstance(self.resposta, BaseException):
                raise self.resposta
            return self.resposta if isinstance(self.resposta, bytes) else json.dumps(self.resposta).encode("utf-8")

        ce._http_get = _falso
        return self

    def __exit__(self, *_exc):
        ce._http_get = self._original

    def responder(self, resposta: object) -> None:
        self.resposta = resposta


def _erro(funcao, *args) -> str:
    try:
        funcao(*args)
    except ce.ErroConsultaExterna as exc:
        return str(exc)
    raise AssertionError(f"{funcao.__name__}{args} devia levantar ErroConsultaExterna")


def _http_erro(codigo: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://exemplo.invalido", codigo, "x", {}, None)


def testar_core() -> None:
    linha("1) Core: CEP e CNPJ com resposta simulada")
    with RedeSimulada() as rede:
        rede.responder(VIACEP_OK)
        achado = ce.consultar_cep(CEP_FICTICIO)
        assert achado == {"logradouro": "Rua Exemplo", "complemento": "lado par", "bairro": "Bairro Exemplo",
                          "cidade": "Cidade Exemplo", "uf": "CE"}, achado
        assert rede.urls == ["https://viacep.com.br/ws/12345678/json/"], rede.urls
        rede.responder({"localidade": "Cidade Exemplo", "uf": "CE", "logradouro": "", "bairro": None})
        assert ce.consultar_cep("12345678")["logradouro"] == "" and ce.consultar_cep("12345678")["bairro"] == ""
        print("OK: CEP devolve os campos do app (uf em maiúsculas, o que não vem fica vazio), só dígitos na URL.")

        rede.urls.clear()
        rede.responder(BRASILAPI_OK)
        achado = ce.consultar_cnpj(CNPJ_FICTICIO)
        assert achado == {"razao_social": "EMPRESA EXEMPLO LTDA", "logradouro": "AVENIDA DAS FLORES", "numero": "100",
                          "complemento": "SALA 2", "bairro": "CENTRO EXEMPLO", "cidade": "CIDADE EXEMPLO", "uf": "CE",
                          "cep": "12345678"}, achado
        assert rede.urls == ["https://brasilapi.com.br/api/cnpj/v1/11222333000181"], rede.urls
        rede.responder({**BRASILAPI_OK, "logradouro": "AVENIDA DAS FLORES"})
        assert ce.consultar_cnpj("11222333000181")["logradouro"] == "AVENIDA DAS FLORES", "o tipo não se repete"
        rede.responder({**BRASILAPI_OK, "cep": "12345-678"})
        assert ce.consultar_cnpj("11222333000181")["cep"] == "12345678", "o CEP do CNPJ vem só com dígitos"
        rede.responder({**BRASILAPI_OK, "descricao_tipo_de_logradouro": "", "numero": 7, "complemento": None})
        achado = ce.consultar_cnpj("11222333000181")
        assert achado["logradouro"] == "DAS FLORES" and achado["numero"] == "7" and achado["complemento"] == ""
        print("OK: CNPJ devolve razão social e endereço (tipo + nome do logradouro, CEP só com dígitos).")

    linha("1b) Core: o que preencher direto e o que perguntar")
    sep = ce.separar_preenchimentos
    assert sep({"cep": "12345-678", "cidade": "Cidade  Exemplo", "bairro": "Antigo"},
               {"cep": "12345678", "cidade": "cidade exemplo", "bairro": "Novo"}) == ({}, {"bairro": "Novo"})
    assert sep({"cep": "12345-678"}, {"cep": "87654321"}) == ({}, {"cep": "87654321"})
    assert sep({"logradouro": "", "bairro": "  "}, {"logradouro": "Rua A", "bairro": "B"}) == (
        {"logradouro": "Rua A", "bairro": "B"}, {})
    assert sep({"logradouro": "Rua X", "numero": ""}, {"logradouro": "", "numero": "  "}) == ({}, {}),         "o que a consulta não trouxe nunca apaga nem pergunta"
    print("OK: vazio entra direto; igual (máscara/caixa/espaços) é ignorado; diferente pergunta; consulta vazia não mexe.")

    linha("2) Core: CEP inexistente, sem rede, tempo esgotado, resposta estranha")
    with RedeSimulada() as rede:
        rede.responder({"erro": True})
        assert "não encontrado" in _erro(ce.consultar_cep, CEP_FICTICIO)
        rede.responder({"erro": "true"})
        assert "não encontrado" in _erro(ce.consultar_cep, CEP_FICTICIO)
        rede.responder(_http_erro(404))
        assert "não encontrado" in _erro(ce.consultar_cep, CEP_FICTICIO)
        assert "não encontrado" in _erro(ce.consultar_cnpj, CNPJ_FICTICIO)
        rede.responder(_http_erro(429))
        assert "Muitas consultas" in _erro(ce.consultar_cnpj, CNPJ_FICTICIO)
        rede.responder(_http_erro(503))
        assert "503" in _erro(ce.consultar_cep, CEP_FICTICIO)
        rede.responder(urllib.error.URLError(socket.gaierror("sem dns")))
        assert "sem conexão com a internet" in _erro(ce.consultar_cep, CEP_FICTICIO)
        assert "sem conexão com a internet" in _erro(ce.consultar_cnpj, CNPJ_FICTICIO)
        rede.responder(ConnectionResetError("caiu"))
        assert "falha de conexão" in _erro(ce.consultar_cep, CEP_FICTICIO)
        for tempo in (TimeoutError("lento"), urllib.error.URLError(TimeoutError("lento"))):
            rede.responder(tempo)
            assert "demorou demais" in _erro(ce.consultar_cep, CEP_FICTICIO)
            assert "demorou demais" in _erro(ce.consultar_cnpj, CNPJ_FICTICIO)
        print("OK: não encontrado (CEP, 404), muitas consultas, erro do serviço, sem internet, queda e tempo esgotado "
              "viram mensagem clara.")

        estranhas = [b"<html>fora do ar</html>", b"\xff\xfe", b"[]", b'"texto"', b"null", b"{}",
                     json.dumps({"localidade": ["lista"]}).encode()]
        for corpo in estranhas:
            rede.responder(corpo)
            assert "não deu para entender" in _erro(ce.consultar_cep, CEP_FICTICIO) or \
                "formato inesperado" in _erro(ce.consultar_cep, CEP_FICTICIO), corpo
        for corpo in (b"<html>", b"[]", b"{}", json.dumps({"razao_social": ""}).encode()):
            rede.responder(corpo)
            assert "não deu para entender" in _erro(ce.consultar_cnpj, CNPJ_FICTICIO), corpo
        rede.responder({**BRASILAPI_OK, "numero": {"x": 1}})
        assert "formato inesperado" in _erro(ce.consultar_cnpj, CNPJ_FICTICIO)
        print("OK: HTML, bytes quebrados, JSON de outro formato e campo com tipo errado viram erro, nunca dado torto.")

    linha("3) Core: o que não é CEP/CNPJ válido nunca chega ao HTTP (CPF nunca é enviado)")
    with RedeSimulada() as rede:
        rede.responder(BRASILAPI_OK)
        for entrada in (fx.CPF_MARIA, "52998224725", "", "1234567", "123456789", "123456789012345"):
            _erro(ce.consultar_cnpj, entrada)
        assert "CPF" in _erro(ce.consultar_cnpj, fx.CPF_MARIA)
        assert "inválido" in _erro(ce.consultar_cnpj, "11.222.333/0001-82"), "dígito verificador errado"
        assert "inválido" in _erro(ce.consultar_cnpj, "00000000000000")
        for entrada in (fx.CPF_MARIA, "52998224725", "", "1234567", "123456789"):
            _erro(ce.consultar_cep, entrada)
        assert rede.urls == [], f"saiu consulta que não devia: {rede.urls}"
        print("OK: CPF (11 dígitos), CNPJ com dígito errado, CEP/CNPJ incompletos: nenhuma chamada saiu.")

    linha("4) Core: o ponto único de HTTP (urlopen simulado: a internet nunca é usada)")
    pedidos = []

    class _Resposta:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def read(self):
            return b'{"ok": 1}'

    def _urlopen_falso(pedido, timeout=None):
        pedidos.append((pedido.full_url, timeout))
        return _Resposta()

    original = urllib.request.urlopen
    urllib.request.urlopen = _urlopen_falso
    try:
        assert ce._http_get("https://exemplo.invalido/x", 5) == b'{"ok": 1}'
    finally:
        urllib.request.urlopen = original
    assert pedidos == [("https://exemplo.invalido/x", 5)], pedidos
    print("OK: _http_get faz um GET com o tempo limite pedido.")


def _teclar_cep(tela: FichaClienteScreen, texto: str) -> None:
    tela._campo_cep.clear()
    QTest.keyClicks(tela._campo_cep, texto)


def testar_ficha(msgs: Mensagens, caminho: Path) -> None:
    linha("5) Ficha: botões só em edição, habilitados só com CEP de 8 / CNPJ de 14 dígitos")
    tela = FichaClienteScreen()
    tela.resize(1250, 800)
    tela.show()
    _processar()
    tela._selecionar_por_cpf(fx.CPF_MARIA)
    _processar()
    antes = bd.ler_clientes(caminho).copy()
    assert tela._botao_buscar_cep.isHidden() and tela._botao_buscar_cnpj.isHidden(), "em leitura não há 'Buscar'"
    tela._alternar_edicao_cliente()
    _processar()
    assert not tela._botao_buscar_cep.isHidden() and not tela._botao_buscar_cnpj.isHidden()
    assert not tela._botao_buscar_cnpj.isEnabled(), "CPF de 11 dígitos: sem busca (CPF nunca é consultado)"
    assert "CPF nunca é consultado" in tela._botao_buscar_cnpj.toolTip()
    _teclar_cep(tela, "1234567")
    assert not tela._botao_buscar_cep.isEnabled()
    _teclar_cep(tela, "12345678")
    assert tela._botao_buscar_cep.isEnabled() and tela._campo_cep.text() == CEP_FICTICIO
    tela._campo_cpf.setText("11222333000181")
    assert tela._botao_buscar_cnpj.isEnabled() and tela._campo_cpf.text() == CNPJ_FICTICIO
    tela._campo_cpf.setText("1122233300018")
    assert not tela._botao_buscar_cnpj.isEnabled(), "CNPJ incompleto: sem busca"
    print("OK: 'Buscar' só aparece editando; CEP exige 8 dígitos e o outro botão só liga com 14 (CNPJ).")

    linha("6) Ficha: só ao clicar (digitar não consulta), campo vazio é preenchido direto, nada é gravado")
    with RedeSimulada() as rede:
        rede.responder(VIACEP_OK)
        msgs.limpar()
        for campo in (tela._campo_logradouro, tela._campo_numero, tela._campo_complemento, tela._campo_bairro,
                      tela._campo_cidade):
            campo.clear()
        tela._definir_texto_uf("")
        tela._campo_cpf.setText(fx.CPF_MARIA)
        _teclar_cep(tela, "12345678")
        _processar()
        assert rede.urls == [], "digitar o CEP não pode consultar"
        QTest.mouseClick(tela._botao_buscar_cep, Qt.MouseButton.LeftButton)
        _processar()
        assert rede.urls == ["https://viacep.com.br/ws/12345678/json/"], rede.urls
        assert (tela._campo_logradouro.text(), tela._campo_complemento.text(), tela._campo_bairro.text(),
                tela._campo_cidade.text(), tela._campo_uf.currentText()) == (
            "Rua Exemplo", "lado par", "Bairro Exemplo", "Cidade Exemplo", "CE")
        assert tela._campo_numero.text() == "", "o CEP não traz número: fica como estava"
        assert tela._campo_cep.text() == CEP_FICTICIO
        msgs.exigir_vazio("campos vazios: preenchimento direto, sem pergunta nem aviso")
        assert bd.ler_clientes(caminho).equals(antes), "a consulta não grava nada sozinha"
        print("OK: nenhuma consulta ao digitar; ao clicar, os campos vazios foram preenchidos; planilha intacta.")

        linha("7) Ficha: texto já digitado -> pergunta com antes e depois; 'Não' mantém, 'Sim' troca")
        tela._campo_logradouro.setText("Rua Que Eu Digitei")
        tela._campo_bairro.setText("Bairro Exemplo")  # igual ao que vem (só a caixa muda): não pergunta
        tela._campo_cidade.setText("cidade exemplo")
        tela._campo_complemento.clear()
        tela._definir_texto_uf("PE")
        msgs.limpar()
        msgs.resposta_pergunta = QMessageBox.StandardButton.No
        tela._buscar_cep()
        tipo, _titulo, texto = msgs.ultima()
        assert tipo == "question" and len(msgs.registro) == 1, msgs.registro
        assert '"Rua Que Eu Digitei"  →  "Rua Exemplo"' in texto and '"PE"  →  "CE"' in texto, texto
        assert "Bairro" not in texto and "Cidade" not in texto, "o que já é igual não entra na pergunta"
        assert tela._campo_logradouro.text() == "Rua Que Eu Digitei" and tela._campo_uf.currentText() == "PE"
        assert tela._campo_complemento.text() == "lado par", "o vazio é preenchido mesmo dizendo 'Não'"
        msgs.limpar()
        msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
        tela._buscar_cep()
        assert tela._campo_logradouro.text() == "Rua Exemplo" and tela._campo_uf.currentText() == "CE"
        assert tela._campo_cidade.text() == "cidade exemplo", "igual ao que veio: não é mexido"
        assert bd.ler_clientes(caminho).equals(antes), "nem a troca grava: só o OK/salvar grava"
        print("OK: a pergunta mostra o antes e o depois; 'Não' mantém o digitado; 'Sim' troca; nada gravado.")

        linha("8) Ficha: falhas viram aviso e o formulário segue usável")
        tela._campo_logradouro.setText("Rua Que Eu Digitei")
        for erro, trecho in ((urllib.error.URLError(socket.gaierror("x")), "sem conexão"), (TimeoutError("x"), "demorou demais"),
                             (b"<html>", "não deu para entender"), ({"erro": True}, "não encontrado")):
            rede.responder(erro)
            msgs.limpar()
            tela._buscar_cep()
            tipo, _t, texto = msgs.ultima()
            assert tipo == "warning" and trecho in texto, (tipo, texto)
            assert tela._campo_logradouro.text() == "Rua Que Eu Digitei"
            assert not tela._campo_logradouro.isReadOnly() and tela._botao_ok_cliente.isEnabled(), "segue editável"
        tela._campo_numero.setText("55")
        assert tela._campo_numero.text() == "55"
        print("OK: sem internet / lento / resposta estranha / CEP inexistente: aviso, campos como estavam, tela usável.")

        linha("9) Ficha: CNPJ preenche nome e endereço; nome já digitado pergunta")
        tela._cancelar_edicao_cliente()
        msgs.limpar()
        tela._iniciar_novo_cliente()
        _processar()
        rede.responder(BRASILAPI_OK)
        rede.urls.clear()
        QTest.keyClicks(tela._campo_cpf, "11222333000181")
        assert tela._campo_nome.text() == "" and rede.urls == []
        QTest.mouseClick(tela._botao_buscar_cnpj, Qt.MouseButton.LeftButton)
        _processar()
        assert rede.urls == ["https://brasilapi.com.br/api/cnpj/v1/11222333000181"], rede.urls
        assert tela._campo_nome.text() == "EMPRESA EXEMPLO LTDA"
        assert (tela._campo_cep.text(), tela._campo_logradouro.text(), tela._campo_numero.text(),
                tela._campo_complemento.text(), tela._campo_bairro.text(), tela._campo_cidade.text(),
                tela._campo_uf.currentText()) == (CEP_FICTICIO, "AVENIDA DAS FLORES", "100", "SALA 2", "CENTRO EXEMPLO",
                                                  "CIDADE EXEMPLO", "CE")
        msgs.exigir_vazio("tudo vazio: sem pergunta")
        assert tela._modo_novo_cliente and bd.ler_clientes(caminho).equals(antes), "o cadastro só grava no OK"

        tela._campo_nome.setText("Nome Que Eu Digitei")
        msgs.resposta_pergunta = QMessageBox.StandardButton.No
        tela._buscar_cnpj()
        _tipo, _t, texto = msgs.ultima()
        assert '"Nome Que Eu Digitei"  →  "EMPRESA EXEMPLO LTDA"' in texto, texto
        assert tela._campo_nome.text() == "Nome Que Eu Digitei"
        msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
        tela._buscar_cnpj()
        assert tela._campo_nome.text() == "EMPRESA EXEMPLO LTDA"
        print("OK: razão social só entra no Nome se vazio (ou se o usuário confirmar); nada gravado antes do OK.")

        linha("10) Ficha: CPF digitado nunca vira consulta (nem forçando o clique)")
        rede.urls.clear()
        msgs.limpar()
        tela._campo_cpf.setText(fx.CPF_ANA)
        assert not tela._botao_buscar_cnpj.isEnabled()
        tela._buscar_cnpj()
        assert msgs.ultima()[0] == "warning" and "CPF" in msgs.ultima()[2] and rede.urls == [], (msgs.registro, rede.urls)
        print("OK: com CPF o botão fica desligado e, mesmo forçado, nenhuma chamada sai.")

    linha("11) Ficha: Cancelar sai do rascunho sem gravar")
    tela._cancelar_edicao_cliente()
    _processar()
    assert bd.ler_clientes(caminho).equals(antes)
    tela.close()
    tela.deleteLater()


def main() -> None:
    def _sem_rede(*_a, **_k):
        raise AssertionError("o teste tentou acessar o Google de verdade")

    def _sem_internet(*_a, **_k):
        raise AssertionError("o teste tentou usar a internet de verdade")

    guardados = (nuvem._obter_cliente, sheets_sync._obter_cliente, urllib.request.urlopen, socket.socket.connect)
    nuvem._obter_cliente = sheets_sync._obter_cliente = _sem_rede
    urllib.request.urlopen = _sem_internet
    socket.socket.connect = _sem_internet
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_consulta_"))
    registro_antes = fx.instantaneo_do_registro()
    fx.isolar_preferencias(pasta)
    caminho = fx.criar(pasta)
    fx.apontar_modulos_para(caminho)
    sessao_mod.iniciar(ADMIN)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(build_stylesheet(TEMA_ESCURO))
    fontes = (clientes_mod._ler_da_fonte_ativa, propostas_mod._ler_da_fonte_ativa)
    try:
        testar_core()
        with Mensagens() as msgs:
            testar_ficha(msgs, caminho)
        print("\nTUDO OK")
    finally:
        clientes_mod._ler_da_fonte_ativa, propostas_mod._ler_da_fonte_ativa = fontes
        nuvem._obter_cliente, sheets_sync._obter_cliente, urllib.request.urlopen, socket.socket.connect = guardados
        fx.restaurar_modulos()
        sessao_mod.encerrar()
        assert fx.instantaneo_do_registro() == registro_antes, "o teste mexeu nas preferências reais"


if __name__ == "__main__":
    main()
