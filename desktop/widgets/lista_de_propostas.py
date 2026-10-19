"""A lista de cards de proposta (um por pedido a um banco): Todas as Propostas e, na Ficha, as de antes das vendas.

Os cards ficam em colunas que encaixam (desktop/widgets/colunas_que_encaixam.py, a mesma peca da lista de vendas);
esta lista cuida de qual esta ABERTO (um por vez: ele so cresce para baixo, na propria coluna), do formulario dentro
dele, do card "Nova proposta" (o "+ Nova proposta" do topo, que escolhe o cliente e a venda, e o Duplicar do
Dashboard) e de nunca descartar algo digitado sem perguntar. Excluir so
de dentro do formulario, com confirmacao - nada de selecionar varias para apagar. Quem mostra a lista decide QUAIS
propostas aparecem (busca, filtros, o cliente da ficha) e rele depois de gravar: a lista avisa pelo sinal `gravou`.

O ADMIN abre a proposta direto no formulario em edicao; o VENDEDOR (so leitura) ve o mesmo formulario travado.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QMessageBox, QScrollArea, QWidget

from core import sessao as sessao_mod
from core import vendas as vendas_mod
from desktop.widgets.card_da_proposta import CardDaProposta, CardNovaProposta
from desktop.widgets.card_da_venda import LARGURA_CARD, ControleDasVendas
from desktop.widgets.colunas_que_encaixam import ListaEmColunas
from desktop.widgets.encerrar_propostas_da_venda import perguntar_e_encerrar
from desktop.widgets.exclusao_proposta import excluir_proposta_com_confirmacao
from desktop.widgets.formulario_proposta import FormularioProposta

NOVA = "nova"  # a chave do card "Nova proposta"

# a linha da proposta (dict) como a tela a leu, pelo indice real; None se ela nao esta mais na leitura
LinhaDaProposta = Callable[[int], "dict | None"]


def chave_da_proposta(item: vendas_mod.PropostaNaLista) -> str:
    """O ID_PROPOSTA; as de antes das vendas, sem ID, pela posicao no arquivo."""
    return item.proposta.id or f"#{item.proposta.indice}"


class ListaDePropostas(ListaEmColunas):
    gravou = Signal(str)  # gravou algo (o aviso a mostrar, "" = nenhum): quem mostra a lista rele as propostas
    ficha_pedida = Signal(str)  # cpf
    venda_pedida = Signal(str, str)  # (ID_VENDA, ID_PROPOSTA) ("Ver na venda")

    def __init__(self, rolagem: QScrollArea, linha_da_proposta: LinhaDaProposta, parent: QWidget | None = None, *,
                 com_ficha: bool = True, uma_coluna: bool = False):
        """`rolagem`: quem rola a lista (a da tela). `linha_da_proposta`: o formulario abre com o que a tela leu.
        `com_ficha`: o "Abrir a ficha" do card aberto (na propria ficha nao faz sentido). `uma_coluna`: a Ficha."""
        super().__init__(rolagem, parent, largura_card=LARGURA_CARD, uma_coluna=uma_coluna)
        self._linha_da_proposta = linha_da_proposta
        self._com_ficha = com_ficha
        self._propostas: list[vendas_mod.PropostaNaLista] = []
        self.aberta: str | None = None  # a chave (chave_da_proposta) do card aberto
        self.rascunho: dict | None = None  # o card "Nova proposta": {"cpf", "nome", "base", "escolher_venda"}
        self.antes_de_editar: Callable[[], bool] | None = None  # False: nao abre (na Ficha, o outro formulario)
        self.controle = ControleDasVendas(self, self.gravou.emit)
        self._linha_aberta: dict | None = None  # a proposta como o formulario aberto a abriu (o excluir confere)

    # -- propostas ----------------------------------------------------------------------------------

    def definir_propostas(self, propostas: list[vendas_mod.PropostaNaLista], *, texto_vazio: str = "",
                          voltar_ao_inicio: bool = False) -> None:
        """As propostas a mostrar, na ordem. `voltar_ao_inicio`: outra lista (busca, filtro, outro cliente) - volta
        a primeira pagina e nao devolve a rolagem; senao (releu depois de gravar) tudo fica onde estava."""
        self._propostas = list(propostas)
        if self.aberta not in {chave_da_proposta(p) for p in self._propostas}:
            self.aberta = None
        self._remontar(texto_vazio, voltar_ao_inicio)

    def _remontar(self, texto_vazio: str | None = None, voltar_ao_inicio: bool = False) -> None:
        itens = ([NOVA] if self.rascunho is not None else []) + self._propostas
        self._definir_itens(itens, self.vazio.text() if texto_vazio is None else texto_vazio, voltar_ao_inicio)

    def total(self) -> int:
        return len(self._propostas)

    def propostas(self) -> list[vendas_mod.PropostaNaLista]:
        """Todas as que a lista mostra, na ordem (os cards vem de 30 em 30)."""
        return list(self._propostas)

    def _chave(self, item) -> str:
        return NOVA if item == NOVA else chave_da_proposta(item)

    def _posicao_que_precisa_aparecer(self) -> int | None:
        """O card aberto nunca fica alem da pagina carregada (abrir pelo "Ver na venda", mudar a busca): ele aparece."""
        if self.aberta is None:
            return None
        deslocamento = 1 if self.rascunho is not None else 0
        return next((i + deslocamento for i, p in enumerate(self._propostas) if chave_da_proposta(p) == self.aberta), None)

    def _formulario_aberto(self) -> tuple[str, FormularioProposta] | None:
        for card in self.cards:
            if isinstance(card, CardNovaProposta) and self.rascunho is not None:
                return NOVA, card.formulario
            if isinstance(card, CardDaProposta) and card.formulario is not None and self.aberta == chave_da_proposta(card.item):
                return self.aberta, card.formulario
        return None

    def _criar_card(self, item) -> QWidget:
        if item == NOVA:
            return self._card_do_rascunho()
        card = CardDaProposta(item, self, aberto=chave_da_proposta(item) == self.aberta, com_ficha=self._com_ficha)
        self.controle.conectar_proposta(card)
        card.abrir_pedido.connect(self.abrir_proposta)
        card.fechar_pedido.connect(lambda _p: self.fechar_proposta())
        card.venda_pedida.connect(self.venda_pedida)
        card.ficha_pedida.connect(self.ficha_pedida)
        if card.aberto:
            self._por_formulario(card)
        return card

    # -- card aberto e formulario -------------------------------------------------------------------

    def card_aberto(self) -> CardDaProposta | CardNovaProposta | None:
        return next((c for c in self.cards if getattr(c, "aberto", False) or isinstance(c, CardNovaProposta)), None)

    def tem_edicao_pendente(self) -> bool:
        return any(c.tem_alteracoes() for c in self.cards if isinstance(c, (CardDaProposta, CardNovaProposta)))

    def pode_descartar(self) -> bool:
        """Ha algo digitado no formulario aberto? Pergunta antes de descartar."""
        if not self.tem_edicao_pendente():
            return True
        resposta = QMessageBox.question(
            self, "Alterações não salvas", "Há uma proposta com alterações que ainda não foram salvas. Descartar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        return resposta == QMessageBox.StandardButton.Yes

    def descartar(self) -> bool:
        """Fecha o que estiver aberto sem perguntar (quem chama ja perguntou ou vai avisar). True se havia algo
        digitado."""
        tinha = self.tem_edicao_pendente()
        if self.aberta is not None or self.rascunho is not None:
            self.aberta, self.rascunho = None, None
            self._remontar()
        return tinha

    def liberar(self) -> bool:
        """Fecha o que estiver aberto, perguntando antes de descartar o digitado. False = a pessoa preferiu continuar
        editando (quem chamou nao segue)."""
        if self.aberta is None and self.rascunho is None:
            return True
        if not self.pode_descartar():
            return False
        self.aberta, self.rascunho = None, None
        self._remontar()
        return True

    def abrir_proposta(self, item: vendas_mod.PropostaNaLista) -> bool:
        chave = chave_da_proposta(item)
        if chave == self.aberta and self.rascunho is None:
            return True
        if not self.pode_descartar():
            return False
        if self.antes_de_editar is not None and not self.antes_de_editar():
            return False
        self.aberta, self.rascunho = chave, None
        self._remontar()
        self.rolar_ate(self.card_aberto())
        return True

    def fechar_proposta(self) -> bool:
        if not self.pode_descartar():
            return False
        self.aberta = None
        self._remontar()
        return True

    def nova_proposta(self) -> bool:
        """O "+ Nova proposta" de Todas as Propostas: o card "Nova proposta" no topo, com o cliente (busca) e a venda
        (uma em aberto dele, ou uma venda nova junto). Se ja ha um, ele fica (com o que foi digitado)."""
        if not sessao_mod.eh_admin():
            return False
        if self.rascunho is not None and self.rascunho.get("escolher_venda"):
            self.rolar_ate(self.card_aberto())
            return True
        if not self.pode_descartar():
            return False
        if self.antes_de_editar is not None and not self.antes_de_editar():
            return False
        self.aberta = None
        self.rascunho = {"cpf": None, "nome": "", "base": None, "escolher_venda": True}
        self._remontar()
        self.rolar_ate(self.card_aberto())
        return True

    def _card_do_rascunho(self) -> CardNovaProposta:
        formulario = self._formulario_guardado(NOVA)
        if formulario is None:
            formulario = FormularioProposta(self.rascunho["cpf"], self.rascunho["nome"], base=self.rascunho["base"],
                                            escolher_venda=self.rascunho.get("escolher_venda", False))
            formulario.gravada.connect(self._ao_gravar_formulario)
            formulario.cancelada.connect(self._ao_cancelar)
            QTimer.singleShot(0, formulario.dar_foco_inicial)
        return CardNovaProposta(self.rascunho["nome"], formulario, self)

    def _por_formulario(self, card: CardDaProposta) -> None:
        item = card.item
        admin = sessao_mod.eh_admin()
        guardado = self._formulario_guardado(chave_da_proposta(item))
        if guardado is not None:  # o mesmo de antes da montagem, com o que ja foi digitado
            linha = self._linha_aberta
            card.mostrar_formulario(guardado, (lambda: self._excluir(item, linha)) if admin else None)
            return
        linha = self._linha_da_proposta(item.proposta.indice)
        if linha is None:  # nunca falhar em silencio (ex.: a proposta sumiu entre a leitura e o clique)
            QMessageBox.warning(self, "Não foi possível abrir a proposta",
                                "A proposta pode ter sido removida ou mudado de lugar. Recarregue a lista.")
            self.aberta = None
            QTimer.singleShot(0, self._remontar)  # o card ja nasceu aberto: fecha
            return
        if not admin:
            # o VENDEDOR so le, e pode estar num computador sem o arquivo local (onde a venda mora): o equipamento
            # aparece como esta escrito na proposta, sem as caixinhas da venda
            linha = {coluna: valor for coluna, valor in linha.items() if coluna != "ID_VENDA"}
        try:
            formulario = FormularioProposta(item.cpf, item.cliente, proposta=linha, indice=item.proposta.indice,
                                            so_edicao=admin)
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.warning(self, "Não foi possível abrir a proposta", f"{type(exc).__name__}: {exc}")
            self.aberta = None
            QTimer.singleShot(0, self._remontar)
            return
        formulario.gravada.connect(self._ao_gravar_formulario)
        formulario.cancelada.connect(self._ao_cancelar)
        formulario.recolher_pedido.connect(self._ao_cancelar)
        formulario.efetivada_agora.connect(self._ao_efetivar)
        self._linha_aberta = linha
        card.mostrar_formulario(formulario, (lambda: self._excluir(item, linha)) if admin else None)
        QTimer.singleShot(0, formulario.dar_foco_inicial)

    def _ao_gravar_formulario(self) -> None:
        self.aberta, self.rascunho = None, None
        QTimer.singleShot(0, lambda: self.gravou.emit("Proposta gravada."))  # fora do sinal do formulario

    def _ao_cancelar(self) -> None:
        self.aberta, self.rascunho = None, None
        QTimer.singleShot(0, self._remontar)

    def _ao_efetivar(self, cpf: str, equipamento: str, indice: int) -> None:
        """Uma proposta de antes das vendas virou Efetivado no formulario: oferece encerrar as outras em aberto do mesmo
        cliente+equipamento (como sempre). Chega ANTES de `gravada`: o pai do dialogo e a lista, que sobrevive."""
        perguntar_e_encerrar(self, cpf, equipamento, indice)

    def _excluir(self, item: vendas_mod.PropostaNaLista, linha: dict) -> None:
        """O "Excluir esta proposta…" do formulario aberto, com confirmacao: numa venda, pelo mesmo caminho do card da
        venda; as de antes das vendas, pela posicao, conferindo que a linha ainda e a mesma."""
        if item.venda is not None and item.proposta.id:
            self.controle.excluir_proposta(item.venda, item.proposta)  # confirma, grava e avisa `gravou`
            return
        if excluir_proposta_com_confirmacao(self, item.proposta.indice, item.cliente or item.cpf, linha):
            self.aberta = None
            self.gravou.emit(f"{item.cliente or item.cpf}: proposta do {item.proposta.banco or 'banco'} excluída.")
