# main.py
import subprocess
import sys
import time
import signal
import threading

HOSTS = [
    ("HOST_A", "AA:BB:CC:DD:EE:01", 5002, 8080),
    ("HOST_B", "AA:BB:CC:DD:EE:03", 5003, 8081),
]

CORES = {
    "Roteador": "\033[96m",   # ciano
    "Servidor": "\033[92m",   # verde
    "HOST_A":   "\033[94m",   # azul
    "HOST_B":   "\033[95m",   # magenta
    "HOST_C":   "\033[93m",   # amarelo
}
RESET   = "\033[0m"
AMARELO = "\033[93m"
CIANO   = "\033[96m"

processos = []


def redirecionar_saida(processo, nome):
    """
    Lê stdout do subprocesso linha a linha e imprime
    com prefixo colorido identificando o componente.
    Roda em thread daemon para não bloquear o main.
    """
    cor    = CORES.get(nome, "\033[97m")
    prefixo = f"{cor}[{nome}]{RESET}"

    for linha in processo.stdout:
        print(f"{prefixo} {linha}", end="")


def iniciar(nome, cmd):
    # -u força o Python filho a não fazer buffer no stdout
    cmd_sem_buffer = [cmd[0], "-u"] + cmd[1:]

    p = subprocess.Popen(
        cmd_sem_buffer,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,                  # 1 significa "line buffered" (ideal para text=True)
        encoding='utf-8',           # Força a leitura em UTF-8
        errors='replace'            # Substitui caracteres problemáticos por '?' em vez de travar
    )
    processos.append((nome, p))
    threading.Thread(target=redirecionar_saida, args=(p, nome), daemon=True).start()
    return p



def encerrar(sig=None, frame=None):
    print(f"\n{AMARELO}Encerrando todos os processos...{RESET}")
    for _, p in processos:
        p.terminate()
    for _, p in processos:
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()
    print(f"{AMARELO}Encerrado.{RESET}")
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT,  encerrar)
    signal.signal(signal.SIGTERM, encerrar)

    print("=" * 50)
    print(f"{CIANO}  Mini-NET Chat{RESET}")
    print("=" * 50 + "\n")

    iniciar("Roteador", [sys.executable, "roteador.py"])
    time.sleep(0.5)

    iniciar("Servidor", [sys.executable, "server.py"])
    time.sleep(0.5)

    for vip, mac, porta_rede, porta_web in HOSTS:
        iniciar(vip, [sys.executable, "interface.py", vip, mac,
                      str(porta_rede), str(porta_web)])
        time.sleep(0.5)

    print("\n" + "=" * 50)
    for vip, _, _, porta_web in HOSTS:
        cor = CORES.get(vip, "")
        print(f"  {cor}{vip}{RESET} -> http://127.0.0.1:{porta_web}")
    print("=" * 50)
    print(f"\n  {AMARELO}Ctrl+C para encerrar tudo.{RESET}\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        encerrar()


if __name__ == "__main__":
    main()
