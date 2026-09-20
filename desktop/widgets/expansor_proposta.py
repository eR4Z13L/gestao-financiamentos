"""Card de proposta EXPANSIVEL: o UNICO jeito de ver, editar, lancar e duplicar uma proposta.
A Ficha de Cliente (historico) e a tela Todas as Propostas usam esta mesma classe, entao o
comportamento e o mesmo nas duas. Cada tela diz de onde vem os dados e o que fazer depois de
gravar:

    self._expansor = ExpansorDeProposta(self._lista, self._modelo, self._dados_da_proposta, self._recarregar, self)
    self._lista.acionado.connect(self._expansor.alternar)   # duplo clique / Enter num card
    self._expansor.nova(cpf, nome)                         # "+ Nova Proposta"

Duplo clique num card: o PROPRIO card cresce ali mesmo (a lista se ajusta em volta, nada fica
coberto) e mostra o formulario em modo leitura. So um card fica expandido por vez: expandir outro
recolhe o anterior - e se o anterior tem edicao NAO salva, o app pergunta antes de descartar.

"+ Nova Proposta" e "Duplicar" poem um card "Nova proposta" no topo da lista, ja expandido e em
edicao. Cancel nele volta pra proposta de onde saiu a duplicata (ou so o tira, numa nova de
verdade); gravar cria uma proposta independente - a original nunca e alterada.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QMessageBox

from core import propostas as propostas_mod
from core import sessao as sessao_mod
from desktop.widgets.formulario_proposta import FormularioProposta
from desktop.widgets.lista_cartoes import RASCUNHO, ListaCartoes, ModeloCartoes

# (cpf, nome do cliente, a proposta como dict) de uma proposta da tela, pelo indice real; None se sumiu
ObterProposta = Callable[[int], "tuple[str | None, str | None, dict] | None"]


def _item_do_rascunho(nome_cliente: str | None) -> dict:
    """O card "Nova proposta" (so o cabecalho dele: o resto e o formulario)."""
    titulo = f"Nova proposta — {nome_cliente}" if nome_cliente else "Nova proposta"
    return {
        "tipo": "rascunho", "titulo": titulo, "titulo_vazio": "Nova proposta", "linha2": "",
        "cliente": "", "status": "", "data": "", "tempo": "", "etapa": "", "cor": "neutro",
    }


class ExpansorDeProposta(QObject):
    proposta_gravada = Signal(int)  # a posicao real da proposta criada ou alterada (a tela ja foi recarregada)

    def __init__(
        self,
        lista: ListaCartoes,
        modelo: ModeloCartoes,
        obter_proposta: ObterProposta,
        recarregar: Callable[[int | None], None],
        parent: QObject | None = None,
    ):
        """`recarregar(indice)`: a tela le os dados de novo e mantem selecionada a proposta `indice`."""
        super().__init__(parent)
        self._lista = lista
        self._modelo = modelo
        self._obter_proposta = obter_proposta
        self._recarregar = recarregar

        self._formulario: FormularioProposta | None = None
        self._indice_aberto: int | None = None  # a proposta do card expandido (None: nenhum, ou o "Nova proposta")
        self._e_rascunho = False
        self._aberta: dict | None = None  # o que "Duplicar" copia: {"cpf", "nome_cliente", "proposta"}
        self._origem_da_duplicata: int | None = None  # o card que Cancel reabre
        self._perdeu_alteracoes = False

        lista.expansao_perdida.connect(self._ao_perder_expansao)

    # -- consulta ---------------------------------------------------------------

    def formulario(self) -> FormularioProposta | None:
        return self._formulario

    def indice_aberto(self) -> int | None:
        return self._indice_aberto

    def esta_expandido(self) -> bool:
        return self._formulario is not None

    def eh_rascunho(self) -> bool:
        return self._e_rascunho

    def tem_alteracoes(self) -> bool:
        """Ha um card expandido com edicao que ainda nao foi salva."""
        return self._formulario is not None and self._formulario.tem_alteracoes()

    # -- abrir e recolher -------------------------------------------------------------

    def alternar(self, linha: int) -> None:
        """Duplo clique (ou Enter) no card da `linha`: expande; no que ja esta expandido, recolhe."""
        if self._modelo.eh_rascunho(linha):
            return
        indice = self._modelo.indice_real(linha)
        if indice is None:
            return
        if indice == self._indice_aberto:
            if self._formulario is not None and self._formulario._modo_leitura:
                self._soltar()
                self._lista.setFocus()
            return  # em edicao nao recolhe: Cancel ou OK primeiro
        if not self.liberar():
            return
        self._expandir_indice(indice)

    def nova(self, cpf: str | None, nome_cliente: str | None = None) -> None:
        """"+ Nova Proposta": o card "Nova proposta" no topo, em edicao. `cpf=None`: com o campo de
        cliente pra escolher."""
        if not self.liberar():
            return
        self._origem_da_duplicata = None
        self._abrir_rascunho(cpf, nome_cliente)

    def nova_a_partir_de(self, cpf: str, nome_cliente: str, proposta: dict) -> None:
        """O card "Nova proposta" no topo, em edicao, ja preenchido a partir de `proposta` pela mesma
        regra do botao Duplicar (mesmo cliente, equipamento e valor; data de hoje, sem banco, em analise).
        Cancelar so tira o card: nao ha proposta de onde "voltar"."""
        if not self.liberar():
            return
        self._origem_da_duplicata = None
        self._abrir_rascunho(cpf, nome_cliente, base=propostas_mod.dados_para_duplicar(proposta))

    def liberar(self) -> bool:
        """Deixa nada expandido, se der: com edicao NAO salva, pergunta antes de descartar. False =
        a pessoa preferiu continuar editando (quem chamou nao deve seguir)."""
        if self._formulario is None:
            return True
        if self._formulario.tem_alteracoes() and not self._confirmar_descarte():
            return False
        self._soltar()
        return True

    def descartar(self) -> bool:
        """Recolhe tudo sem perguntar (a tela mudou de assunto: outro cliente, proposta excluida...).
        Devolve True se havia edicao nao salva - quem chamou avisa a pessoa."""
        tinha = self._formulario is not None and self._formulario.tem_alteracoes()
        self._soltar()
        return tinha

    def _confirmar_descarte(self) -> bool:
        resposta = QMessageBox.question(
            self._lista,
            "Alterações não salvas",
            "Este card tem alterações que ainda não foram salvas. Descartar as alterações e continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return resposta == QMessageBox.StandardButton.Yes

    def _soltar(self) -> None:
        """Recolhe o card expandido (e tira o card "Nova proposta", se era ele)."""
        era_rascunho = self._e_rascunho
        self._limpar_estado()
        self._lista.recolher()
        if era_rascunho:
            self._modelo.definir_rascunho(None)

    def _limpar_estado(self) -> None:
        self._formulario = None
        self._indice_aberto = None
        self._e_rascunho = False
        self._aberta = None

    def _ao_perder_expansao(self, _chave) -> None:
        """A lista descartou o card expandido: a proposta saiu dela (filtro, recarga...)."""
        if self._formulario is not None and self._formulario.tem_alteracoes():
            self._perdeu_alteracoes = True
            # depois, fora do meio da recarga da lista: o aviso e modal
            QTimer.singleShot(0, self._avisar_alteracoes_descartadas)
        self._limpar_estado()
        self._origem_da_duplicata = None

    def _avisar_alteracoes_descartadas(self) -> None:
        if not self._perdeu_alteracoes:
            return
        self._perdeu_alteracoes = False
        QMessageBox.information(
            self._lista,
            "Alterações descartadas",
            "A proposta que estava sendo editada saiu da lista e as alterações que não tinham sido salvas foram descartadas.",
        )

    # -- expandir uma proposta existente ---------------------------------------------

    def _expandir_indice(self, indice: int) -> bool:
        linha = self._modelo.linha_do_indice_real(indice)
        if linha is None:
            return False
        dados = self._obter_proposta(indice)
        if dados is None:
            QMessageBox.warning(self._lista, "Proposta não encontrada", "Esta proposta pode ter sido removida. Atualize a lista.")
            return False
        cpf, nome_cliente, proposta = dados
        formulario = FormularioProposta(cpf, nome_cliente, proposta=proposta, indice=indice)
        self._conectar(formulario)
        self._formulario = formulario
        self._indice_aberto = indice
        self._e_rascunho = False
        self._aberta = {"cpf": cpf, "nome_cliente": nome_cliente, "proposta": proposta}
        self._lista.expandir(indice, formulario)
        formulario.dar_foco_inicial()
        self._lista.garantir_visivel(linha)
        return True

    def _abrir_rascunho(self, cpf: str | None, nome_cliente: str | None, base: dict | None = None) -> None:
        self._modelo.definir_rascunho(_item_do_rascunho(nome_cliente))
        formulario = FormularioProposta(cpf, nome_cliente, base=base)
        self._conectar(formulario)
        self._formulario = formulario
        self._indice_aberto = None
        self._e_rascunho = True
        self._aberta = None
        self._lista.expandir(RASCUNHO, formulario)
        formulario.dar_foco_inicial()
        self._lista.garantir_visivel(0)

    def _conectar(self, formulario: FormularioProposta) -> None:
        formulario.gravada.connect(self._ao_gravar)
        formulario.recolher_pedido.connect(self._ao_recolher_pedido)
        formulario.cancelada.connect(self._ao_cancelar_rascunho)
        formulario.duplicacao_pedida.connect(self._duplicar)

    # -- reacoes do formulario -----------------------------------------------------------

    def _ao_recolher_pedido(self) -> None:
        self._soltar()
        self._lista.setFocus()

    def _duplicar(self) -> None:
        origem = self._aberta
        # o botao ja fica escondido pro VENDEDOR; aqui e a segunda trava (a de verdade, ao gravar, e a do core)
        if origem is None or self._indice_aberto is None or not sessao_mod.eh_admin():
            return
        base = propostas_mod.dados_para_duplicar(origem["proposta"])
        indice_origem = self._indice_aberto
        self._soltar()  # a original volta ao tamanho normal (esta em leitura: nada a perder)
        self._origem_da_duplicata = indice_origem
        self._abrir_rascunho(origem["cpf"], origem["nome_cliente"], base=base)

    def _ao_cancelar_rascunho(self) -> None:
        origem, self._origem_da_duplicata = self._origem_da_duplicata, None
        self._soltar()
        if origem is not None:
            self._expandir_indice(origem)  # a duplicata era de uma proposta: volta pra leitura dela
        else:
            self._lista.setFocus()

    def _ao_gravar(self) -> None:
        formulario = self._formulario
        indice = None if formulario is None else formulario.indice_gravado
        era_rascunho = self._e_rascunho
        self._origem_da_duplicata = None
        self._soltar()
        if indice is None:
            return
        self._recarregar(indice)  # a tela le de novo e deixa selecionada a proposta gravada
        if era_rascunho:
            linha = self._modelo.linha_do_indice_real(indice)
            if linha is not None:
                self._lista.garantir_visivel(linha)  # a proposta nova aparece na lista: mostra onde
        else:
            self._expandir_indice(indice)  # volta a leitura, ja com o que foi gravado
        self.proposta_gravada.emit(indice)
