"""Testa juntar as propostas antigas em vendas (core/migracao_vendas.py): o plano (grupos automaticos e as duvidas
que o usuario responde), o status de cada venda tirado das propostas, backup antes, gravacao unica e as recusas.

Planilha 100% ficticia em pasta temporaria; o Google fica desligado e qualquer acesso a ele derruba o teste.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_migracao_vendas.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False
import fixture_ficticia as fx
from core import backup as backup_mod
from core import data_store as bd
from core import data_store_sheets as nuvem
from core import migracao_vendas as mig
from core import sessao as sessao_mod
from core import sheets_sync
from core import vendas as v
from PySide6.QtWidgets import QApplication
from ambiente_de_teste import Mensagens
from desktop.dialogs.organizar_vendas_dialog import OrganizarVendasDialog

HOJE = date(2026, 9, 1)


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _p(cpf: str, dias: int, equip: str, banco: str, status: str) -> dict:
    return {"DATA": pd.Timestamp(HOJE + timedelta(days=dias)), "CPF": cpf, "VALOR (R$)": 1000, "MESES": 12,
            "EQUIPAMENTO": equip, "BANCO": banco, "STATUS": status, "OBSERVAÇÕES": "", "ID_PROPOSTA": "", "ID_VENDA": ""}


def main() -> None:
    def _sem_rede(*_a, **_k):
        raise AssertionError("o teste tentou acessar o Google de verdade")

    rede_original = (nuvem._obter_cliente, sheets_sync._obter_cliente)
    nuvem._obter_cliente = sheets_sync._obter_cliente = _sem_rede
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_migracao_vendas_"))
    caminho = fx.criar(pasta)
    fx.apontar_modulos_para(caminho)
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    M, J, A = fx.CPF_MARIA, fx.CPF_JOAO, fx.CPF_ANA
    linhas = [
        # Maria: cadeira em 3 bancos no mesmo dia e 1 dia depois (uma venda); laser 2 dias depois (dúvida: vários equipamentos)
        _p(M, 0, "Cadeira X", "Banco A", "Aprovado"), _p(M, 0, "cadeira x ", "Banco B", "Negado"), _p(M, 1, "Cadeira X", "Banco C", "Em Análise"),
        _p(M, 2, "Laser Y", "Banco A", "Em Análise"),
        # João: mesa em duas levas separadas por 20 dias (dúvida: espaçada); todas negadas
        _p(J, 0, "Mesa Z", "Banco A", "Negado"), _p(J, 20, "Mesa Z", "Banco B", "NEGADO"),
        # Ana: autoclave efetivada num banco, outro banco encerrado (status antigo)
        _p(A, 5, "Autoclave W", "Banco A", "Efetivado"), _p(A, 5, "Autoclave W", "Banco B", "Encerrada"),
        # Ana: laser 30 dias depois (longe demais pra ser dúvida de vários equipamentos)
        _p(A, 35, "Laser Y", "Banco A", "Pré-aprovado"),
    ]
    bd.escrever_propostas(caminho, pd.DataFrame(linhas))
    try:
        linha("1) O plano: grupos automáticos e só as dúvidas que o app não decide sozinho")
        antes = caminho.read_bytes()
        plano = mig.planejar()
        assert caminho.read_bytes() == antes, "planejar nunca grava"
        assert plano.resumo == {"propostas": 9, "grupos": 6, "duvidas": 2}, plano.resumo
        por_cpf = {}
        for g in plano.grupos:
            por_cpf.setdefault(g.cpf, []).append((g.equipamento.upper(), len(g.indices)))
        assert sorted(por_cpf["52998224725"]) == [("CADEIRA X", 3), ("LASER Y", 1)], "cadeira com espaço/maiúscula diferente é o mesmo grupo"
        assert sorted(por_cpf["11144477735"]) == [("MESA Z", 1), ("MESA Z", 1)], "20 dias de distância: grupos separados"
        tipos = {d.tipo: d for d in plano.duvidas}
        assert set(tipos) == {mig.DUVIDA_VARIOS_EQUIPAMENTOS, mig.DUVIDA_ESPACADA}
        assert tipos[mig.DUVIDA_VARIOS_EQUIPAMENTOS].cpf == "52998224725" and "Laser Y" in tipos[mig.DUVIDA_VARIOS_EQUIPAMENTOS].pergunta
        assert tipos[mig.DUVIDA_ESPACADA].cpf == "11144477735" and tipos[mig.DUVIDA_ESPACADA].cliente
        print("OK: 9 propostas -> 6 grupos; dúvidas só para Maria (cadeira + laser em 2 dias) e João (mesa com 20 dias entre as levas).")

        linha("2) Aplicar exige todas as dúvidas respondidas")
        try:
            mig.aplicar(plano, {tipos[mig.DUVIDA_ESPACADA].chave: True})
            raise AssertionError("deveria recusar com dúvida sem resposta")
        except v.ErroVenda as exc:
            assert "1 sem resposta" in str(exc)
        assert caminho.read_bytes() == antes and not backup_mod.listar_backups()
        print("OK: com dúvida sem resposta, recusa e não grava nem faz backup.")

        linha("3) Pela janela: só aplica com tudo respondido; Maria junta, João fica separado")
        decisoes = {tipos[mig.DUVIDA_VARIOS_EQUIPAMENTOS].chave: True, tipos[mig.DUVIDA_ESPACADA].chave: False}
        app = QApplication.instance() or QApplication(sys.argv)
        with Mensagens() as msgs:
            janela = OrganizarVendasDialog(plano)
            assert not janela.botao_aplicar.isEnabled() and "Falta responder 2" in janela.falta.text(), "nada marcado de início"
            janela.respostas[tipos[mig.DUVIDA_VARIOS_EQUIPAMENTOS].chave].button(1).click()
            assert not janela.botao_aplicar.isEnabled()
            janela.respostas[tipos[mig.DUVIDA_ESPACADA].chave].button(0).click()
            assert janela.botao_aplicar.isEnabled() and janela.decisoes() == decisoes
            janela.botao_aplicar.click()
            assert msgs.ultima()[1] == "Propostas juntadas em vendas" and "viraram 5 vendas" in msgs.ultima()[2]
        resumo = janela.resultado
        print("OK: a janela começa sem nada marcado, só libera 'Juntar em vendas' com tudo respondido e mostra o resumo.")
        assert resumo["vendas"] == 5 and resumo["propostas"] == 9
        assert [b.motivo for b in backup_mod.listar_backups()] == [backup_mod.MOTIVO_PRE_VENDAS], "backup antes de gravar"
        propostas = bd.ler_propostas(caminho)
        vendas = bd.ler_vendas(caminho).set_index("ID_VENDA")
        assert (propostas["ID_VENDA"] != "").all() and propostas["ID_PROPOSTA"].is_unique and (propostas["ID_PROPOSTA"] != "").all()
        assert list(propostas["STATUS"]) == [l["STATUS"] for l in linhas], "o status das propostas não muda"

        def venda_de(i):
            return vendas.loc[propostas.at[i, "ID_VENDA"]]

        maria = venda_de(0)
        assert propostas.loc[0:3, "ID_VENDA"].nunique() == 1, "cadeira (3 bancos) + laser: uma venda só"
        assert maria["EQUIPAMENTOS"] == "Cadeira X + Laser Y" and maria["STATUS"] == v.VENDA_AGUARDANDO
        assert maria["DATA_CRIACAO"] == pd.Timestamp(HOJE)
        print("OK: Maria virou uma venda com 'Cadeira X + Laser Y', 4 propostas, aguardando bancos, criada na data da 1ª proposta.")

        joao1, joao2 = venda_de(4), venda_de(5)
        assert propostas.at[4, "ID_VENDA"] != propostas.at[5, "ID_VENDA"], "João: separado, como respondido"
        assert joao1["STATUS"] == joao2["STATUS"] == v.VENDA_PERDIDA and joao1["MOTIVO"] == "Todos os bancos negaram"
        ana = venda_de(6)
        assert ana["STATUS"] == v.VENDA_EFETIVADA and ana["BANCO_ESCOLHIDO"] == propostas.at[6, "ID_PROPOSTA"]
        assert propostas.at[7, "ID_VENDA"] == propostas.at[6, "ID_VENDA"], "a encerrada fica na mesma venda"
        assert venda_de(8)["STATUS"] == v.VENDA_AGUARDANDO and propostas.at[8, "ID_VENDA"] != propostas.at[6, "ID_VENDA"]
        print("OK: João em 2 vendas Perdidas ('Todos os bancos negaram'); Ana Efetivada com o banco certo; o laser 30 dias depois é outra venda.")

        hist = bd.ler_historico(caminho)
        assert len(hist) == 5 and set(hist["TIPO"]) == {v.TIPO_VENDA} and set(hist["ID"]) == set(vendas.index)
        assert resumo["por_status"] == {v.VENDA_AGUARDANDO: 2, v.VENDA_PERDIDA: 2, v.VENDA_EFETIVADA: 1}
        print("OK: uma linha de histórico por venda nova; o resumo bate.")

        linha("4) Depois de aplicar, nada sobra; plano velho é recusado")
        assert mig.planejar().resumo == {"propostas": 0, "grupos": 0, "duvidas": 0}
        try:
            mig.aplicar(plano, decisoes)
            raise AssertionError("plano velho deveria ser recusado")
        except v.ErroVenda as exc:
            assert "mudaram" in str(exc)
        assert len(bd.ler_vendas(caminho)) == 5, "não duplica nada"
        v.criar_venda(M, ["Mesa Z"], {"BANCO": "Banco A", "VALOR (R$)": 1, "MESES": 1})
        assert mig.planejar().resumo["propostas"] == 0, "proposta criada já como venda não entra no plano"
        print("OK: rodar de novo não acha nada; plano feito antes é recusado; propostas novas já nascem em vendas.")

        linha("5) Só junta com este computador em dia com a nuvem")
        from core import sincronizacao as sinc
        from desktop.dialogs import organizar_vendas_dialog as dialogo_mod
        original_verificar = sinc.verificar_ao_abrir
        config.SINCRONIZACAO_GOOGLE_ATIVADA = True  # so a CONFERENCIA roda (simulada): nada e enviado nem lido de verdade
        try:
            with Mensagens() as msgs:
                for tipo, trecho in ((sinc.SITUACAO_NUVEM_MAIS_NOVA, "Baixe da nuvem"), (sinc.SITUACAO_SEM_REDE, "internet"),
                                     (sinc.SITUACAO_LOCAL_PENDENTE, "Espere"), (sinc.SITUACAO_CONFLITO, "Resolva")):
                    sinc.verificar_ao_abrir = lambda tipo=tipo: sinc.SituacaoAoAbrir(tipo)
                    assert dialogo_mod.em_dia_com_a_nuvem(None) is False and trecho in msgs.ultima()[2], (tipo, msgs.ultima())
                sinc.verificar_ao_abrir = lambda: sinc.SituacaoAoAbrir(sinc.SITUACAO_EM_DIA)
                msgs.limpar()
                assert dialogo_mod.em_dia_com_a_nuvem(None) is True and not msgs.registro
        finally:
            sinc.verificar_ao_abrir = original_verificar
            config.SINCRONIZACAO_GOOGLE_ATIVADA = False
        print("OK: nuvem mais nova, sem internet, envio pendente ou conflito: explica o que fazer e não deixa juntar; em dia: deixa.")

        linha("6) Só o Administrador aplica")
        sessao_mod.encerrar()
        try:
            mig.aplicar(mig.planejar(), {})
            raise AssertionError("sem sessão não pode gravar")
        except sessao_mod.PermissaoNegada:
            pass
        print("OK: sem sessão de Administrador, aplicar é recusado.")
        linha("TUDO OK")
    finally:
        nuvem._obter_cliente, sheets_sync._obter_cliente = rede_original
        fx.restaurar_modulos()
        sessao_mod.encerrar()


if __name__ == "__main__":
    main()
