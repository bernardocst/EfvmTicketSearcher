"""
Monitor de disponibilidade - Trem de Passageiros EFVM (Vale)
 
Uso:
    pip install requests
    python efvmTicketWatcher.py
 
O app pergunta estacao de origem/destino, data, tipo de viagem (so ida,
so volta ou ida e volta), classe e passageiros, e depois consulta a
disponibilidade a cada 30 segundos ate encontrar vaga.
 
O endpoint (pesquisaPassagem) e o payload foram copiados do proprio site.
"""
 
import json
import sys
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
INTERVALO_SEGUNDOS = 30           # intervalo entre consultas
PAUSA_ENTRE_CONSULTAS = 2          # segundos entre uma consulta e outra no mesmo ciclo
BACKOFF_MAXIMO = 600              # em erro, espera ate 10 min entre tentativas
 
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://tremdepassageiros.vale.com",
    "Referer": "https://tremdepassageiros.vale.com/sgpweb/portal/index.html",
    "User-Agent": "Mozilla/5.0 (monitor pessoal de disponibilidade)",
}
 
# ----------------------------------------------------------------------
# DADOS JA CONHECIDOS (obtidos das respostas que voce enviou)
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
# (suposicao minha: nao confirmei que Noite = true).
TREM_FERIAS = False
 
# Se True: faz UMA consulta, imprime a resposta completa e encerra.
MODO_DIAGNOSTICO = False
 
# O site manda a data como meia-noite de Brasilia em milissegundos
# (ex.: 09/10/2026 -> 1791514800000).
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
            return False, "sem passagens para a pesquisa"
        desc = (exc.get("descricao") or "").strip().replace("\n", " ")
        return False, f"aviso do servidor (tipo {exc.get('tipo')}): {desc[:200]}"
 
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
                f"  Trem {p.get('descricaoTrem')}  {dia}  "
                f"saida {p.get('horaPartidaPrevista')} -> chegada {p.get('horaChegadaPrevista')}  "
                f"{p.get('descricaoClasse')}  {valor}"
            )
        return True, "\n".join(linhas)
    if passagens:
        return False, "servidor devolveu so outro trecho (" + ", ".join(sorted(outros)) + "), ignorado"
    return False, "resposta sem passagens"
 
 
# ----------------------------------------------------------------------
# INTERFACE (menus)
# ----------------------------------------------------------------------
def escolher_de_lista(titulo, opcoes):
    """opcoes: dict id -> nome. Retorna o id escolhido."""
    itens = sorted(opcoes.items(), key=lambda kv: kv[1])
    print(f"\n{titulo}")
    for i, (_, nome) in enumerate(itens, 1):
        print(f"  {i:2d}) {nome}")
    while True:
        txt = input("Digite o numero: ").strip()
        if txt.isdigit() and 1 <= int(txt) <= len(itens):
            return itens[int(txt) - 1][0]
        print("Opcao invalida.")
 
 
def pedir_data(rotulo, minimo=None):
    hoje = date.today()
    primeiro = max(hoje + timedelta(days=1), minimo or hoje)
    ultimo = hoje + timedelta(days=DIAS_LIBERACAO_VENDA)
    print(f"\n{rotulo} (de {primeiro:%d/%m/%Y} ate {ultimo:%d/%m/%Y})")
    print("Obs.: nao ha venda para o mesmo dia da viagem.")
    while True:
        txt = input("Data (DD/MM/AAAA): ").strip()
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
 
 
def pedir_inteiro(rotulo, minimo, maximo):
    while True:
        txt = input(f"{rotulo} ({minimo}-{maximo}): ").strip()
        if txt.isdigit() and minimo <= int(txt) <= maximo:
            return int(txt)
        print("Valor invalido.")
 
 
def escolher_classes():
    """Devolve a lista de ids de classe a monitorar."""
    print("\nCLASSE:")
    print("  1) Economica")
    print("  2) Executiva")
    print("  3) Ambas (Economica + Executiva)")
    print("  4) Cadeirante")
    op = pedir_inteiro("Escolha", 1, 4)
    return {1: [43], 2: [44], 3: [43, 44], 4: [45]}[op]
 
 
def montar_trechos():
    """Pergunta tudo ao usuario e devolve a lista de trechos a monitorar."""
    print("=" * 60)
    print(" Monitor de disponibilidade - EFVM (Vale)")
    print("=" * 60)
 
    print("\nTipo de viagem:")
    print("  1) So ida")
    print("  2) Ida e volta")
    tipo = pedir_inteiro("Escolha", 1, 2)
 
    # Origem e destino sao perguntados uma unica vez.
    # Na volta, o sentido e invertido automaticamente (destino -> origem).
    origem = escolher_de_lista("ESTACAO DE ORIGEM (partida):", ESTACOES)
    restantes = {k: v for k, v in ESTACOES.items() if k != origem}
    destino = escolher_de_lista("ESTACAO DE DESTINO (chegada):", restantes)
 
    classes = escolher_classes()
    qtd = pedir_inteiro("Numero de passageiros", 1, 8)
 
    trechos = []
    d1 = pedir_data("Data da IDA")
    trechos.append(("IDA", origem, destino, d1))
    if tipo == 2:
        d2 = pedir_data("Data da VOLTA", minimo=d1)
        trechos.append(("VOLTA", destino, origem, d2))
 
    print("\n--- Resumo ---")
    for nome, o, d_, dt in trechos:
        print(f"{nome}: {ESTACOES[o]} -> {ESTACOES[d_]} em {dt:%d/%m/%Y}")
    print(f"Classe(s): {' + '.join(CLASSES[c] for c in classes)} | Passageiros: {qtd}")
    print(f"Consulta a cada {INTERVALO_SEGUNDOS}s. Ctrl+C para parar.")
    input("Aperte ENTER para iniciar... ")
    return trechos, classes, qtd
 
 
# ----------------------------------------------------------------------
# CONSULTA
# ----------------------------------------------------------------------
def consultar(sessao, trecho, classe, qtd):
    _, origem, destino, data_viagem = trecho
    payload = montar_payload(origem, destino, data_viagem, classe, qtd)
    resp = sessao.post(URL_DISPONIBILIDADE, json=payload, timeout=20)
    resp.raise_for_status()
    return resp.json()
 
 
def bipar(repeticoes=3):
    """Aviso sonoro suave: 3 toques espacados.
    No Windows usa o som padrao do sistema (bem mais agradavel que um bip puro)."""
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
 
 
def anunciar_vaga(trecho, classe, qtd, resumo):
    nome, origem, destino, data_viagem = trecho
    linha = "=" * 60
    print()
    print(linha)
    print("  PASSAGEM ENCONTRADA!")
    print(linha)
    print(f"  Trecho    : {nome} - {ESTACOES[origem]} -> {ESTACOES[destino]}")
    print(f"  Data      : {data_viagem:%d/%m/%Y}")
    print(f"  Classe    : {CLASSES[classe]}  |  Passageiros: {qtd}")
    print(f"  Encontrada: {datetime.now():%d/%m/%Y as %H:%M:%S}")
    print(linha)
    print("  Opcoes:")
    print(resumo)
    print(linha)
    print("  Corra para comprar:")
    print("  https://tremdepassageiros.vale.com/sgpweb/portal/index.html#/home")
    print(linha)
    print()
    bipar()
 
 
def main():
    trechos, classes, qtd = montar_trechos()
    sessao = requests.Session()
    sessao.headers.update(HEADERS)
 
    pendentes = list(trechos)
    espera = INTERVALO_SEGUNDOS
    tentativa = 0
 
    try:
        while pendentes:
            tentativa += 1
            falhou = False
 
            for trecho in list(pendentes):
                nome, o, d, dt = trecho
                achou = False
 
                for classe in classes:
                    agora = datetime.now().strftime("%H:%M:%S")
                    rotulo = (f"{nome} {ESTACOES[o]} -> {ESTACOES[d]} "
                              f"{dt:%d/%m} [{CLASSES[classe]}]")
                    try:
                        dados = consultar(sessao, trecho, classe, qtd)
                    except requests.HTTPError as e:
                        falhou = True
                        print(f"[{agora}] {rotulo}: erro HTTP {e.response.status_code}")
                        time.sleep(PAUSA_ENTRE_CONSULTAS)
                        continue
                    except (requests.RequestException, ValueError) as e:
                        falhou = True
                        print(f"[{agora}] {rotulo}: erro de rede/JSON: {e}")
                        time.sleep(PAUSA_ENTRE_CONSULTAS)
                        continue
 
                    if MODO_DIAGNOSTICO:
                        print("\n=== RESPOSTA COMPLETA ===")
                        print(json.dumps(dados, indent=2, ensure_ascii=False))
                        print("=== FIM ===")
                        print("Modo diagnostico: encerrando apos uma consulta.")
                        return
 
                    tem_vaga, resumo = interpretar_resposta(dados, qtd, o, d, classe)
                    if tem_vaga:
                        anunciar_vaga(trecho, classe, qtd, resumo)
                        achou = True
                    else:
                        print(f"[{agora}] #{tentativa} {rotulo}: {resumo}")
                    time.sleep(PAUSA_ENTRE_CONSULTAS)
 
                if achou:
                    pendentes.remove(trecho)
 
            if not pendentes:
                break
 
            if falhou:
                # servidor reclamando: espera cada vez mais (sem martelar o site)
                espera = min(espera * 2, BACKOFF_MAXIMO)
                print(f"Aguardando {espera}s antes de tentar de novo...")
            else:
                espera = INTERVALO_SEGUNDOS
            time.sleep(espera)
 
        print("\nTodos os trechos monitorados tiveram vaga. Encerrando.")
    except KeyboardInterrupt:
        print("\nMonitoramento interrompido.")
 
 
if __name__ == "__main__":
    main()
 