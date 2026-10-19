"""Testa corrigir o CPF/CNPJ de um cliente (core/clientes.py e a Ficha): as propostas e vendas dele vao junto para o CPF
novo, com backup "pre-cpf" antes e numa gravacao so (tudo ou nada), sincronizando as abas que mudaram; o CPF repetido
e recusado sem gravar nada; so mudar a pontuacao nao e troca; cliente sem nada ligado muda so o cadastro; outros
clientes nao sao tocados; na Ficha, "Cancelar" nao grava e "Levar junto e salvar" grava.

Planilha 100% ficticia em pasta temporaria, preferencias isoladas e o Google desligado (qualquer acesso derruba).

Rodar com: venv/Scripts/python.exe scripts/smoke_test_cpf_leva_junto.py
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from PySide6.QtWidgets import QApplication

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False
import fixture_ficticia as fx
from ambiente_de_teste import Mensagens
from core import backup as backup_mod
from core import bancos as bancos_mod
from core import clientes as clientes_mod
from core import data_store as bd
from core import data_store_sheets as nuvem
from core import sessao as sessao_mod
from core import sheets_sync
from core import vendas as v
from core.validators import apenas_digitos
from desktop.dialogs import escolha_dialog
from desktop.screens.ficha_cliente_screen import FichaClienteScreen
from desktop.screens.usuarios_screen import _ROTULO_POR_MOTIVO
from desktop.theme import TEMA_ESCURO, build_stylesheet

ADMIN = sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador")


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def mascarar(cpf: str) -> str:
    d = apenas_digitos(cpf)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def hash_do(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def da_pessoa(cpf: str, caminho: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(propostas, vendas) que estao hoje neste CPF/CNPJ (so os digitos contam)."""
    alvo = apenas_digitos(cpf)
    propostas, vendas = bd.ler_propostas(caminho), bd.ler_vendas(caminho)
    return (propostas[propostas["CPF"].map(apenas_digitos) == alvo].reset_index(drop=True),
            vendas[vendas["CPF"].map(apenas_digitos) == alvo].reset_index(drop=True))


def com_venda(cpf: str, banco: str, outro_banco: bool = False) -> str:
    id_venda, _ = v.criar_venda(cpf, ["Equipamento Modelo X"], {"BANCO": banco, "VALOR (R$)": 1000, "MESES": 12})
    if outro_banco:
        v.mandar_a_outro_banco(id_venda, {"BANCO": banco, "VALOR (R$)": 500, "MESES": 12})
    return id_venda


def cadastrar(cpf: str, nome: str) -> None:
    clientes_mod.adicionar_cliente({"CPF/CNPJ": cpf, "CLIENTE": nome, "TIPO": "Cliente"})


def campos_de(cpf_novo: str, nome: str) -> dict:
    return {"CPF/CNPJ": cpf_novo, "CLIENTE": nome, "TIPO": "Cliente"}


def main() -> None:
    def _sem_rede(*_a, **_k):
        raise AssertionError("o teste tentou acessar o Google de verdade")

    rede_original = (nuvem._obter_cliente, sheets_sync._obter_cliente, sheets_sync.sincronizar_em_background)
    nuvem._obter_cliente = sheets_sync._obter_cliente = _sem_rede
    enviadas: list[str] = []
    sheets_sync.sincronizar_em_background = lambda aba, _df: enviadas.append(aba)
    salvar_original = bd._salvar_planilha

    pasta = Path(tempfile.mkdtemp(prefix="_smoke_cpf_"))
    registro_antes = fx.instantaneo_do_registro()
    fx.isolar_preferencias(pasta)
    caminho = fx.criar(pasta)
    fx.apontar_modulos_para(caminho)
    sessao_mod.iniciar(ADMIN)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(build_stylesheet(TEMA_ESCURO))
    try:
        with Mensagens() as msgs:
            banco = bancos_mod.nomes_ativos()[0]
            cpf_a, cpf_novo_a = mascarar(fx.cpf_ficticio(300_000_001)), mascarar(fx.cpf_ficticio(300_000_011))
            cpf_b = fx.cpf_ficticio(300_000_002)  # outro cliente, sem pontuacao no cadastro
            cpf_c = mascarar(fx.cpf_ficticio(300_000_003))  # sem propostas nem vendas
            cpf_e, cpf_novo_c = mascarar(fx.cpf_ficticio(300_000_005)), mascarar(fx.cpf_ficticio(300_000_013))
            cadastrar(cpf_a, "CLIENTE A")
            cadastrar(cpf_b, "CLIENTE B")
            cadastrar(cpf_c, "CLIENTE C")
            cadastrar(cpf_e, "CLIENTE E")
            id_venda_a = com_venda(cpf_a, banco, outro_banco=True)  # 2 propostas e 1 venda no A
            com_venda(cpf_b, banco)
            com_venda(cpf_e, banco)
            # uma das propostas do A guardada so com os numeros (dado antigo): o CPF e o mesmo
            propostas = bd.ler_propostas(caminho)[bd.PROPOSTAS_COLUNAS_EDITAVEIS].copy()
            marca_a = propostas["CPF"].map(apenas_digitos) == apenas_digitos(cpf_a)
            propostas.loc[propostas.index[marca_a][0], "CPF"] = apenas_digitos(cpf_a)
            bd.escrever_propostas(caminho, propostas)
            assert clientes_mod.contar_vinculos_do_cpf(cpf_a) == (2, 1)
            assert clientes_mod.contar_vinculos_do_cpf("") == (0, 0)

            linha("1) Trocar o CPF leva 2 propostas e 1 venda; backup 'pre-cpf'; o resto fica como está")
            antes_b, antes_vb = da_pessoa(cpf_b, caminho)
            antes_todas = len(bd.ler_propostas(caminho)), len(bd.ler_vendas(caminho))
            historico_antes = bd.ler_historico(caminho)
            backups_antes = len(backup_mod.listar_backups(caminho))
            enviadas.clear()
            resultado = clientes_mod.atualizar_cliente(cpf_a, campos_de(cpf_novo_a, "Cliente A Corrigido"))
            assert (resultado.propostas, resultado.vendas) == (2, 1), resultado
            assert resultado.backup is not None and resultado.backup.exists() and "pre-cpf" in resultado.backup.name
            novos = [b for b in backup_mod.listar_backups(caminho)]
            assert len(novos) == backups_antes + 1 and novos[0].motivo == backup_mod.MOTIVO_PRE_CPF
            assert da_pessoa(cpf_a, caminho)[0].empty and da_pessoa(cpf_a, caminho)[1].empty, "o CPF antigo ficou sem nada"
            propostas_novas, vendas_novas = da_pessoa(cpf_novo_a, caminho)
            assert len(propostas_novas) == 2 and len(vendas_novas) == 1
            assert set(propostas_novas["CPF"]) == {cpf_novo_a} and set(vendas_novas["CPF"]) == {cpf_novo_a}, \
                "o mesmo texto que foi para o cadastro"
            assert clientes_mod.buscar_por_cpf(cpf_a) is None
            assert clientes_mod.buscar_por_cpf(cpf_novo_a)["CLIENTE"] == "CLIENTE A CORRIGIDO"
            assert set(propostas_novas["CLIENTE"]) == {"CLIENTE A CORRIGIDO"}, "a proposta acompanha o cliente"
            venda = v.vendas_do_cliente(cpf_novo_a)
            assert [x.id for x in venda] == [id_venda_a] and len(venda[0].propostas) == 2 and not v.vendas_do_cliente(cpf_a)
            pd.testing.assert_frame_equal(bd.ler_historico(caminho), historico_antes)  # o historico e ligado por ID
            assert (len(bd.ler_propostas(caminho)), len(bd.ler_vendas(caminho))) == antes_todas
            assert _ROTULO_POR_MOTIVO[backup_mod.MOTIVO_PRE_CPF] == "Antes de corrigir CPF"
            assert sorted(enviadas) == sorted([bd.ABA_CLIENTES, bd.ABA_PROPOSTAS, bd.ABA_VENDAS]), enviadas
            print("OK: 2 propostas e 1 venda no CPF novo (mesmo texto do cadastro), o antigo sem nada, backup 'pre-cpf', "
                  "histórico igual, clientes + propostas + vendas enviados à nuvem.")

            linha("2) Outros clientes não são tocados")
            depois_b, depois_vb = da_pessoa(cpf_b, caminho)
            pd.testing.assert_frame_equal(antes_b, depois_b)
            pd.testing.assert_frame_equal(antes_vb, depois_vb)
            assert clientes_mod.buscar_por_cpf(cpf_b)["CLIENTE"] == "CLIENTE B" and clientes_mod.buscar_por_cpf(cpf_c)
            print("OK: propostas, vendas e cadastro dos outros ficam iguais.")

            linha("3) CPF novo já é de outro cliente: recusa e nada é gravado")
            antes_hash, backups_antes = hash_do(caminho), len(backup_mod.listar_backups(caminho))
            enviadas.clear()
            try:
                clientes_mod.atualizar_cliente(cpf_e, campos_de(mascarar(cpf_b), "CLIENTE E"))
            except clientes_mod.ErroCliente as exc:
                assert "Já existe um cliente" in str(exc), str(exc)
            else:
                raise AssertionError("deveria recusar o CPF de outro cliente")
            assert hash_do(caminho) == antes_hash, "o arquivo ficou idêntico"
            assert len(backup_mod.listar_backups(caminho)) == backups_antes and not enviadas
            assert clientes_mod.buscar_por_cpf(cpf_e) and sum(map(len, da_pessoa(cpf_e, caminho))) == 2
            print("OK: recusado com texto claro; arquivo idêntico, sem backup extra, nada enviado.")

            linha("4) Só a pontuação diferente não é troca")
            backups_antes = len(backup_mod.listar_backups(caminho))
            antes_b, antes_vb = da_pessoa(cpf_b, caminho)
            enviadas.clear()
            resultado = clientes_mod.atualizar_cliente(cpf_b, campos_de(mascarar(cpf_b), "CLIENTE B NOVO NOME"))
            assert (resultado.propostas, resultado.vendas, resultado.backup) == (0, 0, None)
            assert len(backup_mod.listar_backups(caminho)) == backups_antes, "sem backup extra"
            assert enviadas == [bd.ABA_CLIENTES], enviadas
            depois_b, depois_vb = da_pessoa(cpf_b, caminho)
            pd.testing.assert_frame_equal(antes_b[bd.PROPOSTAS_COLUNAS_EDITAVEIS], depois_b[bd.PROPOSTAS_COLUNAS_EDITAVEIS])
            pd.testing.assert_frame_equal(antes_vb, depois_vb)
            assert clientes_mod.buscar_por_cpf(cpf_b)["CLIENTE"] == "CLIENTE B NOVO NOME"
            print("OK: mesmo CPF com outra máscara só muda o cadastro (sem backup, propostas e vendas intactas).")

            linha("5) Cliente sem propostas nem vendas: só o cadastro muda, sem backup")
            backups_antes = len(backup_mod.listar_backups(caminho))
            tamanho = len(bd.ler_propostas(caminho)), len(bd.ler_vendas(caminho))
            resultado = clientes_mod.atualizar_cliente(cpf_c, campos_de(cpf_novo_c, "CLIENTE C"))
            assert (resultado.propostas, resultado.vendas, resultado.backup) == (0, 0, None)
            assert len(backup_mod.listar_backups(caminho)) == backups_antes
            assert clientes_mod.buscar_por_cpf(cpf_c) is None and clientes_mod.buscar_por_cpf(cpf_novo_c)
            assert (len(bd.ler_propostas(caminho)), len(bd.ler_vendas(caminho))) == tamanho
            print("OK: sem nada ligado ao CPF, só o cadastro muda.")

            linha("6) Falha ao gravar: nada pela metade")
            cpf_f, cpf_novo_f = mascarar(fx.cpf_ficticio(300_000_006)), mascarar(fx.cpf_ficticio(300_000_016))
            cadastrar(cpf_f, "CLIENTE F")
            com_venda(cpf_f, banco)

            def _falha(*_a, **_k):
                raise bd.ErroArquivoBloqueado("aberto no Excel (de mentira)")

            bd._salvar_planilha = _falha
            antes_hash = hash_do(caminho)
            try:
                clientes_mod.atualizar_cliente(cpf_f, campos_de(cpf_novo_f, "CLIENTE F"))
            except bd.ErroArquivoBloqueado:
                pass
            else:
                raise AssertionError("deveria avisar que não gravou")
            finally:
                bd._salvar_planilha = salvar_original
            assert hash_do(caminho) == antes_hash and clientes_mod.buscar_por_cpf(cpf_f)
            assert sum(map(len, da_pessoa(cpf_f, caminho))) == 2 and sum(map(len, da_pessoa(cpf_novo_f, caminho))) == 0
            print("OK: se a gravação falha, cadastro, propostas e vendas continuam todos no CPF antigo.")

            linha("7) Na Ficha: a pergunta; Cancelar não grava, Levar junto grava")
            perguntas: list[tuple[str, list[str]]] = []
            resposta = {"indice": 1}

            def _escolher(_pai, titulo, texto, opcoes, **_k):
                perguntas.append((texto, opcoes))
                return resposta["indice"]

            escolher_original = escolha_dialog.escolher
            escolha_dialog.escolher = _escolher
            try:
                tela = FichaClienteScreen()
                tela.resize(1300, 800)
                tela.show()
                avisos: list[int] = []
                tela.dados_atualizados.connect(lambda: avisos.append(1))
                tela._selecionar_por_cpf(cpf_f)
                app.processEvents()
                tela._alternar_edicao_cliente()
                tela._campo_cpf.setText(cpf_novo_f)
                antes_hash, backups_antes = hash_do(caminho), len(backup_mod.listar_backups(caminho))

                tela._salvar_edicao_cliente()  # Cancelar
                assert len(perguntas) == 1 and perguntas[0][1] == ["Levar junto e salvar", "Cancelar"]
                assert "1 proposta e 1 venda" in perguntas[0][0], perguntas[0][0]
                assert hash_do(caminho) == antes_hash and len(backup_mod.listar_backups(caminho)) == backups_antes
                assert not tela._modo_leitura_cliente, "continua editando"
                assert apenas_digitos(tela._cpf_selecionado) == apenas_digitos(cpf_f) and not avisos
                msgs.exigir_sem_erros("cancelar")

                resposta["indice"] = 0  # Levar junto e salvar
                tela._salvar_edicao_cliente()
                assert len(perguntas) == 2
                msgs.exigir_sem_erros("levar junto")
                assert tela._modo_leitura_cliente and apenas_digitos(tela._cpf_selecionado) == apenas_digitos(cpf_novo_f)
                assert sum(map(len, da_pessoa(cpf_f, caminho))) == 0 and sum(map(len, da_pessoa(cpf_novo_f, caminho))) == 2
                assert len(backup_mod.listar_backups(caminho)) == backups_antes + 1 and avisos
                assert len(tela.lista_vendas.cards) == 1, "a ficha mostra a venda no CPF novo"
                print("OK: Cancelar deixa tudo como está (e a ficha em edição); Levar junto grava, e a ficha mostra "
                      "a venda no CPF novo.")

                # CPF que ja e de outro cliente: erro direto, SEM a pergunta
                tela._selecionar_por_cpf(cpf_novo_f)
                tela._alternar_edicao_cliente()
                tela._campo_cpf.setText(mascarar(cpf_b))
                antes_hash = hash_do(caminho)
                msgs.limpar()
                tela._salvar_edicao_cliente()
                assert len(perguntas) == 2, "CPF repetido: não pergunta"
                assert "Já existe um cliente" in msgs.ultima()[2] and hash_do(caminho) == antes_hash
                assert not tela._modo_leitura_cliente
                tela._alternar_edicao_cliente()  # cancela a edicao
                msgs.limpar()
                print("OK: CPF de outro cliente dá o erro direto, sem a pergunta e sem gravar.")

                # sem nada ligado ao CPF: nao pergunta
                cpf_g, cpf_novo_g = mascarar(fx.cpf_ficticio(300_000_007)), mascarar(fx.cpf_ficticio(300_000_017))
                cadastrar(cpf_g, "CLIENTE G")
                tela._atualizar_lista()
                tela._selecionar_por_cpf(cpf_g)
                tela._alternar_edicao_cliente()
                tela._campo_cpf.setText(cpf_novo_g)
                tela._salvar_edicao_cliente()
                assert len(perguntas) == 2, "sem propostas nem vendas, não pergunta"
                assert tela._modo_leitura_cliente and clientes_mod.buscar_por_cpf(cpf_novo_g)
                msgs.exigir_sem_erros("sem vinculos")
                print("OK: cliente sem propostas nem vendas troca o CPF sem pergunta.")
            finally:
                escolha_dialog.escolher = escolher_original
        linha("TUDO OK")
    finally:
        bd._salvar_planilha = salvar_original
        nuvem._obter_cliente, sheets_sync._obter_cliente, sheets_sync.sincronizar_em_background = rede_original
        fx.restaurar_modulos()
        sessao_mod.encerrar()
        assert fx.instantaneo_do_registro() == registro_antes, "o teste mexeu nas preferências reais"


if __name__ == "__main__":
    main()
