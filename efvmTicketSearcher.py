"""
Monitor de disponibilidade - Trem de Passageiros EFVM (Vale) [Versão Aprimorada]

Instalação (uma vez):
    pip install playwright
    (Se não tiver o Google Chrome instalado: playwright install chromium)

Uso:
    python efvmTicketSearcher.py
"""

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode


# ----------------------------------------------------------------------
# AJUSTES DE CONSOLE NO WINDOWS (UTF-8, TÍTULO E QUICKEDIT)
# ----------------------------------------------------------------------
def desabilitar_quickedit():
    """Desabilita o QuickEdit mode no Windows CMD para evitar que cliques pausem a execução."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        hStdin = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(hStdin, ctypes.byref(mode)):
            ENABLE_QUICK_EDIT_MODE = 0x0040
            ENABLE_EXTENDED_FLAGS = 0x0080
            new_mode = (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS
            kernel32.SetConsoleMode(hStdin, new_mode)
        kernel32.SetConsoleTitleW("EFVM Ticket Monitor - Trem de Passageiros (Vale)")
    except Exception:
        pass


try:
    if sys.platform == "win32":
        os.system("")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import winsound  # Windows
except ImportError:
    winsound = None

try:
    from playwright.sync_api import sync_playwright, Error as PlaywrightError
except ImportError:
    print("\n[!] Playwright não encontrado. Para instalar, execute:")
    print("    pip install playwright")
    print("    playwright install chromium\n")
    sys.exit(1)


# ----------------------------------------------------------------------
# ESTILOS E CORES ANSI
# ----------------------------------------------------------------------
class Cor:
    RESET = "\033[0m"
    NEGRITO = "\033[1m"
    DIM = "\033[2m"
    ITALICO = "\033[3m"
    SUBLINHADO = "\033[4m"

    VERDE = "\033[92m"
    VERDE_ESCURO = "\033[32m"
    AMARELO = "\033[93m"
    AZUL = "\033[94m"
    CIANO = "\033[96m"
    VERMELHO = "\033[91m"
    MAGENTA = "\033[95m"
    BRANCO = "\033[97m"
    CINZA = "\033[90m"


def c_str(texto, *estilos):
    """Aplica estilos ANSI se suportado."""
    return f"{''.join(estilos)}{texto}{Cor.RESET}"


# ----------------------------------------------------------------------
# CONFIGURAÇÕES GERAIS
# ----------------------------------------------------------------------
SITE = "https://tremdepassageiros.vale.com/"
API = "https://tremdepassageiros.vale.com/api/pv"
SIGLA_NORMATIVA = "EFVM"
ESTRADA_FERRO_ID = 2              # EFVM

DIAS_LIBERACAO_VENDA = 45         # usado só se a lista de datas do site falhar
MAX_PASSAGEIROS = 15              # quantidade máxima de passagens por CPF
INTERVALO_SEGUNDOS = 30           # intervalo entre ciclos de consulta
PAUSA_ENTRE_CONSULTAS = 2         # segundos entre consultas dentro do mesmo ciclo
PAUSA_ENTRE_VIAGENS = 0.5         # segundos entre chamadas de assentos
BACKOFF_MAXIMO = 600              # em erro de conexão, aguarda até 10 min
TIPO_PASSAGEM_NORMAL = 101        # Tarifa Normal
MARGEM_RENOVAR = 180              # renova o token quando faltar menos que 3 min

PERFIL_ANTIGO = Path(__file__).resolve().parent / "perfil_vale"

MODO_DIAGNOSTICO = False
TECLA_VOLTAR = "V"

LARGURA = 76
LINHA_TRILHO = "═" * LARGURA
LINHA_SIMPLES = "─" * LARGURA


# ----------------------------------------------------------------------
# ARTES ASCII & BANNERS VISUAIS
# ----------------------------------------------------------------------
BANNER_TREM = r"""
  ╔══════════════════════════════════════════════════════════════════════════════╗
  ║                                                                              ║
  ║        o O O                                                                 ║
  ║       o              ___________   ___________   ___________                 ║
  ║      o    _||_      |  EFVM 🚂  | | Passageiros| |  VALE 🎫  |               ║
  ║     [__||_||_||__]  |___________| |___________| |___________|                ║
  ║    ={____|  |____}  (o)(o) (o)(o) (o)(o) (o)(o) (o)(o) (o)(o)                ║
  ║  ══════════════════════════════════════════════════════════════════════════  ║
  ║      🚂 ESTRADA DE FERRO VITÓRIA A MINAS (EFVM) - MONITOR DE PASSAGENS       ║
  ║             Belo Horizonte ⇄ Vitória (Pedro Nolasco) | Linha Vale            ║
  ╚══════════════════════════════════════════════════════════════════════════════╝
"""


def banner_principal():
    print(c_str(BANNER_TREM, Cor.CIANO, Cor.NEGRITO))


def titulo_etapa(numero, total, titulo):
    print()
    barra = f"═[ 🚂 ETAPA {numero}/{total}: {titulo.upper()} ]"
    resto = LARGURA - len(barra)
    if resto > 0:
        barra += "═" * resto
    print(c_str(barra, Cor.CIANO, Cor.NEGRITO))


def subtitulo(texto):
    print(c_str(f"\n─── {texto} " + "─" * max(2, LARGURA - len(texto) - 6), Cor.CINZA))


# ----------------------------------------------------------------------
# DADOS DE ESTAÇÕES E CLASSES
# ----------------------------------------------------------------------
ESTACOES_PADRAO = {
    16: "Pedro Nolasco",
    17: "Flexal",
    18: "Fundao",
    19: "Aricanga",
    20: "Piraqueacu",
    21: "Colatina",
    22: "Itapina",
    23: "Mascarenhas",
    24: "Baixo Guandu",
    25: "Aimores",
    26: "Resplendor",
    27: "Krenak",
    28: "Conselheiro Pena",
    29: "Barra do Cuiete",
    30: "Sao Tome do Rio Doce",
    31: "Tumiritinga",
    32: "Governador Valadares",
    33: "Pedra Corrida",
    34: "Periquito",
    35: "Frederico Sellow",
    36: "Ipaba",
    37: "Intendente Camara",
    38: "Mario Carvalho",
    39: "Antonio Dias",
    40: "Desembargador Drumond",
    41: "Joao Monlevade",
    42: "Rio Piracicaba",
    43: "Dois Irmaos",
    44: "Belo Horizonte",
    45: "Itabira",
}

CLASSES = {
    1: "Executivo",
    2: "Economico",
    3: "Cadeirante",
}

ESTACOES = dict(ESTACOES_PADRAO)


# ----------------------------------------------------------------------
# UTILITÁRIOS GERAIS
# ----------------------------------------------------------------------
def sem_acentos(txt):
    return "".join(
        c for c in unicodedata.normalize("NFKD", str(txt)) if not unicodedata.combining(c)
    )


def log(msg=""):
    print(msg, flush=True)


def hora():
    return datetime.now().strftime("%H:%M:%S")


def apito_de_trem(repeticoes=3):
    """Alerta sonoro com ritmo que simula o apito de uma locomotiva."""
    for _ in range(repeticoes):
        if winsound:
            try:
                winsound.Beep(587, 350)  # D5
                time.sleep(0.08)
                winsound.Beep(587, 500)  # D5
                time.sleep(0.2)
                winsound.Beep(440, 600)  # A4
            except Exception:
                try:
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                except Exception:
                    pass
        else:
            print("\a", end="", flush=True)
        time.sleep(1.2)


def jwt_exp(token):
    """Lê o timestamp 'exp' do payload JWT sem checar assinatura."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        dados = json.loads(base64.urlsafe_b64decode(payload))
        return float(dados.get("exp", time.time() + 3600))
    except Exception:
        return time.time() + 3600


class ErroApi(Exception):
    pass


JS_FETCH = """async ([metodo, url, corpo, cab]) => {
    const h = {
        "authorization": cab["authorization"],
        "x-sigla-normativa": cab["x-sigla-normativa"],
        "x-origem-requisicao": cab["x-origem-requisicao"],
        "accept": cab["accept"],
    };
    const opts = {method: metodo, headers: h, credentials: "include"};
    if (corpo !== null && corpo !== undefined) {
        h["content-type"] = "application/json";
        opts.body = JSON.stringify(corpo);
    }
    const r = await fetch(url, opts);
    return {status: r.status, texto: await r.text()};
}"""


# ----------------------------------------------------------------------
# GERENCIAMENTO DE SESSÃO & NAVEGADOR
# ----------------------------------------------------------------------
class Sessao:
    """
    Gerencia a autenticação visual automática e a execução das buscas em segundo plano.
    O login abre a janela visível; após o usuário logar, a janela fecha sozinha.
    Todas as buscas seguintes rodam em modo headless invisível, protegidas contra 403.
    """

    def __init__(self, pw):
        self.pw = pw
        self.token = None
        self.token_exp = 0.0
        self.captura_ts = 0.0
        self.datas = None
        self.browser = None
        self.ctx = None
        self.page = None

    def _abrir_navegador(self, headless=True, storage_state=None):
        """Abre uma instância do Chromium (visível ou invisível)."""
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-default-browser-check",
            "--disable-infobars",
        ]
        ultimo_erro = None
        for canal in ("chrome", None):
            try:
                kw = dict(headless=headless, args=launch_args)
                if canal:
                    kw["channel"] = canal
                self.browser = self.pw.chromium.launch(**kw)
                break
            except PlaywrightError as e:
                ultimo_erro = e
        else:
            log(c_str("\n[!] Não foi possível abrir o Chromium.", Cor.VERMELHO, Cor.NEGRITO))
            log("    Instale o Google Chrome ou execute: playwright install chromium")
            if ultimo_erro:
                log(f"    Detalhes: {str(ultimo_erro).splitlines()[0]}")
            sys.exit(1)

        ctx_kwargs = dict(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            locale="pt-BR",
            viewport={"width": 1280, "height": 720},
        )
        if storage_state:
            ctx_kwargs["storage_state"] = storage_state

        self.ctx = self.browser.new_context(**ctx_kwargs)
        self.ctx.on("request", self._on_request)

        self.page = self.ctx.new_page()
        try:
            self.page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
        except Exception:
            pass

    def _fechar_navegador(self):
        """Fecha navegador e contexto em execução."""
        for obj in (self.ctx, self.browser):
            try:
                if obj:
                    obj.close()
            except Exception:
                pass
        self.ctx = self.browser = self.page = None

    def fechar(self):
        self._fechar_navegador()
        self.token = None
        self.token_exp = 0.0

    # -- Captura de token de autorização -------------------------------
    def _on_request(self, req):
        try:
            if "/api/pv/" not in req.url:
                return
            auth = req.headers.get("authorization", "")
            if not auth.lower().startswith("bearer "):
                return
            tok = auth[7:].strip()
            exp = jwt_exp(tok)
            # Prioriza tokens com maior validade e obtidos diretamente do cabeçalho
            if exp >= self.token_exp or (self.token_exp - time.time() < 60):
                self.token = tok
                self.token_exp = exp
                self.captura_ts = time.time()
        except Exception:
            pass

    def _capturar_token_storage(self):
        """
        Extrai especificamente o AccessToken do MSAL (Azure B2C).
        Evita pegar o IdToken por engano, prevenindo o erro HTTP 403.
        """
        if not self.page:
            return False
        try:
            tok = self.page.evaluate("""() => {
                try {
                    // 1. Procura estritamente por AccessToken no localStorage do MSAL
                    for (let i = 0; i < localStorage.length; i++) {
                        const k = (localStorage.key(i) || "").toLowerCase();
                        const v = localStorage.getItem(localStorage.key(i)) || "";
                        if (k.includes("accesstoken") || v.includes("AccessToken")) {
                            try {
                                const parsed = JSON.parse(v);
                                if (parsed.credentialType === "AccessToken" && parsed.secret) {
                                    return parsed.secret;
                                }
                                if (parsed.secret && k.includes("accesstoken")) {
                                    return parsed.secret;
                                }
                            } catch(e) {}
                        }
                    }
                    // 2. Procura em sessionStorage
                    for (let i = 0; i < sessionStorage.length; i++) {
                        const k = (sessionStorage.key(i) || "").toLowerCase();
                        const v = sessionStorage.getItem(sessionStorage.key(i)) || "";
                        if (k.includes("accesstoken")) {
                            try {
                                const parsed = JSON.parse(v);
                                if (parsed.secret) return parsed.secret;
                            } catch(e) {}
                        }
                    }
                } catch(e) {}
                return null;
            }""")
            if tok and isinstance(tok, str) and tok.startswith("eyJ"):
                exp = jwt_exp(tok)
                if exp > time.time() and exp >= self.token_exp:
                    self.token = tok
                    self.token_exp = exp
                    self.captura_ts = time.time()
                    return True
        except Exception:
            pass
        return False

    def token_valido(self, margem=MARGEM_RENOVAR):
        if not self.token:
            self._capturar_token_storage()
        return bool(self.token) and (self.token_exp - time.time()) > margem

    def bombear(self, segundos):
        fim = time.time() + segundos
        while True:
            restante = fim - time.time()
            if restante <= 0:
                return
            try:
                self.page.wait_for_timeout(int(min(1.0, restante) * 1000))
            except Exception:
                time.sleep(min(1.0, restante))

    # -- Fluxo de Login Visual com Fechamento Automático ---------------
    def login_visual_automatico(self):
        """
        Abre a página da Vale em janela visível para o usuário fazer o login.
        Assim que o login é concluído, fecha a janela automaticamente
        e migra a sessão autenticada para o modo headless invisível.
        """
        print()
        print(c_str("═" * LARGURA, Cor.CIANO))
        print(c_str("  🔒 LOGIN NO SISTEMA DE VENDAS DA VALE", Cor.BRANCO, Cor.NEGRITO))
        print(c_str("═" * LARGURA, Cor.CIANO))
        print(c_str("  [+] Abrindo a janela do navegador...", Cor.AMARELO, Cor.NEGRITO))
        print(c_str("  [+] Faça seu login normalmente na janela que abriu.", Cor.BRANCO))
        print(c_str("  [+] Assim que você entrar, a janela fechará AUTOMATICAMENTE!", Cor.VERDE, Cor.NEGRITO))
        print(c_str("═" * LARGURA, Cor.CIANO))

        self._fechar_navegador()
        self._abrir_navegador(headless=False)

        try:
            self.page.goto(SITE, wait_until="domcontentloaded", timeout=60000)
            self.page.wait_for_timeout(2000)

            # Clica no botão 'Entrar' automaticamente para já exibir os campos de login
            try:
                for seletor in [
                    'text=/^\\s*(entrar|login|acessar)\\s*$/i',
                    'a:has-text("Entrar")',
                    'button:has-text("Entrar")',
                    '[aria-label*="Entrar" i]',
                ]:
                    el = self.page.locator(seletor).first
                    if el.is_visible():
                        el.click(timeout=3000)
                        break
            except Exception:
                pass
        except PlaywrightError as e:
            log(c_str(f"  [!] Aviso na navegação inicial: {str(e).splitlines()[0]}", Cor.CINZA))

        print(c_str("\n  ⏳ Aguardando você concluir o login no navegador...", Cor.CIANO))

        # Monitora ativamente o momento em que o login é efetuado
        t0 = time.time()
        timeout_max = 300  # até 5 minutos para o usuário logar
        login_concluido = False

        while time.time() - t0 < timeout_max:
            # 1. Verifica se capturou access token do storage ou de requisições de API
            if self._capturar_token_storage() or (self.token and self.token_valido(30)):
                login_concluido = True
                break

            # 2. Se a URL voltou para o site oficial (fora do b2clogin)
            try:
                url_atual = self.page.url.lower()
                if "tremdepassageiros.vale.com" in url_atual and "b2clogin" not in url_atual:
                    # Dispara uma chamada leve interna para forçar o aplicativo a anexar o token
                    self.page.evaluate("() => fetch('/api/pv/viagens/datas', {credentials: 'include'}).catch(() => {})")
                    self.bombear(1.0)
                    if self._capturar_token_storage() or (self.token and self.token_valido(30)):
                        login_concluido = True
                        break
            except Exception:
                pass

            self.bombear(1.0)

        if not login_concluido or not self.token:
            log(c_str("\n  [!] Tempo esgotado ou login não concluído. Encerrando.", Cor.VERMELHO))
            self.fechar()
            sys.exit(1)

        # Salva o estado dos cookies e tokens autenticados
        estado_sessao = self.ctx.storage_state()

        # Fecha a janela visível AUTOMATICAMENTE
        self._fechar_navegador()

        print(c_str("\n  ✅ Login concluído com sucesso!", Cor.VERDE, Cor.NEGRITO))
        print(c_str("  🚪 Janela do navegador fechada automaticamente.", Cor.CIANO))
        print(c_str("  🕶️  Iniciando buscas em segundo plano (modo silencioso)...\n", Cor.CINZA))

        # Abre o navegador headless em segundo plano com a mesma sessão autenticada
        self._abrir_navegador(headless=True, storage_state=estado_sessao)

        # Valida o token com uma consulta de teste
        try:
            self.page.goto(SITE, wait_until="domcontentloaded", timeout=45000)
            self._garantir_token_valido()
        except Exception:
            pass

    def _garantir_token_valido(self):
        """Garante que temos o token Bearer válido fazendo chamada direta no contexto da página."""
        if self.token and self.token_valido(60):
            return True
        try:
            self._capturar_token_storage()
            if not self.token or not self.token_valido(60):
                self.page.evaluate("() => fetch('/api/pv/viagens/datas', {credentials: 'include'}).catch(() => {})")
                self.bombear(1.5)
                self._capturar_token_storage()
        except Exception:
            pass
        return bool(self.token)

    # -- Chamadas HTTP à API Oficial -----------------------------------
    def _cabecalhos(self):
        return {
            "authorization": "Bearer " + (self.token or ""),
            "x-sigla-normativa": SIGLA_NORMATIVA,
            "x-origem-requisicao": "vendas",
            "origin": SITE.rstrip("/"),
            "referer": SITE,
            "accept": "application/json, text/plain, */*",
        }

    def chamar(self, metodo, caminho, corpo=None, params=None):
        """
        Executa chamadas HTTP seguras dentro do contexto da página.
        Se ocorrer 401/403, renova a sessão automaticamente.
        """
        for tentativa in (1, 2):
            self._garantir_token_valido()

            url = API + caminho
            if params:
                url += "?" + urlencode(params)

            try:
                if not self.page or self.page.is_closed():
                    self._abrir_navegador(headless=True)
                    self.page.goto(SITE, wait_until="domcontentloaded", timeout=45000)

                res = self.page.evaluate(JS_FETCH, [metodo, url, corpo, self._cabecalhos()])
            except PlaywrightError as e:
                msg = str(e).splitlines()[0] if str(e) else "erro"
                raise ErroApi(f"Falha de comunicação: {msg}")

            status = res.get("status")
            texto = res.get("texto") or ""

            # Se der 401 ou 403 na primeira tentativa, tenta revalidar o token e tentar de novo
            if status in (401, 403) and tentativa == 1:
                self.token_exp = 0.0
                try:
                    self.page.evaluate("() => fetch('/api/pv/viagens/datas', {credentials: 'include'}).catch(() => {})")
                    self.bombear(2.0)
                    self._capturar_token_storage()
                except Exception:
                    pass
                continue

            if status != 200:
                trecho = " ".join(texto.split())[:150]
                raise ErroApi(f"HTTP {status} {trecho}")

            try:
                return json.loads(texto)
            except Exception:
                raise ErroApi("Resposta da Vale não está em formato JSON válido")

        raise ErroApi("Acesso não autorizado após renovação")

    def carregar_dados_site(self):
        """Atualiza catálogo de estações e datas liberadas pelo site."""
        global ESTACOES
        try:
            dados = self.chamar("GET", f"/estacao/estrada-ferro/{ESTRADA_FERRO_ID}")
            lista = dados.get("content") if isinstance(dados, dict) else dados
            novas = {
                int(e["id"]): sem_acentos(e["nome"])
                for e in (lista or [])
                if e.get("id") is not None and e.get("nome")
            }
            if len(novas) >= 5:
                ESTACOES = novas
        except Exception:
            pass

        try:
            dados = self.chamar("GET", "/viagens/datas")
            lista = dados.get("content") if isinstance(dados, dict) else dados
            datas = {date(int(x["ano"]), int(x["mes"]), int(x["dia"])) for x in (lista or [])}
            self.datas = datas or None
        except Exception:
            self.datas = None


# ----------------------------------------------------------------------
# INTERFACE INTERATIVA COM O USUÁRIO
# ----------------------------------------------------------------------
def mostrar_selecao(dados):
    partes = []
    if dados.get("tipo"):
        tipo_str = "Somente Ida" if dados["tipo"] == 1 else "Ida e Volta"
        partes.append(f"Modalidade : {c_str(tipo_str, Cor.BRANCO, Cor.NEGRITO)}")
    if dados.get("origem"):
        partes.append(f"Origem     : {c_str(ESTACOES[dados['origem']], Cor.VERDE, Cor.NEGRITO)}")
    if dados.get("destino"):
        partes.append(f"Destino    : {c_str(ESTACOES[dados['destino']], Cor.VERDE, Cor.NEGRITO)}")
    if dados.get("classes"):
        desc = " + ".join(CLASSES[c] for c in dados["classes"])
        partes.append(f"Classe(s)  : {c_str(desc, Cor.AMARELO, Cor.NEGRITO)}")
    if dados.get("qtd"):
        partes.append(f"Passageiros: {c_str(str(dados['qtd']), Cor.BRANCO, Cor.NEGRITO)}")
    if dados.get("d1"):
        d1_fmt = dados["d1"].strftime("%d/%m/%Y")
        partes.append(f"Data Ida   : {c_str(d1_fmt, Cor.CIANO, Cor.NEGRITO)}")
    if dados.get("d2"):
        d2_fmt = dados["d2"].strftime("%d/%m/%Y")
        partes.append(f"Data Volta : {c_str(d2_fmt, Cor.CIANO, Cor.NEGRITO)}")

    if partes:
        print(c_str("\n  ┌─ Dados selecionados até agora ─────────────────────────────", Cor.CINZA))
        for p in partes:
            print(f"  │  {p}")
        print(c_str("  └────────────────────────────────────────────────────────────", Cor.CINZA))


def escolher_estacao(titulo, opcoes):
    itens = sorted(opcoes.items(), key=lambda kv: sem_acentos(kv[1]).lower())
    subtitulo(titulo)

    metade = (len(itens) + 1) // 2
    for i in range(metade):
        col1 = f"  [{i+1:2d}] {itens[i][1]:<24}"
        col2 = ""
        if i + metade < len(itens):
            col2 = f" [{i+metade+1:2d}] {itens[i+metade][1]}"
        print(c_str(col1, Cor.BRANCO) + c_str(col2, Cor.BRANCO))

    print(c_str(f"\n  [{TECLA_VOLTAR}] ↩️  Voltar à etapa anterior", Cor.AMARELO, Cor.NEGRITO))

    while True:
        txt = input(c_str("\n  Digite o número da estação: ", Cor.CIANO, Cor.NEGRITO)).strip()
        if txt.upper() == TECLA_VOLTAR:
            return None
        if txt.isdigit() and 1 <= int(txt) <= len(itens):
            return itens[int(txt) - 1][0]
        print(c_str("  [!] Opção inválida. Digite o número correspondente à estação.", Cor.VERMELHO))


def pedir_data(rotulo, datas, minimo=None):
    hoje = date.today()
    base = max(hoje, minimo or hoje)
    if datas:
        validas = sorted(d for d in datas if d >= base)
        if not validas:
            print(c_str(f"  [!] Não há datas liberadas a partir de {base:%d/%m/%Y}.", Cor.VERMELHO))
            return None
        primeiro, ultimo = validas[0], validas[-1]
    else:
        primeiro, ultimo = base, hoje + timedelta(days=DIAS_LIBERACAO_VENDA)

    subtitulo(rotulo.upper())
    print(c_str(f"  • Intervalo aceito : {primeiro:%d/%m/%Y} até {ultimo:%d/%m/%Y}", Cor.CINZA))
    print(c_str(f"  • Pressione [{TECLA_VOLTAR}] para voltar", Cor.CINZA))

    while True:
        txt = input(c_str(f"  📅 Data da {rotulo} (DD/MM/AAAA): ", Cor.CIANO, Cor.NEGRITO)).strip()
        if txt.upper() == TECLA_VOLTAR:
            return None
        try:
            d = datetime.strptime(txt, "%d/%m/%Y").date()
        except ValueError:
            print(c_str("  [!] Formato inválido. Digite no formato DD/MM/AAAA (ex: 25/12/2026).", Cor.VERMELHO))
            continue
        if d < primeiro:
            print(c_str(f"  [!] A data deve ser a partir de {primeiro:%d/%m/%Y}.", Cor.VERMELHO))
        elif d > ultimo:
            print(c_str(f"  [!] A venda no site só está aberta até {ultimo:%d/%m/%Y}.", Cor.VERMELHO))
        elif datas and d not in datas:
            print(c_str("  [!] Essa data específica não consta como liberada no calendário do site.", Cor.VERMELHO))
        else:
            return d


def pedir_inteiro(rotulo, minimo, maximo, permitir_voltar=True):
    sufixo = f", ou [{TECLA_VOLTAR}] para voltar" if permitir_voltar else ""
    while True:
        txt = input(c_str(f"  {rotulo} ({minimo}-{maximo}{sufixo}): ", Cor.CIANO, Cor.NEGRITO)).strip()
        if permitir_voltar and txt.upper() == TECLA_VOLTAR:
            return None
        if txt.isdigit() and minimo <= int(txt) <= maximo:
            return int(txt)
        print(c_str(f"  [!] Valor inválido. Digite um número entre {minimo} e {maximo}.", Cor.VERMELHO))


def escolher_classes():
    subtitulo("SELEÇÃO DE CLASSE")
    print(c_str("  [1] 💺 Econômico", Cor.BRANCO))
    print(c_str("  [2] 🛋️  Executivo", Cor.BRANCO))
    print(c_str("  [3] ✨ Ambas (Econômico ou Executivo)", Cor.BRANCO))
    print(c_str("  [4] ♿ Cadeirante", Cor.BRANCO))
    print(c_str(f"  [{TECLA_VOLTAR}] ↩️  Voltar", Cor.AMARELO, Cor.NEGRITO))

    while True:
        txt = input(c_str("\n  Escolha a classe desejada: ", Cor.CIANO, Cor.NEGRITO)).strip()
        if txt.upper() == TECLA_VOLTAR:
            return None
        if txt.isdigit() and 1 <= int(txt) <= 4:
            return {1: [2], 2: [1], 3: [2, 1], 4: [3]}[int(txt)]
        print(c_str("  [!] Opção inválida. Escolha de 1 a 4.", Cor.VERMELHO))


def exibir_cartao_resumo(trechos, classes, qtd, tipo):
    print()
    print(c_str("  ╔══════════════════════════════════════════════════════════════════════╗", Cor.VERDE, Cor.NEGRITO))
    print(c_str("  ║ 🎫 BILHETE DE MONITORAMENTO - ESTRADA DE FERRO VITÓRIA A MINAS       ║", Cor.VERDE, Cor.NEGRITO))
    print(c_str("  ╠══════════════════════════════════════════════════════════════════════╣", Cor.VERDE))
    for nome, org, dst, dt in trechos:
        icone = "🚂 IDA  " if nome == "IDA" else "🔄 VOLTA"
        linha = f"  ║  {icone}: {ESTACOES[org]} ➔ {ESTACOES[dst]} em {dt:%d/%m/%Y}"
        print(c_str(f"{linha:<73}║", Cor.BRANCO, Cor.NEGRITO))

    desc_classes = " + ".join(CLASSES[c] for c in classes)
    print(c_str(f"  ║  💺 Classe(s)   : {desc_classes:<51}║", Cor.BRANCO))
    print(c_str(f"  ║  👥 Passageiros : {qtd:<51}║", Cor.BRANCO))
    print(c_str(f"  ║  ⏱️  Frequência  : A cada {INTERVALO_SEGUNDOS} segundos{' '*34}║", Cor.BRANCO))
    print(c_str("  ╠══════════════════════════════════════════════════════════════════════╣", Cor.VERDE))
    if tipo == 2:
        print(c_str("  ║  🔔 Avisos: Vagas individuais emitem alerta e a busca continua;      ║", Cor.CINZA))
        print(c_str("  ║             Ida e Volta simultâneas alertam e encerram a busca.       ║", Cor.CINZA))
    else:
        print(c_str("  ║  🔔 Avisos: Ao encontrar vagas para o trecho, a busca é encerrada.    ║", Cor.CINZA))
    print(c_str("  ╚══════════════════════════════════════════════════════════════════════╝", Cor.VERDE, Cor.NEGRITO))


def montar_trechos(sessao):
    banner_principal()

    dados = {}
    etapa = 0

    while True:

        # ETAPA 0 - TIPO DE VIAGEM
        if etapa == 0:
            titulo_etapa(1, 6, "Tipo de Viagem")
            print(c_str("  [1] 🎫 Somente Ida", Cor.BRANCO))
            print(c_str("  [2] 🔄 Ida e Volta", Cor.BRANCO))
            tipo = pedir_inteiro("Escolha", 1, 2, permitir_voltar=False)
            dados["tipo"] = tipo
            if tipo == 1:
                dados["d2"] = None
            etapa = 1
            continue

        # ETAPA 1 - ORIGEM
        if etapa == 1:
            mostrar_selecao(dados)
            titulo_etapa(2, 6, "Estação de Origem (Partida)")
            origem = escolher_estacao("Selecione de onde você partirá", ESTACOES)
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
            titulo_etapa(3, 6, "Estação de Destino (Chegada)")
            restantes = {k: v for k, v in ESTACOES.items() if k != dados["origem"]}
            destino = escolher_estacao("Selecione para onde você viajará", restantes)
            if destino is None:
                etapa = 1
                continue
            dados["destino"] = destino
            etapa = 3
            continue

        # ETAPA 3 - CLASSE
        if etapa == 3:
            mostrar_selecao(dados)
            titulo_etapa(4, 6, "Classe Desejada")
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
            titulo_etapa(5, 6, "Quantidade de Passageiros")
            qtd = pedir_inteiro("Número de assentos desejados", 1, MAX_PASSAGEIROS)
            if qtd is None:
                etapa = 3
                continue
            dados["qtd"] = qtd
            etapa = 5
            continue

        # ETAPA 5 - DATA DA IDA
        if etapa == 5:
            mostrar_selecao(dados)
            titulo_etapa(6, 6, "Data da Viagem")
            d1 = pedir_data("Ida", sessao.datas)
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
            subtitulo("DATA DE RETORNO")
            d2 = pedir_data("Volta", sessao.datas, minimo=dados["d1"])
            if d2 is None:
                etapa = 5
                continue
            dados["d2"] = d2
            etapa = 7
            continue

        # ETAPA 7 - CONFIRMAÇÃO
        if etapa == 7:
            o, d = dados["origem"], dados["destino"]
            trechos = [("IDA", o, d, dados["d1"])]
            if dados["tipo"] == 2:
                trechos.append(("VOLTA", d, o, dados["d2"]))

            exibir_cartao_resumo(trechos, dados["classes"], dados["qtd"], dados["tipo"])

            print(c_str(f"\n  [ENTER] ", Cor.VERDE, Cor.NEGRITO) + "Iniciar monitoramento contínuo")
            print(c_str(f"  [{TECLA_VOLTAR}]     ", Cor.AMARELO, Cor.NEGRITO) + "Voltar e corrigir dados")
            print(c_str(f"  [Ctrl+C] ", Cor.VERMELHO, Cor.NEGRITO) + "Sair do programa")

            confirmacao = input(c_str("\n  Opção: ", Cor.CIANO, Cor.NEGRITO)).strip()
            if confirmacao.upper() == TECLA_VOLTAR:
                etapa = 6 if dados["tipo"] == 2 else 5
                continue

            return trechos, dados["classes"], dados["qtd"], dados["tipo"]


# ----------------------------------------------------------------------
# CONSULTA DE ASSENTOS E DISPONIBILIDADE
# ----------------------------------------------------------------------
def _get(d, *chaves):
    for c in chaves:
        if not isinstance(d, dict):
            return None
        d = d.get(c)
    return d


def assentos_da_viagem(sessao, viagem_id, origem, destino, qtd):
    dados = sessao.chamar(
        "GET", "/assentos/carros-ocupados",
        params={
            "idaOuVolta": "ida",
            "viagemId": viagem_id,
            "quantidadePassagens": qtd,
            "estacaoOrigemId": origem,
            "estacaoDestinoId": destino,
            "tipoPassagemId": TIPO_PASSAGEM_NORMAL,
        },
    )
    itens = dados if isinstance(dados, list) else [dados]
    disp, resumo = {}, []
    for item in itens:
        if not isinstance(item, dict):
            continue
        if item.get("viagemId") not in (None, viagem_id):
            continue
        for carro in item.get("carros") or []:
            cid = carro.get("classeId")
            livres = carro.get("assentosDisponiveis") or 0
            disp[cid] = disp.get(cid, 0) + livres
            resumo.append((carro.get("carroPlaca"), cid, livres, carro.get("totalAssentos")))
    return disp, resumo


def consultar_trecho(sessao, trecho, qtd):
    _, origem, destino, dt = trecho
    dados = sessao.chamar(
        "POST", "/viagens/buscar-viagens-disponiveis",
        corpo={
            "idaOuVolta": "ida",
            "origemId": origem,
            "destinoId": destino,
            "data": dt.isoformat(),
        },
    )
    conteudo = dados.get("content") if isinstance(dados, dict) else dados
    viagens = []
    for v in conteudo or []:
        vid = v.get("id")
        if vid is None:
            continue
        disp, carros = assentos_da_viagem(sessao, vid, origem, destino, qtd)
        viagens.append({
            "id": vid,
            "trem": _get(v, "os", "prefixo", "prefixo") or "?",
            "data": (v.get("data") or "").replace("-", "/"),
            "partida": v.get("partida") or "--:--",
            "chegada": v.get("chegada") or "--:--",
            "disp": disp,
            "carros": carros,
        })
        sessao.bombear(PAUSA_ENTRE_VIAGENS)
    return viagens


def linha_viagem(v, classe):
    n = v["disp"].get(classe, 0)
    return (
        f"    🚂 Trem {v['trem']} ({v['data']}) | Partida: {v['partida']} ➔ Chegada: {v['chegada']} | "
        f"{CLASSES[classe]}: {n} vaga(s) disponível(is)"
    )


def resumo_sem_vaga(viagens, classe, qtd):
    if not viagens:
        return "Sem viagens programadas"
    maior = max(v["disp"].get(classe, 0) for v in viagens)
    if maior == 0:
        return f"{len(viagens)} viagem(ns) no dia, sem vagas livres"
    return f"{len(viagens)} viagem(ns), máx {maior} vaga(s) encontrada(s) (necessário: {qtd})"


# ----------------------------------------------------------------------
# ANÚNCIO DE VAGAS ENCONTRADAS
# ----------------------------------------------------------------------
def anunciar_vaga(sessao, titulo, itens, qtd, rodape=None):
    print()
    print(c_str("╔══════════════════════════════════════════════════════════════════════════╗", Cor.VERDE, Cor.NEGRITO))
    print(c_str(f"║  🎉 🎉 🎉   {titulo.center(56)}   🎉 🎉 🎉  ║", Cor.VERDE, Cor.NEGRITO))
    print(c_str("╠══════════════════════════════════════════════════════════════════════════╣", Cor.VERDE))
    for trecho, classe, linhas in itens:
        nome, origem, destino, data_viagem = trecho
        print(c_str(f"║  📍 Trecho: {ESTACOES[origem]} ➔ {ESTACOES[destino]}", Cor.BRANCO, Cor.NEGRITO))
        print(c_str(f"║  📅 Data  : {data_viagem:%d/%m/%Y} | {CLASSES[classe]} | {qtd} passageiro(s)", Cor.BRANCO))
        print(c_str("║  " + "─" * 68, Cor.CINZA))
        for linha in linhas:
            print(c_str(f"║  {linha.strip()}", Cor.AMARELO, Cor.NEGRITO))
        print(c_str("║  " + "─" * 68, Cor.CINZA))

    print(c_str(f"║  🕒 Identificado em: {datetime.now():%d/%m/%Y às %H:%M:%S}", Cor.CINZA))
    if rodape:
        print(c_str(f"║  ⚠️  {rodape}", Cor.AMARELO))
    print(c_str(f"║  🛒 Acesse IMEDIATAMENTE para comprar: {SITE}", Cor.CIANO, Cor.NEGRITO))
    print(c_str("╚══════════════════════════════════════════════════════════════════════════╝", Cor.VERDE, Cor.NEGRITO))
    apito_de_trem()


# ----------------------------------------------------------------------
# EXECUÇÃO DO MONITORAMENTO
# ----------------------------------------------------------------------
def executar_busca(sessao, trechos, classes, qtd, tipo):
    por_nome = {t[0]: t for t in trechos}
    disponivel = {}

    print()
    print(c_str("╔══════════════════════════════════════════════════════════════════════════╗", Cor.CIANO, Cor.NEGRITO))
    print(c_str("║ 🚂 MONITORAMENTO ATIVO - Pressione Ctrl+C a qualquer momento para pausar║", Cor.CIANO, Cor.NEGRITO))
    print(c_str("╚══════════════════════════════════════════════════════════════════════════╝", Cor.CIANO, Cor.NEGRITO))

    for nome, o, d, dt in trechos:
        print(c_str(f"  • {nome:<5}: {ESTACOES[o]} ➔ {ESTACOES[d]} em {dt:%d/%m/%Y}", Cor.BRANCO))
    print(c_str("─" * LARGURA, Cor.CINZA))
    print(c_str("  Hora      Ciclo   Trecho   Data    Classe     │ Situação", Cor.CINZA))
    print(c_str("─" * LARGURA, Cor.CINZA))

    def tratar_vaga(trecho, classe, linhas):
        nome = trecho[0]
        novo = (nome, classe) not in disponivel
        disponivel[(nome, classe)] = linhas

        if tipo == 1:
            anunciar_vaga(sessao, "PASSAGEM ENCONTRADA!", [(trecho, classe, linhas)], qtd)
            return "unica"

        tem_ida = any(k[0] == "IDA" for k in disponivel)
        tem_volta = any(k[0] == "VOLTA" for k in disponivel)
        if tem_ida and tem_volta:
            itens = [(por_nome[n], c, l) for (n, c), l in sorted(disponivel.items())]
            anunciar_vaga(sessao, "IDA E VOLTA DISPONÍVEIS!", itens, qtd)
            return "conjunto"

        if novo:
            faltando = "VOLTA" if nome == "IDA" else "IDA"
            anunciar_vaga(
                sessao,
                f"VAGA INDIVIDUAL ({nome})",
                [(trecho, classe, linhas)],
                qtd,
                rodape=f"Ainda monitorando a {faltando} para fechar o conjunto de ida e volta.",
            )
        return None

    ciclo = 0
    espera = INTERVALO_SEGUNDOS

    try:
        while True:
            ciclo += 1
            falhou = False

            for trecho in trechos:
                nome, o, d, dt = trecho
                try:
                    viagens = consultar_trecho(sessao, trecho, qtd)
                except ErroApi as e:
                    falhou = True
                    log(c_str(f"  [{hora()}] #{ciclo:03d}   {nome:<6}  {dt:%d/%m}   Erro: {e}", Cor.VERMELHO))
                    sessao.bombear(PAUSA_ENTRE_CONSULTAS)
                    continue

                if MODO_DIAGNOSTICO:
                    print("\n=== DIAGNÓSTICO ===")
                    for v in viagens:
                        print(f"Viagem {v['id']} - trem {v['trem']} {v['data']} {v['partida']} -> {v['chegada']}")
                        for placa, cid, livres, total in v["carros"]:
                            print(f"   carro {placa}: {CLASSES.get(cid, cid)} {livres}/{total} livres")
                    print("=== FIM DIAGNÓSTICO ===")
                    return "diagnostico"

                for classe in classes:
                    prefixo = f"  [{hora()}] #{ciclo:03d}   {nome:<6}  {dt:%d/%m}   {CLASSES[classe]:<10} │"
                    achadas = [v for v in viagens if v["disp"].get(classe, 0) >= qtd]

                    if achadas:
                        log(c_str(f"{prefixo} 🟢 >>> VAGA ENCONTRADA! <<<", Cor.VERDE, Cor.NEGRITO))
                        linhas = [linha_viagem(v, classe) for v in achadas]
                        motivo = tratar_vaga(trecho, classe, linhas)
                        if motivo:
                            return motivo
                    else:
                        disponivel.pop((nome, classe), None)
                        msg_vaga = resumo_sem_vaga(viagens, classe, qtd)
                        log(c_str(f"{prefixo} ⏳ {msg_vaga}", Cor.CINZA))

                sessao.bombear(PAUSA_ENTRE_CONSULTAS)

            if falhou:
                espera = min(espera * 2, BACKOFF_MAXIMO)
                log(c_str(f"  [{hora()}]       ⚠️  Conexão oscilando: aguardando {espera}s...", Cor.AMARELO))
            else:
                espera = INTERVALO_SEGUNDOS

            sessao.bombear(espera)

    except KeyboardInterrupt:
        print(c_str("\n\n  🛑 Monitoramento interrompido pelo usuário.", Cor.AMARELO, Cor.NEGRITO))
        return "interrompida"


def perguntar_nova_busca():
    while True:
        r = input(c_str("\n  Deseja realizar uma nova pesquisa? [S = Sim / N = Encerrar]: ", Cor.CIANO, Cor.NEGRITO)).strip().upper()
        if r in ("S", "SIM"):
            return True
        if r in ("N", "NAO", "NÃO"):
            return False
        print(c_str("  [!] Por favor, responda com S ou N.", Cor.VERMELHO))


# ----------------------------------------------------------------------
# CONTROLE DE JANELA EXTERNA (CMD DEDICADO)
# ----------------------------------------------------------------------
FLAG_JANELA_CMD = "--janela-cmd"
ENV_JANELA_CMD = "EFVM_NOVA_JANELA"


def garantir_janela_cmd():
    """
    Garante que o script sempre rode em uma nova janela independente do Prompt
    de Comando (CMD), liberando o terminal do VSCode ou de qualquer outro ambiente.
    Caso o usuário deseje forçar a execução no terminal atual, basta passar --aqui.
    """
    if sys.platform != "win32":
        return

    if FLAG_JANELA_CMD in sys.argv:
        sys.argv.remove(FLAG_JANELA_CMD)
        return

    if "--aqui" in sys.argv or "--no-new-window" in sys.argv:
        if "--aqui" in sys.argv:
            sys.argv.remove("--aqui")
        if "--no-new-window" in sys.argv:
            sys.argv.remove("--no-new-window")
        return

    if os.environ.get(ENV_JANELA_CMD) == "1":
        return

    script_path = os.path.abspath(__file__)
    script_dir = os.path.dirname(script_path)
    python_exe = sys.executable

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env[ENV_JANELA_CMD] = "1"

    subprocess.Popen(
        [python_exe, "-u", script_path, FLAG_JANELA_CMD],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        cwd=script_dir,
        env=env,
    )

    print("\n" + "═" * 70)
    print("  🚂 EFVM TICKET MONITOR")
    print("═" * 70)
    print("  [+] Abrindo uma nova janela externa do Prompt de Comando (CMD)...")
    print("  [+] O monitor será executado na nova janela.")
    print("  [+] Você já pode fechar ou minimizar este terminal do VSCode.")
    print("═" * 70 + "\n")
    time.sleep(1)
    sys.exit(0)


# ----------------------------------------------------------------------
# PONTO DE ENTRADA PRINCIPAL
# ----------------------------------------------------------------------
def main():
    desabilitar_quickedit()

    mensagens = {
        "unica": "Passagem individual encontrada!",
        "conjunto": "Ida e Volta encontradas com sucesso!",
        "interrompida": "Interrompida pelo usuário.",
        "diagnostico": "Modo diagnóstico concluído.",
    }

    if PERFIL_ANTIGO.exists():
        shutil.rmtree(PERFIL_ANTIGO, ignore_errors=True)
        if not PERFIL_ANTIGO.exists():
            log("Limpeza: pasta legada 'perfil_vale' removida com sucesso.")

    with sync_playwright() as pw:
        sessao = Sessao(pw)
        try:
            # 1. Abre a página da Vale para login no navegador e fecha a janela automaticamente
            sessao.login_visual_automatico()

            # 2. Carrega catálogo de estações e datas
            sessao.carregar_dados_site()

            # 3. Ciclo de configuração e busca
            while True:
                trechos, classes, qtd, tipo = montar_trechos(sessao)
                motivo = executar_busca(sessao, trechos, classes, qtd, tipo)
                print(c_str(f"\n  Finalizado: {mensagens.get(motivo, 'Fim do ciclo.')}", Cor.BRANCO, Cor.NEGRITO))

                if not perguntar_nova_busca():
                    break

        except KeyboardInterrupt:
            print()
        except PlaywrightError as e:
            print(c_str(f"\n[!] A janela do navegador reportou erro: {str(e).splitlines()[0]}", Cor.VERMELHO))
        finally:
            sessao.fechar()

    print(c_str("\n  🚂 Obrigado por usar o Monitor EFVM! Boa viagem!\n", Cor.CIANO, Cor.NEGRITO))


if __name__ == "__main__":
    garantir_janela_cmd()
    try:
        main()
    except KeyboardInterrupt:
        print("\nPrograma interrompido.")
    except Exception as e:
        print(f"\n[!] Erro inesperado: {e}")
    finally:
        if sys.platform == "win32":
            try:
                input("\nPressione ENTER para fechar esta janela...")
            except Exception:
                pass
