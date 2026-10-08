"""
Monitor de disponibilidade - Trem de Passageiros EFVM (Vale)
 
Uso:
    pip install requests
    python efvmTicketSearcher.py
 
Comportamento:
  - SO IDA: ao encontrar passagem, avisa, PARA a busca e pergunta se o
    usuario quer fazer uma nova busca ou encerrar o programa.
  - IDA E VOLTA: monitora IDA e VOLTA em paralelo.
      * Vaga individual (so ida ou so volta): avisa, mas continua buscando.
      * Vaga nos dois trechos AO MESMO TEMPO (conjunto): avisa, PARA a busca
        e pergunta se o usuario quer fazer uma nova busca ou encerrar.
"""
 
import json
import threading
import time
from datetime import date, datetime, timedelta, timezone
 
import requests
 
try:
    import winsound  # Windows
except ImportError:
    winsound = None
 
# ----------------------------------------------------------------------
# CONFIGURACOES GERAIS
# ----------------------------------------------------------------------
BASE = "https://tremdepassageiros.vale.com/sgpweb/rest/externo"
CODIGO_FERROVIA = "03"            # Estrada de Ferro Vitoria a Minas
DIAS_LIBERACAO_VENDA = 45         # quantidadeDiasLiberacaoVenda
INTERVALO_SEGUNDOS = 30           # intervalo entre ciclos de consulta
PAUSA_ENTRE_CONSULTAS = 2         # segundos entre consultas dentro do mesmo ciclo
BACKOFF_MAXIMO = 600              # em erro, espera ate 10 min entre tentativas
 
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://tremdepassageiros.vale.com",
    "Referer": "https://tremdepassageiros.vale.com/sgpweb/portal/index.html",
    "User-Agent": "Mozilla/5.0 (monitor pessoal de disponibilidade)",
}
 
URL_COMPRA = "https://tremdepassageiros.vale.com/sgpweb/portal/index.html#/home"
 
# Tecla usada para voltar durante o preenchimento dos dados.
TECLA_VOLTAR = "V"
 
# Visual do terminal
LARGURA = 70
LINHA_DUPLA = "=" * LARGURA
LINHA_SIMPLES = "-" * LARGURA
 
# Lock para impedir que duas threads escrevam no terminal ao mesmo tempo.
PRINT_LOCK = threading.Lock()
 
# ----------------------------------------------------------------------
# DADOS JA CONHECIDOS
# ----------------------------------------------------------------------
ESTACOES = {
    7166: "Aimores",
    7180: "Antonio Dias",
    7160: "Aricanga (Ibiracu / Aracruz)",
    7165: "Baixo Guandu",
    7170: "Barra do Cuiete (Conselheiro Pena)",
    7185: "Belo Horizonte",
    7162: "Colatina",
    7169: "Conselheiro Pena",
    7168: "Crenaque (Resplendor)",
    7181: "Desembargador Drumond (Nova Era)",
    7184: "Dois Irmaos (Barao de Cocais / Sta. Barbara)",
    7158: "Flexal",
    7176: "Frederico Sellow (Cachoeira Escura / Belo Oriente)",
    7159: "Fundao",
    7173: "Governador Valadares",
    7178: "Intendente Camara (Ipatinga)",
    7177: "Ipaba",
    7183: "Itabira",
    7163: "Itapina (Colatina)",
    7182: "Joao Monlevade",
    7164: "Mascarenhas (Baixo Guandu)",
    7179: "Mario Carvalho (Timoteo)",
    7174: "Pedra Corrida (Periquito)",
    7157: "Pedro Nolasco (Cariacica / Vitoria)",
    7175: "Periquito",
    7161: "Piraqueacu (J. Neiva / Linhares / S. Mateus)",
    7167: "Resplendor",
    7186: "Rio Piracicaba",
    7171: "Sao Tome do Rio Doce (Tumiritinga)",
    7172: "Tumiritinga",
}
 
CLASSES = {
    43: "Economica",
    44: "Executiva",
    45: "Cadeirante",
}
 
# Tipos de passagem (o app usa Tarifa Normal; os outros estao aqui se precisar)
TIPO_TARIFA_NORMAL = 33
TIPOS_PASSAGEM = {
    33: "Tarifa Normal (INT)",
    37: "Beneficio Idoso (IDO)",
    38: "PCD (PLD)",
    113: "Acompanhante de PCD (ACOMPCD)",
    39: "Crianca ate 5 anos no colo (COL)",
    116: "Jovem Baixa Renda (JBR)",
    195: "Acompanhante Cadeirante - Tarifa Normal (ACOMTN)",
}
 
# ======================================================================
# ENDPOINT DE DISPONIBILIDADE (copiado do site: pesquisaPassagem)
# ======================================================================
URL_DISPONIBILIDADE = BASE + "/VendaInternet/publico/pesquisaPassagem"
 
# No site, o campo "tremFerias" vem false com Embarque = Dia.
# Para monitorar o trem da noite (alta temporada), mude para True
# (suposicao: nao confirmei que Noite = true).
TREM_FERIAS = False
 
# Se True: faz UMA consulta, imprime a resposta completa e encerra a busca.
MODO_DIAGNOSTICO = False
 
# O site manda a data como meia-noite de Brasilia em milissegundos.
BRT = timezone(timedelta(hours=-3))
 
 
def data_para_ms(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=BRT).timestamp() * 1000)
 
 
def montar_payload(origem_id, destino_id, data_viagem, classe_id, qtd):
    """Mesmo formato que o site envia (so ida; a volta e consultada como
    uma viagem de ida no sentido inverso)."""
    return {
        "codigoFerrovia": CODIGO_FERROVIA,
        "codigoLocalOrigem": origem_id,
        "codigoLocalDestino": destino_id,
        "dataIda": data_para_ms(data_viagem),
        "codigoClasse": classe_id,
        "detalheVenda": [
            {"detalhe": TIPO_TARIFA_NORMAL, "qtd": qtd, "funcionario": False}
        ],
        "tremFerias": TREM_FERIAS,
    }
 
 
def interpretar_resposta(dados, qtd, origem, destino, classe):
    """Devolve (tem_vaga, resumo).
 
    - Resposta sem passagens: "excessao" preenchido e "passagensIda" nulo.
    - Resposta com passagens: lista em "passagensIda". Como o site tem
      "buscarPorSubTrecho", o servidor pode devolver um trecho diferente
      do pedido; so conto como vaga se origem, destino e classe baterem.
    """
    exc = dados.get("excessao")
    if exc:
        if exc.get("tipo") == "N":
            return False, "sem passagens"
        desc = (exc.get("descricao") or "").strip().replace("\n", " ")
        return False, f"aviso do servidor (tipo {exc.get('tipo')}): {desc[:120]}"
 
    passagens = dados.get("passagensIda") or []
    corretas, outros = [], set()
    for p in passagens:
        if (p.get("idOrigem") == origem and p.get("idDestino") == destino
                and p.get("idClasse", classe) == classe):
            corretas.append(p)
        else:
            outros.add(f"{p.get('descricaoOrigem')} -> {p.get('descricaoDestino')}")
 
    if corretas:
        linhas = []
        for p in corretas:
            ms = p.get("partidaPrevista")
            dia = datetime.fromtimestamp(ms / 1000, BRT).strftime("%d/%m") if ms else "--/--"
            valor = f"R$ {p.get('valorTotal', 0):.2f}".replace(".", ",")
            linhas.append(
                f"    Trem {p.get('descricaoTrem')}  {dia}  "
                f"saida {p.get('horaPartidaPrevista')} -> chegada {p.get('horaChegadaPrevista')}  "
                f"{p.get('descricaoClasse')}  {valor}"
            )
        return True, "\n".join(linhas)
    if passagens:
        return False, "servidor devolveu so outro trecho (" + ", ".join(sorted(outros)) + "), ignorado"
    return False, "resposta sem passagens"
 
 
# ----------------------------------------------------------------------
# UTILITARIOS DE TELA
# ----------------------------------------------------------------------
def log(msg):
    with PRINT_LOCK:
        print(msg)
 
 
def titulo_secao(texto):
    print()
    print(LINHA_SIMPLES)
    print(f" {texto}")
    print(LINHA_SIMPLES)
 
 
def mostrar_selecao(dados):
    """Mostra o que ja foi escolhido, para o usuario nao se perder ao voltar."""
    partes = []
    if dados.get("tipo"):
        partes.append("Viagem: " + ("so ida" if dados["tipo"] == 1 else "ida e volta"))
    if dados.get("origem"):
        partes.append(f"De: {ESTACOES[dados['origem']]}")
    if dados.get("destino"):
        partes.append(f"Para: {ESTACOES[dados['destino']]}")
    if dados.get("classes"):
        partes.append("Classe: " + " + ".join(CLASSES[c] for c in dados["classes"]))
    if dados.get("qtd"):
        partes.append(f"Passageiros: {dados['qtd']}")
    if dados.get("d1"):
        partes.append(f"Ida: {dados['d1']:%d/%m/%Y}")
    if dados.get("d2"):
        partes.append(f"Volta: {dados['d2']:%d/%m/%Y}")
    if partes:
        print("\n  Escolhido ate agora:")
        for p in partes:
            print(f"    - {p}")
 
 
# ----------------------------------------------------------------------
# INTERFACE (menus)
# ----------------------------------------------------------------------
def escolher_de_lista(titulo, opcoes):
    """opcoes: dict id -> nome. Retorna o id escolhido ou None (voltar)."""
    itens = sorted(opcoes.items(), key=lambda kv: kv[1])
    titulo_secao(titulo)
    for i, (_, nome) in enumerate(itens, 1):
        print(f"  {i:2d}) {nome}")
    print(f"   {TECLA_VOLTAR}) Voltar")
    while True:
        txt = input("\nDigite o numero: ").strip()
        if txt.upper() == TECLA_VOLTAR:
            return None
        if txt.isdigit() and 1 <= int(txt) <= len(itens):
            return itens[int(txt) - 1][0]
        print("Opcao invalida.")
 
 
def pedir_data(rotulo, minimo=None):
    hoje = date.today()
    primeiro = max(hoje + timedelta(days=1), minimo or hoje)
    ultimo = hoje + timedelta(days=DIAS_LIBERACAO_VENDA)
    titulo_secao(rotulo.upper())
    print(f"  Datas aceitas: {primeiro:%d/%m/%Y} ate {ultimo:%d/%m/%Y}")
    print("  (nao ha venda para o mesmo dia da viagem)")
    print(f"  {TECLA_VOLTAR}) Voltar")
    while True:
        txt = input("\nData (DD/MM/AAAA): ").strip()
        if txt.upper() == TECLA_VOLTAR:
            return None
        try:
            d = datetime.strptime(txt, "%d/%m/%Y").date()
        except ValueError:
            print("Formato invalido. Use DD/MM/AAAA.")
            continue
        if d < primeiro:
            print(f"A data deve ser a partir de {primeiro:%d/%m/%Y}.")
        elif d > ultimo:
            print(f"A venda so abre ate {ultimo:%d/%m/%Y}.")
        else:
            return d
 
 
def pedir_inteiro(rotulo, minimo, maximo, permitir_voltar=True):
    sufixo = f", {TECLA_VOLTAR}=voltar" if permitir_voltar else ""
    while True:
        txt = input(f"\n{rotulo} ({minimo}-{maximo}{sufixo}): ").strip()
        if permitir_voltar and txt.upper() == TECLA_VOLTAR:
            return None
        if txt.isdigit() and minimo <= int(txt) <= maximo:
            return int(txt)
        print("Valor invalido.")
 
 
def escolher_classes():
    """Devolve a lista de ids de classe a monitorar (ou None para voltar)."""
    titulo_secao("CLASSE")
    print("  1) Economica")
    print("  2) Executiva")
    print("  3) Ambas (Economica + Executiva)")
    print("  4) Cadeirante")
    print(f"  {TECLA_VOLTAR}) Voltar")
    while True:
        txt = input("\nEscolha: ").strip()
        if txt.upper() == TECLA_VOLTAR:
            return None
        if txt.isdigit() and 1 <= int(txt) <= 4:
            return {1: [43], 2: [44], 3: [43, 44], 4: [45]}[int(txt)]
        print("Opcao invalida.")
 
 
def montar_trechos():
    """Pergunta tudo ao usuario e devolve (trechos, classes, qtd, tipo)."""
    print()
    print(LINHA_DUPLA)
    print(" MONITOR DE PASSAGENS - TREM DE PASSAGEIROS EFVM (VALE)")
    print(LINHA_DUPLA)
 
    dados = {}
    etapa = 0
 
    while True:
 
        # ETAPA 0 - TIPO DE VIAGEM (primeira etapa: nao ha para onde voltar)
        if etapa == 0:
            titulo_secao("TIPO DE VIAGEM")
            print("  1) So ida")
            print("  2) Ida e volta")
            tipo = pedir_inteiro("Escolha", 1, 2, permitir_voltar=False)
            dados["tipo"] = tipo
            if tipo == 1:
                dados["d2"] = None
            etapa = 1
            continue
 
        # ETAPA 1 - ORIGEM
        if etapa == 1:
            mostrar_selecao(dados)
            origem = escolher_de_lista("ESTACAO DE ORIGEM (partida)", ESTACOES)
            if origem is None:
                etapa = 0
                continue
            dados["origem"] = origem
            if dados.get("destino") == origem:
                dados["destino"] = None
            etapa = 2
            continue
 
        # ETAPA 2 - DESTINO
        if etapa == 2:
            mostrar_selecao(dados)
            restantes = {k: v for k, v in ESTACOES.items() if k != dados["origem"]}
            destino = escolher_de_lista("ESTACAO DE DESTINO (chegada)", restantes)
            if destino is None:
                etapa = 1
                continue
            dados["destino"] = destino
            etapa = 3
            continue
 
        # ETAPA 3 - CLASSE
        if etapa == 3:
            mostrar_selecao(dados)
            classes = escolher_classes()
            if classes is None:
                etapa = 2
                continue
            dados["classes"] = classes
            etapa = 4
            continue
 
        # ETAPA 4 - PASSAGEIROS
        if etapa == 4:
            mostrar_selecao(dados)
            titulo_secao("PASSAGEIROS")
            qtd = pedir_inteiro("Numero de passageiros", 1, 8)
            if qtd is None:
                etapa = 3
                continue
            dados["qtd"] = qtd
            etapa = 5
            continue
 
        # ETAPA 5 - DATA DA IDA
        if etapa == 5:
            mostrar_selecao(dados)
            d1 = pedir_data("Data da IDA")
            if d1 is None:
                etapa = 4
                continue
            dados["d1"] = d1
            if dados.get("d2") is not None and dados["d2"] < d1:
                dados["d2"] = None
            etapa = 6 if dados["tipo"] == 2 else 7
            continue
 
        # ETAPA 6 - DATA DA VOLTA
        if etapa == 6:
            mostrar_selecao(dados)
            d2 = pedir_data("Data da VOLTA", minimo=dados["d1"])
            if d2 is None:
                etapa = 5
                continue
            dados["d2"] = d2
            etapa = 7
            continue
 
        # ETAPA 7 - RESUMO / CONFIRMACAO
        if etapa == 7:
            o, d = dados["origem"], dados["destino"]
            trechos = [("IDA", o, d, dados["d1"])]
            if dados["tipo"] == 2:
                trechos.append(("VOLTA", d, o, dados["d2"]))
 
            titulo_secao("RESUMO DA BUSCA")
            for nome, org, dst, dt in trechos:
                print(f"  {nome:<5}: {ESTACOES[org]} -> {ESTACOES[dst]}  em {dt:%d/%m/%Y}")
            print(f"  Classe(s)  : {' + '.join(CLASSES[c] for c in dados['classes'])}")
            print(f"  Passageiros: {dados['qtd']}")
            print(f"  Frequencia : a cada {INTERVALO_SEGUNDOS}s")
            if dados["tipo"] == 2:
                print("  Avisos     : vagas individuais (ida OU volta) avisam e a busca continua;")
                print("               ida E volta ao mesmo tempo avisam e encerram a busca.")
            else:
                print("  Avisos     : ao encontrar passagem a busca e encerrada.")
            print(f"\n  ENTER = iniciar | {TECLA_VOLTAR} = voltar e corrigir | Ctrl+C = sair")
 
            confirmacao = input("> ").strip()
            if confirmacao.upper() == TECLA_VOLTAR:
                etapa = 6 if dados["tipo"] == 2 else 5
                continue
 
            return trechos, dados["classes"], dados["qtd"], dados["tipo"]
 
 
# ----------------------------------------------------------------------
# ESTADO COMPARTILHADO DA BUSCA
# ----------------------------------------------------------------------
class Busca:
    """Reune tudo que as threads precisam compartilhar."""
 
    def __init__(self, trechos, classes, qtd, tipo):
        self.trechos = trechos
        self.por_nome = {t[0]: t for t in trechos}
        self.classes = classes
        self.qtd = qtd
        self.tipo = tipo
        self.parar = threading.Event()   # sinaliza fim da busca a todas as threads
        self.motivo = None               # "unica", "conjunto", "interrompida", ...
        self.lock = threading.Lock()
        # vagas atualmente disponiveis: (nome_trecho, classe) -> resumo
        self.disponivel = {}
 
 
# ----------------------------------------------------------------------
# CONSULTA E AVISOS
# ----------------------------------------------------------------------
def consultar(sessao, trecho, classe, qtd):
    _, origem, destino, data_viagem = trecho
    payload = montar_payload(origem, destino, data_viagem, classe, qtd)
    resp = sessao.post(URL_DISPONIBILIDADE, json=payload, timeout=20)
    resp.raise_for_status()
    return resp.json()
 
 
def bipar(repeticoes=3):
    """Aviso sonoro suave: 3 toques espacados."""
    for i in range(repeticoes):
        if winsound:
            try:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                winsound.Beep(700, 200)
        else:
            print("\a", end="", flush=True)
        if i < repeticoes - 1:
            time.sleep(1.5)
 
 
def anunciar(titulo, itens, qtd, rodape=None):
    """itens: lista de (trecho, classe, resumo)."""
    with PRINT_LOCK:
        print()
        print(LINHA_DUPLA)
        print(f"  {titulo}")
        print(LINHA_DUPLA)
        for trecho, classe, resumo in itens:
            nome, origem, destino, data_viagem = trecho
            print(f"  {nome}: {ESTACOES[origem]} -> {ESTACOES[destino]}")
            print(f"  Data: {data_viagem:%d/%m/%Y} | {CLASSES[classe]} | {qtd} passageiro(s)")
            print(resumo)
            print(LINHA_SIMPLES)
        print(f"  Encontrada em {datetime.now():%d/%m/%Y as %H:%M:%S}")
        if rodape:
            print(f"  {rodape}")
        print(f"  Compre em: {URL_COMPRA}")
        print(LINHA_DUPLA)
        print()
    bipar()
 
 
def tratar_vaga(busca, trecho, classe, resumo):
    """Registra a vaga e decide o que fazer:
      - so ida: avisa e encerra a busca;
      - ida e volta: se ha vaga nos dois trechos, avisa e encerra;
        se e so um trecho (e e novidade), avisa e continua."""
    nome = trecho[0]
    acao = None
 
    with busca.lock:
        if busca.parar.is_set():
            return  # outra thread ja encerrou a busca
 
        novo = (nome, classe) not in busca.disponivel
        busca.disponivel[(nome, classe)] = resumo
 
        if busca.tipo == 1:
            acao = "unica"
        else:
            tem_ida = any(k[0] == "IDA" for k in busca.disponivel)
            tem_volta = any(k[0] == "VOLTA" for k in busca.disponivel)
            if tem_ida and tem_volta:
                acao = "conjunto"
            elif novo:
                acao = "individual"
 
        if acao in ("unica", "conjunto"):
            busca.motivo = acao
            busca.parar.set()
        snapshot = dict(busca.disponivel)
 
    if acao == "unica":
        anunciar("PASSAGEM ENCONTRADA!", [(trecho, classe, resumo)], busca.qtd)
 
    elif acao == "conjunto":
        itens = [(busca.por_nome[n], c, r) for (n, c), r in sorted(snapshot.items())]
        anunciar("IDA E VOLTA DISPONIVEIS!", itens, busca.qtd)
 
    elif acao == "individual":
        anunciar(
            f"VAGA INDIVIDUAL ({nome}) - busca do conjunto continua",
            [(trecho, classe, resumo)],
            busca.qtd,
            rodape=f"Ainda falta vaga na {'VOLTA' if nome == 'IDA' else 'IDA'} para fechar o conjunto.",
        )
 
 
# ----------------------------------------------------------------------
# MONITORAMENTO DE UM TRECHO (roda em thread propria)
# ----------------------------------------------------------------------
def monitorar_trecho(busca, trecho):
    nome, o, d, dt = trecho
    sessao = requests.Session()
    sessao.headers.update(HEADERS)
 
    espera = INTERVALO_SEGUNDOS
    tentativa = 0
 
    while not busca.parar.is_set():
        tentativa += 1
        falhou = False
 
        for classe in busca.classes:
            if busca.parar.is_set():
                return
 
            agora = datetime.now().strftime("%H:%M:%S")
            prefixo = f"[{agora}] #{tentativa:<3} {nome:<5} {dt:%d/%m} {CLASSES[classe]:<10} |"
 
            try:
                dados = consultar(sessao, trecho, classe, busca.qtd)
 
            except requests.HTTPError as e:
                falhou = True
                log(f"{prefixo} erro HTTP {e.response.status_code}")
                busca.parar.wait(PAUSA_ENTRE_CONSULTAS)
                continue
 
            except (requests.RequestException, ValueError) as e:
                falhou = True
                log(f"{prefixo} erro de rede/JSON: {e}")
                busca.parar.wait(PAUSA_ENTRE_CONSULTAS)
                continue
 
            if MODO_DIAGNOSTICO:
                with PRINT_LOCK:
                    print("\n=== RESPOSTA COMPLETA ===")
                    print(json.dumps(dados, indent=2, ensure_ascii=False))
                    print("=== FIM ===")
                    print("Modo diagnostico: encerrando apos uma consulta.")
                with busca.lock:
                    busca.motivo = "diagnostico"
                    busca.parar.set()
                return
 
            tem_vaga, resumo = interpretar_resposta(dados, busca.qtd, o, d, classe)
 
            if tem_vaga:
                log(f"{prefixo} >>> VAGA ENCONTRADA <<<")
                tratar_vaga(busca, trecho, classe, resumo)
                if busca.parar.is_set():
                    return
            else:
                # se havia vaga antes e sumiu, deixa de contar para o conjunto
                with busca.lock:
                    busca.disponivel.pop((nome, classe), None)
                log(f"{prefixo} {resumo}")
 
            busca.parar.wait(PAUSA_ENTRE_CONSULTAS)
 
        if falhou:
            espera = min(espera * 2, BACKOFF_MAXIMO)
            log(f"[{datetime.now():%H:%M:%S}]       {nome:<5} servidor instavel: aguardando {espera}s")
        else:
            espera = INTERVALO_SEGUNDOS
 
        busca.parar.wait(espera)  # acorda na hora se a busca for encerrada
 
 
# ----------------------------------------------------------------------
# ORQUESTRACAO
# ----------------------------------------------------------------------
def iniciar_monitoramento(busca):
    """Roda as threads e so retorna quando a busca terminar
    (vaga encontrada ou Ctrl+C)."""
 
    titulo_secao("BUSCA EM ANDAMENTO (Ctrl+C para interromper)")
    for nome, o, d, dt in busca.trechos:
        print(f"  {nome:<5}: {ESTACOES[o]} -> {ESTACOES[d]}  em {dt:%d/%m/%Y}")
    print(LINHA_SIMPLES)
    print("  Hora      Ciclo Trecho Data  Classe     | Situacao")
    print(LINHA_SIMPLES)
 
    threads = [
        threading.Thread(
            target=monitorar_trecho,
            args=(busca, trecho),
            name=f"Monitor-{trecho[0]}",
            daemon=True,
        )
        for trecho in busca.trechos
    ]
    for t in threads:
        t.start()
 
    try:
        while not busca.parar.wait(0.5):
            pass
    except KeyboardInterrupt:
        with busca.lock:
            if busca.motivo is None:
                busca.motivo = "interrompida"
            busca.parar.set()
        print("\nInterrompendo busca...")
 
    for t in threads:
        t.join(timeout=25)
 
    titulo_secao("BUSCA ENCERRADA")
    mensagens = {
        "unica": "Passagem encontrada.",
        "conjunto": "Ida e volta encontradas.",
        "interrompida": "Busca interrompida por voce.",
        "diagnostico": "Modo diagnostico concluido.",
    }
    print(f"  {mensagens.get(busca.motivo, 'Busca encerrada.')}")
 
 
def perguntar_nova_busca():
    print()
    while True:
        r = input("Deseja fazer uma nova busca? (S = nova busca / N = encerrar programa): ").strip().upper()
        if r in ("S", "SIM"):
            return True
        if r in ("N", "NAO"):
            return False
        print("Responda S ou N.")
 
 
def main():
    try:
        while True:
            trechos, classes, qtd, tipo = montar_trechos()
            busca = Busca(trechos, classes, qtd, tipo)
            iniciar_monitoramento(busca)
 
            if not perguntar_nova_busca():
                break
    except KeyboardInterrupt:
        print()
 
    print("\nPrograma encerrado.")
 
 
if __name__ == "__main__":
    main()
