# roteador.py
# Roteador intermediário da rede Mini-NET.
# Todo tráfego entre clientes e servidor passa por aqui.
#
# Responsabilidades:
#   Camada 1 (Física) — recebe e reencaminha bytes pelo canal ruidoso (protocol.py)
#   Camada 2 (Enlace) — verifica CRC do quadro recebido e remonta com MACs atualizados
#   Camada 3 (Rede)   — lê VIP de destino, decrementa TTL e consulta tabela de rotas

import socket
from protocol import Quadro, enviar_pela_rede_ruidosa

ROTEADOR_IP    = "127.0.0.1"
ROTEADOR_PORTA = 6000
ROTEADOR_VIP   = "ROTEADOR"
ROTEADOR_MAC   = "FF:FF:FF:00:00:01"
BUFFER_SIZE    = 65536

VERMELHO = "\033[91m"; AMARELO = "\033[93m"
AZUL     = "\033[94m"; MAGENTA = "\033[95m"; CIANO = "\033[96m"; RESET = "\033[0m"

def log_fisica(m):   print(f"   {VERMELHO}[FÍSICA]{RESET} {m}")
def log_enlace(m):   print(f"  {MAGENTA}[ENLACE]{RESET} {m}")
def log_rede(m):     print(f"  {AZUL}[REDE]{RESET} {m}")
def log_roteador(m): print(f"  {CIANO}[ROTEADOR]{RESET} {m}")

# Tabela de roteamento estática: VIP -> (IP real, Porta real).
# Para adicionar um novo host, inclua entradas aqui, em TABELA_ARP
# e em _ARP no server.py.
TABELA_ROTEAMENTO = {
    "SERVIDOR": ("127.0.0.1", 5001),
    "HOST_A":   ("127.0.0.1", 5002),
    "HOST_B":   ("127.0.0.1", 5003),
    "HOST_C":   ("127.0.0.1", 5004),
}

# Tabela ARP: VIP -> MAC real, usada para preencher DST_MAC do quadro remontado
TABELA_ARP = {
    "SERVIDOR": "AA:BB:CC:DD:EE:02",
    "HOST_A":   "AA:BB:CC:DD:EE:01",
    "HOST_B":   "AA:BB:CC:DD:EE:03",
    "HOST_C":   "AA:BB:CC:DD:EE:04",
}


# ------------------------------------------------------------------
# Loop principal — stateless: cada pacote é tratado de forma
# independente, sem guardar estado entre mensagens.
# ------------------------------------------------------------------

def rotear(sock):
    print(f"\n{CIANO}[ROTEADOR] Aguardando pacotes...{RESET}\n")

    while True:
        try:
            dados_brutos, endereco_origem = sock.recvfrom(BUFFER_SIZE)
            log_fisica(f"Quadro recebido de {endereco_origem} ({len(dados_brutos)} bytes)")

            # Camada 2: verifica integridade pelo CRC antes de qualquer processamento
            quadro_dict, integro = Quadro.deserializar(dados_brutos)
            if not integro:
                log_enlace("Quadro CORROMPIDO! (Erro CRC) -> Descartando.")
                log_rede("Pacote não será roteado (quadro inválido).")
                continue

            log_enlace(f"Quadro íntegro - CRC OK ✓ | "
                       f"SRC_MAC={quadro_dict.get('src_mac','?')} -> "
                       f"DST_MAC={quadro_dict.get('dst_mac','?')}")

            # Camada 3: extrai VIP de destino e verifica TTL
            pacote_dict = quadro_dict.get('data', {})
            vip_origem  = pacote_dict.get('src_vip', '?')
            vip_destino = pacote_dict.get('dst_vip', '?')
            ttl         = pacote_dict.get('ttl', 0)
            log_rede(f"Pacote: {vip_origem} -> {vip_destino} | TTL={ttl}")

            if ttl <= 0:
                log_rede("TTL expirado! Pacote descartado.")
                continue

            pacote_dict['ttl'] = ttl - 1
            log_rede(f"TTL decrementado: {ttl} -> {ttl - 1}")

            if vip_destino not in TABELA_ROTEAMENTO:
                log_rede(f"Destino '{vip_destino}' não encontrado na tabela. Descartando.")
                continue

            endereco_destino = TABELA_ROTEAMENTO[vip_destino]
            mac_destino      = TABELA_ARP.get(vip_destino, "FF:FF:FF:FF:FF:FF")
            log_roteador(f"Rota encontrada: {vip_destino} -> {endereco_destino}")

            # Remonta o quadro: SRC_MAC vira o do roteador (comportamento L2 padrão),
            # DST_MAC vira o MAC real do próximo salto consultado na TABELA_ARP
            novo_quadro      = Quadro(src_mac=ROTEADOR_MAC, dst_mac=mac_destino,
                                      pacote_dict=pacote_dict)
            bytes_encaminhar = novo_quadro.serializar()
            log_enlace(f"Novo quadro | SRC_MAC={ROTEADOR_MAC} -> DST_MAC={mac_destino}")

            # Camada 1: envia pelo canal ruidoso definido em protocol.py
            log_roteador(f"Encaminhando para {endereco_destino}...")
            enviar_pela_rede_ruidosa(sock, bytes_encaminhar, endereco_destino)

            log_roteador(f"Pacote roteado: {vip_origem} -> {vip_destino} ✓")
            print("-" * 50)

        except Exception as e:
            log_fisica(f"Erro no roteador: {e}")


def main():
    print("=" * 60)
    print(f"{CIANO}  ROTEADOR Mini-NET{RESET}")
    print(f"  VIP : {ROTEADOR_VIP} | MAC: {ROTEADOR_MAC}")
    print(f"  Bind: {ROTEADOR_IP}:{ROTEADOR_PORTA}")
    print(f"\n  Tabela de Roteamento:")
    for vip, (ip, porta) in TABELA_ROTEAMENTO.items():
        print(f"    {vip:12s} -> {ip}:{porta}  (MAC: {TABELA_ARP.get(vip,'?')})")
    print("=" * 60)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((ROTEADOR_IP, ROTEADOR_PORTA))
    log_fisica(f"Socket UDP em {ROTEADOR_IP}:{ROTEADOR_PORTA}")

    try:
        rotear(sock)
    except KeyboardInterrupt:
        print(f"\n{AMARELO}[ROTEADOR] Encerrando...{RESET}")
    finally:
        sock.close()

if __name__ == "__main__":
    main()
