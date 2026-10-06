"""Testa o FormularioProposta (o formulario de lancamento de proposta do card
expandido), sem precisar abrir uma janela de verdade (QT_QPA_PLATFORM=offscreen)
e sem ler nem mexer no arquivo real - tudo numa planilha 100% FICTICIA em pasta temporaria
(scripts/fixture_ficticia.py), com as preferencias do app isoladas e o acesso ao Google bloqueado.

Chama dialogo._salvar() diretamente (em vez de clicar no botao OK de verdade),
simulando o clique sem precisar de QTest/interacao real.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_formulario_proposta.py
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QMessageBox

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
from core import clientes as clientes_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from desktop.widgets.formulario_proposta import FormularioProposta

# as copias que o teste grava ficam numa pasta temporaria, nunca ao lado da planilha (testes em paralelo
# esbarrariam nelas, e a conferencia da pasta de dados acusaria arquivo a mais)
PASTA_TEMPORARIA = Path(tempfile.mkdtemp(prefix="smoke_test_"))
atexit.register(shutil.rmtree, PASTA_TEMPORARIA, True)


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _espiar_gravacao(formulario: FormularioProposta) -> list[str]:
    """Lista que recebe "gravada" quando o formulario avisa que gravou (a funcao ligada ao
    sinal captura so a lista, nunca o formulario: seria um ciclo de referencias)."""
    avisos: list[str] = []
    formulario.gravada.connect(lambda: avisos.append("gravada"))
    return avisos


def main() -> None:
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    app = QApplication.instance() or QApplication(sys.argv)

    # QMessageBox.warning/critical sao chamadas modais (.exec() proprio) -
    # em modo headless elas travam esperando um clique que nunca vem. Troca
    # por um stub que so registra a chamada, sem abrir nada.
    mensagens_capturadas: list[str] = []

    def _stub_mensagem(*args, **kwargs):
        texto = args[2] if len(args) > 2 else kwargs.get("text", "")
        mensagens_capturadas.append(str(texto))
        return QMessageBox.StandardButton.Ok

    QMessageBox.warning = staticmethod(_stub_mensagem)
    QMessageBox.critical = staticmethod(_stub_mensagem)
    QMessageBox.information = staticmethod(_stub_mensagem)

    fx.isolar_preferencias(PASTA_TEMPORARIA)
    tmp_path = fx.criar(PASTA_TEMPORARIA)
    fx.apontar_modulos_para(tmp_path)
    fx.bloquear_google()

    try:
        novo_cpf = fx.cpf_ficticio(500_000_011)  # CPF valido (digito verificador correto), fora da fixture
        clientes_mod.adicionar_cliente({"CPF/CNPJ": novo_cpf, "CLIENTE": "Cliente Formulario Teste", "TIPO": "Cliente"})

        linha("1) FormularioProposta (card expandido) - sem equipamento (deve rejeitar)")
        dialogo = FormularioProposta(novo_cpf, "Cliente Formulario Teste")
        gravou = _espiar_gravacao(dialogo)
        dialogo._valor.setValue(50000)
        dialogo._banco.addItem("Banco Teste")  # como se ja estivesse no cadastro (a lista e fechada)
        dialogo._banco.setCurrentText("Banco Teste")
        dialogo._salvar()
        assert gravou == [], "sem equipamento nao pode avisar que gravou"
        assert "quipamento" in mensagens_capturadas[-1]
        print(f"OK: proposta sem equipamento nao foi aceita -> \"{mensagens_capturadas[-1]}\"")

        linha("2) FormularioProposta (card expandido) - lancamento valido")
        historico_antes = propostas_mod.historico_por_cpf(novo_cpf)
        dialogo = FormularioProposta(novo_cpf, "Cliente Formulario Teste")
        gravou = _espiar_gravacao(dialogo)
        dialogo._valor.setValue(75000)
        dialogo._meses.setValue(36)
        dialogo._equipamento.addItem("Equipamento Dialogo Teste")  # como se ja estivesse no cadastro (a lista e fechada)
        dialogo._equipamento.setCurrentText("Equipamento Dialogo Teste")
        dialogo._banco.addItem("Banco Dialogo Teste")  # como se ja estivesse no cadastro (a lista e fechada)
        dialogo._banco.setCurrentText("Banco Dialogo Teste")
        dialogo._salvar()
        assert gravou == ["gravada"]

        historico_depois = propostas_mod.historico_por_cpf(novo_cpf)
        assert len(historico_depois) == len(historico_antes) + 1
        nova = historico_depois.iloc[0]
        assert nova["BANCO"] == "Banco Dialogo Teste"
        assert nova["EQUIPAMENTO"] == "Equipamento Dialogo Teste"
        assert nova["VALOR (R$)"] == 75000
        assert nova["MESES"] == 36
        print(f"OK: proposta lancada via dialogo -> {nova['BANCO']} / {nova['EQUIPAMENTO']} / R$ {nova['VALOR (R$)']}")

        linha("TUDO OK")
    finally:
        tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
