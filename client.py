"""
client.py - Cliente do Chat Mini-NET

Implementa todas as 4 camadas:
- Camada 1 (Física): Usa enviar_pela_rede_ruidosa do protocolo.py
- Camada 2 (Enlace): Quadro com MAC e CRC32
- Camada 3 (Rede): Pacote com VIP e TTL
- Camada 4 (Transporte): Segmento com Stop-and-Wait (SEQ/ACK)
- Camada 5 (Aplicação): Chat JSON
"""

import socket
import json
import threading
import time
import sys
from protocol import (
    Segmento, Pacote, Quadro,
    enviar_pela_rede_ruidosa
)

# ===================== CONFIGURAÇÕES =====================
# O cliente envia ao ROTEADOR, não diretamente ao servidor
ROTEADOR_IP = "127.0.0.1"
ROTEADOR_PORTA = 6000

# Identificação do cliente
CLIENTE_IP = "127.0.0.1"
CLIENTE_PORTA = 5002       # Altere para 5003, 5004, etc. para múltiplos clientes
CLIENTE_VIP = "HOST_A"     # Altere para HOST_B, HOST_C, etc.
CLIENTE_MAC = "AA:BB:CC:DD:EE:01"

DESTINO_VIP = "SERVIDOR"
DESTINO_MAC = "AA:BB:CC:DD:EE:02"  # MAC do servidor (simplificado)

BUFFER_SIZE = 4096
TIMEOUT_ACK = 2.0  # segundos

# Cores para logs
VERMELHO = "\033[91m"
AMARELO = "\033[93m"
VERDE = "\033[92m"
AZUL = "\033[94m"
CIANO = "\033[96m"
MAGENTA = "\033[95m"
RESET = "\033[0m"

# ===================== ESTADO DO TRANSPORTE =====================
seq_envio = 0
seq_esperado = 0
lock = threading.Lock()


def log_fisica(msg):
    print(f"   {VERMELHO}[FÍSICA]{RESET} {msg}")

def log_enlace(msg):
    print(f"  {MAGENTA}[ENLACE]{RESET} {msg}")

def log_rede(msg):
    print(f"  {AZUL}[REDE]{RESET} {msg}")

def log_transporte(msg):
    print(f"  {AMARELO}[TRANSPORTE]{RESET} {msg}")

def log_aplicacao(msg):
    print(f"  {VERDE}[APLICAÇÃO]{RESET} {msg}")


# =================================================================
# CAMADA 2 (ENLACE): Envio de quadro com MAC e CRC
# =================================================================
def enviar_quadro(sock, dados_pacote_dict, mac_destino, endereco_real):
    """
    Encapsula um Pacote (dict) em um Quadro (Enlace),
    calcula o CRC e envia pela rede ruidosa.
    """
    quadro = Quadro(
        src_mac=CLIENTE_MAC,
        dst_mac=mac_destino,
        pacote_dict=dados_pacote_dict
    )
    bytes_quadro = quadro.serializar()
    log_enlace(f"Quadro serializado ({len(bytes_quadro)} bytes) | "
               f"SRC_MAC={CLIENTE_MAC} -> DST_MAC={mac_destino}")
    enviar_pela_rede_ruidosa(sock, bytes_quadro, endereco_real)


# =================================================================
# CAMADA 4 (TRANSPORTE): Envio confiável com Stop-and-Wait
# =================================================================
def enviar_confiavel(sock, payload_app):
    """
    Envia um segmento de dados com Stop-and-Wait.
    Retransmite até receber ACK com o seq_num correto.
    """
    global seq_envio

    segmento = Segmento(seq_num=seq_envio, is_ack=False, payload=payload_app)
    pacote = Pacote(
        src_vip=CLIENTE_VIP,
        dst_vip=DESTINO_VIP,
        ttl=64,
        segmento_dict=segmento.to_dict()
    )

    max_tentativas = 10
    tentativa = 0

    while tentativa < max_tentativas:
        tentativa += 1
        log_transporte(f"Enviando segmento SEQ={seq_envio} (tentativa {tentativa})")

        # Camada 3 -> Camada 2 -> Camada 1
        # Envia ao roteador (que encaminhará ao servidor)
        enviar_quadro(sock, pacote.to_dict(), DESTINO_MAC, (ROTEADOR_IP, ROTEADOR_PORTA))

        # Aguarda ACK
        sock.settimeout(TIMEOUT_ACK)
        try:
            dados_brutos, addr = sock.recvfrom(BUFFER_SIZE)

            # Camada 2: Verifica integridade do quadro
            quadro_dict, integro = Quadro.deserializar(dados_brutos)
            if not integro:
                log_enlace("Quadro de ACK recebido CORROMPIDO! (Erro CRC) -> Descartando.")
                continue

            log_enlace("Quadro de ACK recebido - CRC OK ✓")

            # Camada 3: Extrai pacote
            pacote_recebido = quadro_dict['data']
            seg_recebido = pacote_recebido['data']

            if seg_recebido.get('is_ack') and seg_recebido.get('seq_num') == seq_envio:
                log_transporte(f"ACK recebido para SEQ={seq_envio} ✓")
                seq_envio = 1 - seq_envio  # Alterna 0 <-> 1
                return True
            else:
                log_transporte(f"ACK inesperado (seq={seg_recebido.get('seq_num')}), aguardando...")

        except socket.timeout:
            log_transporte(f"TIMEOUT! ACK não recebido para SEQ={seq_envio}. Retransmitindo...")

    log_transporte(f"FALHA: Número máximo de tentativas atingido para SEQ={seq_envio}")
    return False


# =================================================================
# CAMADA 4 (TRANSPORTE): Envio de ACK
# =================================================================
def enviar_ack(sock, seq_num, vip_destino, mac_destino, endereco_real):
    """Envia um ACK para o remetente."""
    segmento_ack = Segmento(seq_num=seq_num, is_ack=True, payload={})
    pacote_ack = Pacote(
        src_vip=CLIENTE_VIP,
        dst_vip=vip_destino,
        ttl=64,
        segmento_dict=segmento_ack.to_dict()
    )
    log_transporte(f"Enviando ACK para SEQ={seq_num}")
    enviar_quadro(sock, pacote_ack.to_dict(), mac_destino, endereco_real)


# =================================================================
# THREAD DE RECEBIMENTO
# =================================================================
def thread_receber(sock):
    """Thread que escuta mensagens do servidor."""
    global seq_esperado

    while True:
        try:
            sock.settimeout(None)
            dados_brutos, endereco_remetente = sock.recvfrom(BUFFER_SIZE)

            # ========== CAMADA 2: ENLACE ==========
            quadro_dict, integro = Quadro.deserializar(dados_brutos)

            if not integro:
                log_enlace("Quadro recebido CORROMPIDO! (Erro CRC) -> Descartando silenciosamente.")
                log_transporte("Quadro descartado -> O emissor fará retransmissão via timeout.")
                continue

            log_enlace(f"Quadro recebido de MAC={quadro_dict.get('src_mac', '?')} - CRC OK ✓")
            mac_remetente = quadro_dict.get('src_mac', 'UNKNOWN')

            # ========== CAMADA 3: REDE ==========
            pacote_dict = quadro_dict['data']
            vip_origem = pacote_dict.get('src_vip', '?')
            vip_destino = pacote_dict.get('dst_vip', '?')
            ttl = pacote_dict.get('ttl', 0)

            log_rede(f"Pacote de {vip_origem} -> {vip_destino} | TTL={ttl}")

            if ttl <= 0:
                log_rede("TTL expirado! Pacote descartado.")
                continue

            if vip_destino != CLIENTE_VIP:
                log_rede(f"Pacote não é para este host ({CLIENTE_VIP}). Descartando.")
                continue

            # ========== CAMADA 4: TRANSPORTE ==========
            segmento_dict = pacote_dict['data']
            seq_num = segmento_dict.get('seq_num', 0)
            is_ack = segmento_dict.get('is_ack', False)

            # Se for ACK, ignora (tratado na thread de envio)
            if is_ack:
                continue

            log_transporte(f"Segmento recebido: SEQ={seq_num} | Esperado={seq_esperado}")

            if seq_num == seq_esperado:
                # Pacote correto
                enviar_ack(sock, seq_num, vip_origem, mac_remetente, endereco_remetente)
                seq_esperado = 1 - seq_esperado

                # ========== CAMADA 5: APLICAÇÃO ==========
                payload = segmento_dict.get('payload', {})
                processar_mensagem_aplicacao(payload, vip_origem)
            else:
                # Duplicado
                log_transporte(f"Segmento DUPLICADO (SEQ={seq_num}). Reenviando ACK anterior.")
                enviar_ack(sock, seq_num, vip_origem, mac_remetente, endereco_remetente)

        except socket.timeout:
            continue
        except Exception as e:
            log_fisica(f"Erro ao receber dados: {e}")


# =================================================================
# CAMADA 5: APLICAÇÃO
# =================================================================
def processar_mensagem_aplicacao(payload, vip_origem):
    """Processa a mensagem JSON da camada de aplicação."""
    tipo = payload.get('type', 'unknown')
    sender = payload.get('sender', vip_origem)
    mensagem = payload.get('message', '')
    timestamp = payload.get('timestamp', '')

    if tipo == "MSG":
        log_aplicacao(f"💬 [{sender}] ({timestamp}): {mensagem}")
    elif tipo == "JOIN":
        log_aplicacao(f"🟢 {sender} entrou no chat!")
    elif tipo == "LEAVE":
        log_aplicacao(f"🔴 {sender} saiu do chat!")
    else:
        log_aplicacao(f"Mensagem recebida de {sender}: {payload}")


# =================================================================
# MAIN
# =================================================================
def main():
    print("=" * 60)
    print(f"{VERDE}  CLIENTE Mini-NET{RESET}")
    print(f"  VIP: {CLIENTE_VIP} | MAC: {CLIENTE_MAC}")
    print(f"  Porta local: {CLIENTE_PORTA}")
    print(f"  Roteador: {ROTEADOR_IP}:{ROTEADOR_PORTA}")
    print("=" * 60)

    # Cria socket UDP
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((CLIENTE_IP, CLIENTE_PORTA))

    log_fisica(f"Socket UDP criado e vinculado a {CLIENTE_IP}:{CLIENTE_PORTA}")

    # Inicia thread de recebimento
    t_receber = threading.Thread(target=thread_receber, args=(sock,), daemon=True)
    t_receber.start()
    log_aplicacao("Thread de recebimento iniciada.")

    # Envia mensagem JOIN
    join_payload = {
        "type": "JOIN",
        "sender": CLIENTE_VIP,
        "message": f"{CLIENTE_VIP} entrou no chat",
        "timestamp": time.strftime("%H:%M:%S")
    }
    log_aplicacao(f"Enviando notificação JOIN...")
    enviar_confiavel(sock, join_payload)

    # Loop principal: envio de mensagens
    print(f"\n{CIANO}Digite suas mensagens (ou 'sair' para encerrar):{RESET}\n")

    try:
        while True:
            msg = input()
            if not msg.strip():
                continue

            if msg.strip().lower() == 'sair':
                # Envia LEAVE
                leave_payload = {
                    "type": "LEAVE",
                    "sender": CLIENTE_VIP,
                    "message": f"{CLIENTE_VIP} saiu do chat",
                    "timestamp": time.strftime("%H:%M:%S")
                }
                enviar_confiavel(sock, leave_payload)
                break

            timestamp = time.strftime("%H:%M:%S")
            payload_app = {
                "type": "MSG",
                "sender": CLIENTE_VIP,
                "message": msg,
                "timestamp": timestamp
            }

            log_aplicacao(f"Preparando envio de mensagem...")
            sucesso = enviar_confiavel(sock, payload_app)

            if sucesso:
                log_aplicacao("Mensagem entregue com sucesso ✓")
            else:
                log_aplicacao("Falha ao entregar mensagem ✗")

    except (KeyboardInterrupt, EOFError):
        pass

    print(f"\n{AMARELO}[CLIENTE] Encerrando...{RESET}")
    sock.close()


if __name__ == "__main__":
    main()