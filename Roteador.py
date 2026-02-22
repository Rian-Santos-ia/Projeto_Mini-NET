"""
roteador.py - Roteador Intermediário do Projeto Mini-NET

O roteador recebe quadros de qualquer host, inspeciona o endereço
VIP de destino na camada de Rede, consulta sua tabela de roteamento
estática e encaminha o pacote para o IP/Porta real correto.

Implementa:
- Camada 2 (Enlace): Verifica CRC do quadro recebido, re-serializa para envio
- Camada 3 (Rede): Lê VIP destino, decrementa TTL, consulta tabela de rotas
- Camada 1 (Física): Usa enviar_pela_rede_ruidosa para reencaminhar
"""

import socket
import json
import time
from protocol import (
    Quadro,
    enviar_pela_rede_ruidosa
)

# ===================== CONFIGURAÇÕES =====================
ROTEADOR_IP = "127.0.0.1"
ROTEADOR_PORTA = 6000
ROTEADOR_VIP = "ROTEADOR"
ROTEADOR_MAC = "FF:FF:FF:00:00:01"
BUFFER_SIZE = 4096

# Cores para logs
VERMELHO = "\033[91m"
AMARELO = "\033[93m"
VERDE = "\033[92m"
AZUL = "\033[94m"
CIANO = "\033[96m"
MAGENTA = "\033[95m"
RESET = "\033[0m"

# =================================================================
# TABELA DE ROTEAMENTO ESTÁTICA
# Mapeia VIP -> (IP_real, Porta_real)
# =================================================================
TABELA_ROTEAMENTO = {
    "SERVIDOR":  ("127.0.0.1", 5001),
    "HOST_A":    ("127.0.0.1", 5002),
    "HOST_B":    ("127.0.0.1", 5003),
    "HOST_C":    ("127.0.0.1", 5004),
}

# Tabela ARP simplificada: VIP -> MAC
TABELA_ARP = {
    "SERVIDOR":  "AA:BB:CC:DD:EE:02",
    "HOST_A":    "AA:BB:CC:DD:EE:01",
    "HOST_B":    "AA:BB:CC:DD:EE:03",
    "HOST_C":    "AA:BB:CC:DD:EE:04",
}


def log_fisica(msg):
    print(f"   {VERMELHO}[FÍSICA]{RESET} {msg}")

def log_enlace(msg):
    print(f"  {MAGENTA}[ENLACE]{RESET} {msg}")

def log_rede(msg):
    print(f"  {AZUL}[REDE]{RESET} {msg}")

def log_roteador(msg):
    print(f"  {CIANO}[ROTEADOR]{RESET} {msg}")


# =================================================================
# LÓGICA PRINCIPAL DO ROTEADOR
# =================================================================
def rotear(sock):
    """Loop principal do roteador: recebe, inspeciona e encaminha."""
    print(f"\n{CIANO}[ROTEADOR] Aguardando pacotes para rotear...{RESET}\n")

    while True:
        try:
            # Recebe quadro bruto
            dados_brutos, endereco_origem = sock.recvfrom(BUFFER_SIZE)
            log_fisica(f"Quadro recebido de {endereco_origem} ({len(dados_brutos)} bytes)")

            # ========== CAMADA 2: ENLACE ==========
            # Verifica integridade do quadro (CRC)
            quadro_dict, integro = Quadro.deserializar(dados_brutos)

            if not integro:
                log_enlace("Quadro CORROMPIDO! (Erro CRC) -> Descartando.")
                log_rede("Pacote não será roteado (quadro inválido).")
                continue

            log_enlace(f"Quadro íntegro - CRC OK ✓ | "
                       f"SRC_MAC={quadro_dict.get('src_mac', '?')} -> "
                       f"DST_MAC={quadro_dict.get('dst_mac', '?')}")

            # ========== CAMADA 3: REDE ==========
            pacote_dict = quadro_dict.get('data', {})
            vip_origem = pacote_dict.get('src_vip', '?')
            vip_destino = pacote_dict.get('dst_vip', '?')
            ttl = pacote_dict.get('ttl', 0)

            log_rede(f"Pacote: {vip_origem} -> {vip_destino} | TTL={ttl}")

            # Verifica TTL
            if ttl <= 0:
                log_rede("⚠ TTL expirado! Pacote descartado.")
                continue

            # Decrementa TTL
            ttl -= 1
            pacote_dict['ttl'] = ttl
            log_rede(f"TTL decrementado: {ttl + 1} -> {ttl}")

            # Consulta tabela de roteamento
            if vip_destino not in TABELA_ROTEAMENTO:
                log_rede(f"⚠ Destino '{vip_destino}' não encontrado na tabela de roteamento! Descartando.")
                continue

            endereco_destino_real = TABELA_ROTEAMENTO[vip_destino]
            mac_destino = TABELA_ARP.get(vip_destino, "FF:FF:FF:FF:FF:FF")

            log_roteador(f"Rota encontrada: {vip_destino} -> {endereco_destino_real}")

            # ========== REENCAMINHAMENTO ==========
            # Cria novo quadro com MACs atualizados (roteador como origem)
            novo_quadro = Quadro(
                src_mac=ROTEADOR_MAC,
                dst_mac=mac_destino,
                pacote_dict=pacote_dict
            )

            bytes_reencaminhados = novo_quadro.serializar()
            log_enlace(f"Novo quadro criado | SRC_MAC={ROTEADOR_MAC} -> DST_MAC={mac_destino}")

            # Envia pela rede ruidosa (Camada 1)
            log_roteador(f"Encaminhando para {endereco_destino_real}...")
            enviar_pela_rede_ruidosa(sock, bytes_reencaminhados, endereco_destino_real)

            log_roteador(f"Pacote roteado: {vip_origem} -> {vip_destino} ✓")
            print("-" * 50)

        except Exception as e:
            log_fisica(f"Erro no roteador: {e}")


# =================================================================
# MAIN
# =================================================================
def main():
    print("=" * 60)
    print(f"{CIANO}  ROTEADOR Mini-NET{RESET}")
    print(f"  VIP: {ROTEADOR_VIP} | MAC: {ROTEADOR_MAC}")
    print(f"  Escutando em {ROTEADOR_IP}:{ROTEADOR_PORTA}")
    print("=" * 60)
    print(f"\n  Tabela de Roteamento:")
    for vip, (ip, porta) in TABELA_ROTEAMENTO.items():
        mac = TABELA_ARP.get(vip, "?")
        print(f"    {vip:20s} -> {ip}:{porta}  (MAC: {mac})")
    print()

    # Cria socket UDP
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((ROTEADOR_IP, ROTEADOR_PORTA))

    log_fisica(f"Socket UDP criado e vinculado a {ROTEADOR_IP}:{ROTEADOR_PORTA}")

    try:
        rotear(sock)
    except KeyboardInterrupt:
        print(f"\n{AMARELO}[ROTEADOR] Encerrando...{RESET}")
    finally:
        sock.close()


if __name__ == "__main__":
    main()