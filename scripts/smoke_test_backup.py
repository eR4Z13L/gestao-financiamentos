"""Testa core/backup.py (backup automático/manual, limpeza das 7 cópias mais recentes,
restaurar com backup de segurança antes) isoladamente, numa pasta temporária - nunca em
data/ (nem no arquivo real, nem na pasta data/backups/ de verdade).

Rodar com: venv/Scripts/python.exe scripts/smoke_test_backup.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
from core import backup as backup_mod
from core import data_store as bd
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _criar_planilha_vazia(caminho: Path) -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nome, colunas in (
        (bd.ABA_CLIENTES, bd.CLIENTES_COLUNAS),
        (bd.ABA_EQUIPAMENTOS, bd.EQUIPAMENTOS_COLUNAS),
        (bd.ABA_PROPOSTAS, bd.PROPOSTAS_COLUNAS),
        (bd.ABA_VENDEDORES, bd.VENDEDORES_COLUNAS),
    ):
        wb.create_sheet(nome).append(colunas)
    wb.save(caminho)


def testar_fazer_backup_e_listar(arquivo: Path) -> None:
    linha("1) fazer_backup cria um arquivo reconhecido; listar_backups devolve do mais recente pro mais antigo")
    pasta = backup_mod._pasta_backups(arquivo)
    assert not pasta.exists(), "a pasta de backups só deve nascer quando o primeiro backup for feito"

    caminho1 = backup_mod.fazer_backup(backup_mod.MOTIVO_MANUAL, arquivo)
    assert caminho1.exists() and caminho1.parent == pasta
    assert caminho1.read_bytes() == arquivo.read_bytes(), "o backup é uma cópia fiel do arquivo"

    time.sleep(1.1)  # o timestamp no nome só tem resolução de segundo
    caminho2 = backup_mod.fazer_backup(backup_mod.MOTIVO_AUTOMATICO, arquivo)
    assert caminho2 != caminho1, "nomes diferentes (timestamps diferentes)"

    backups = backup_mod.listar_backups(arquivo)
    assert [b.caminho for b in backups] == [caminho2, caminho1], "mais recente primeiro"
    assert backups[0].motivo == backup_mod.MOTIVO_AUTOMATICO and backups[0].eh_automatico
    assert backups[1].motivo == backup_mod.MOTIVO_MANUAL and not backups[1].eh_automatico
    assert backups[0].tamanho_bytes == arquivo.stat().st_size
    print(f"OK: 2 backups criados ({caminho1.name}, {caminho2.name}), listados do mais recente pro mais antigo.")

    arquivo_alheio = pasta / f"{arquivo.stem}.txt"
    arquivo_alheio.write_text("nao e um backup, so um arquivo qualquer na mesma pasta")
    assert len(backup_mod.listar_backups(arquivo)) == 2, "arquivo fora do padrão de nome é ignorado"
    arquivo_alheio.unlink()
    print("OK: um arquivo na pasta que não segue o padrão de nome deste módulo é ignorado pela listagem.")

    for f in pasta.glob("*.xlsx"):
        f.unlink()


def testar_colisao_no_mesmo_segundo(arquivo: Path) -> None:
    linha("1b) dois backups do MESMO motivo no mesmo segundo não se sobrescrevem")
    pasta = backup_mod._pasta_backups(arquivo)
    caminhos = [backup_mod.fazer_backup(backup_mod.MOTIVO_MANUAL, arquivo) for _ in range(3)]
    assert len(set(caminhos)) == 3, "3 chamadas seguidas (mesmo timestamp provável) geram 3 arquivos distintos"
    for c in caminhos:
        assert c.exists()
    assert len(backup_mod.listar_backups(arquivo)) == 3, "nenhum foi sobrescrito calado por outro"
    print(f"OK: {len(caminhos)} backups manuais feitos em sequência rápida, todos preservados: {[c.name for c in caminhos]}")

    for f in pasta.glob("*.xlsx"):
        f.unlink()


def testar_limpeza_automatica(arquivo: Path) -> None:
    linha("2) limpar_backups_automaticos mantém só os 7 mais recentes 'auto' - nunca mexe em manual/pré-restauração")
    pasta = backup_mod._pasta_backups(arquivo)
    for f in pasta.glob("*.xlsx"):
        f.unlink()

    # cria 10 backups "auto" com timestamps ja no NOME (sem precisar de 10 sleeps de verdade)
    base = datetime(2026, 1, 1, 12, 0, 0)
    caminhos_auto = []
    for i in range(10):
        quando = (base + timedelta(days=i)).strftime(backup_mod._FORMATO_TIMESTAMP)
        destino = pasta / f"{arquivo.stem}.{backup_mod.MOTIVO_AUTOMATICO}-{quando}.xlsx"
        shutil.copy2(arquivo, destino)
        caminhos_auto.append(destino)
    manual = backup_mod.fazer_backup(backup_mod.MOTIVO_MANUAL, arquivo)
    seguranca = backup_mod.fazer_backup(backup_mod.MOTIVO_PRE_RESTAURACAO, arquivo)

    apagados = backup_mod.limpar_backups_automaticos(arquivo)
    assert apagados == 10 - backup_mod.MAXIMO_BACKUPS_AUTOMATICOS
    restantes = backup_mod.listar_backups(arquivo)
    automaticos_restantes = [b for b in restantes if b.eh_automatico]
    assert len(automaticos_restantes) == backup_mod.MAXIMO_BACKUPS_AUTOMATICOS
    assert {b.caminho for b in automaticos_restantes} == set(caminhos_auto[-backup_mod.MAXIMO_BACKUPS_AUTOMATICOS:]), (
        "mantém os mais RECENTES (os 3 mais antigos, dias 0/1/2, são os apagados)"
    )
    assert manual.exists(), "backup manual nunca é apagado pela limpeza automática"
    assert seguranca.exists(), "backup de pré-restauração nunca é apagado pela limpeza automática"
    print(f"OK: de 10 backups automáticos, {apagados} apagados, restando os {backup_mod.MAXIMO_BACKUPS_AUTOMATICOS} mais recentes; manual e pré-restauração intactos.")

    for f in pasta.glob("*.xlsx"):
        f.unlink()


def testar_backup_diario(arquivo: Path) -> None:
    linha("3) backup_diario_se_necessario: 1 por dia (idempotente no mesmo dia)")
    pasta = backup_mod._pasta_backups(arquivo)
    for f in pasta.glob("*.xlsx"):
        f.unlink()

    primeiro = backup_mod.backup_diario_se_necessario(arquivo)
    assert primeiro is not None and primeiro.exists()
    segundo = backup_mod.backup_diario_se_necessario(arquivo)
    assert segundo is None, "já tem um automático de hoje - não cria outro"
    assert len([b for b in backup_mod.listar_backups(arquivo) if b.eh_automatico]) == 1
    print("OK: a segunda chamada no mesmo dia não cria um segundo backup automático.")

    ontem = (datetime.now() - timedelta(days=1)).strftime(backup_mod._FORMATO_TIMESTAMP)
    (pasta / f"{arquivo.stem}.{backup_mod.MOTIVO_AUTOMATICO}-{ontem}.xlsx").write_bytes(b"")
    primeiro.unlink()  # so sobra o "de ontem" (o de hoje foi removido de proposito)
    terceiro = backup_mod.backup_diario_se_necessario(arquivo)
    assert terceiro is not None, "sem nenhum automático de HOJE (só de ontem), faz um novo"
    print("OK: um dia novo sem backup automático ainda faz o backup do dia.")

    for f in pasta.glob("*.xlsx"):
        f.unlink()


def testar_restaurar(tmp: Path, arquivo: Path) -> None:
    linha("4) restaurar_backup: faz backup de segurança do estado atual, depois restaura o conteúdo escolhido")
    pasta = backup_mod._pasta_backups(arquivo)
    for f in pasta.glob("*.xlsx"):
        f.unlink()

    vendedores_mod.adicionar_vendedor("Vendedor Antes Do Backup")
    antigo = backup_mod.fazer_backup(backup_mod.MOTIVO_MANUAL, arquivo)
    vendedores_mod.adicionar_vendedor("Vendedor Depois Do Backup")
    assert "Vendedor Depois Do Backup" in vendedores_mod.listar_vendedores()

    antes_da_restauracao = len(backup_mod.listar_backups(arquivo))
    seguranca = backup_mod.restaurar_backup(antigo, arquivo)
    assert seguranca.exists() and seguranca != antigo
    assert seguranca.name.split(".")[-2].startswith(backup_mod.MOTIVO_PRE_RESTAURACAO)
    assert len(backup_mod.listar_backups(arquivo)) == antes_da_restauracao + 1, "o backup de segurança entrou pra lista"

    vendedores_novos = vendedores_mod.listar_vendedores()
    assert "Vendedor Depois Do Backup" not in vendedores_novos, "voltou pro estado de antes"
    assert "Vendedor Antes Do Backup" in vendedores_novos
    print("OK: restaurar trouxe o conteúdo do backup escolhido de volta, e salvou o estado anterior antes de mexer em nada.")

    seguranca_df = bd.ler_vendedores(seguranca)
    assert "Vendedor Depois Do Backup" in seguranca_df["NOME"].tolist(), "o backup de segurança tem o estado ANTES de restaurar"
    print("OK: o próprio backup de segurança pode desfazer a restauração (tem o estado que existia antes dela).")

    linha("5) restaurar_backup recusa se o arquivo real estiver 'aberto no Excel'")
    trava = bd._caminho_arquivo_bloqueio(arquivo)
    trava.write_text("")
    try:
        backup_mod.restaurar_backup(antigo, arquivo)
        raise AssertionError("deveria ter recusado com o arquivo bloqueado")
    except bd.ErroArquivoBloqueado as exc:
        assert "aberto no Excel" in str(exc)
    finally:
        trava.unlink(missing_ok=True)
    print("OK: com o arquivo de trava do Excel presente, restaurar recusa em vez de sobrescrever no meio de uma edição.")

    linha("6) restaurar_backup recusa se o backup escolhido não existe mais")
    inexistente = pasta / f"{arquivo.stem}.manual-99991231-235959.xlsx"
    try:
        backup_mod.restaurar_backup(inexistente, arquivo)
        raise AssertionError("deveria ter recusado backup inexistente")
    except FileNotFoundError:
        pass
    print("OK: escolher um backup que já foi apagado da pasta é recusado (nunca tenta copiar o que não existe).")

    for f in pasta.glob("*.xlsx"):
        f.unlink()


def main() -> None:
    registro_antes = fx.instantaneo_do_registro()
    tmp = Path(tempfile.mkdtemp(prefix="_smoke_backup_"))
    try:
        arquivo = tmp / "controle.xlsx"
        _criar_planilha_vazia(arquivo)
        fx.apontar_modulos_para(arquivo)
        sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))

        testar_fazer_backup_e_listar(arquivo)
        testar_colisao_no_mesmo_segundo(arquivo)
        testar_limpeza_automatica(arquivo)
        testar_backup_diario(arquivo)
        testar_restaurar(tmp, arquivo)

        linha("TUDO OK")
    finally:
        fx.restaurar_modulos()
        sessao_mod.encerrar()
        shutil.rmtree(tmp, ignore_errors=True)
        assert fx.instantaneo_do_registro() == registro_antes, "não pode ter mexido no registro real"


if __name__ == "__main__":
    main()
