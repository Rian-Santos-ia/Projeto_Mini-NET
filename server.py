"""
server.py - Servidor do Chat Mini-NET

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
from protocol import (
    Segmento, Pacote, Quadro,
    enviar_pela_rede_ruidosa
)

# ===================== CONFIGURAÇÕES =====================
SERVIDOR_IP = "127.0.0.1"
SERVIDOR_PORTA = 5001
SERVIDOR_VIP = "SERVIDOR"
SERVIDOR_MAC = "AA:BB:CC:DD:EE:02"
BUFFER_SIZE = 4096
TIMEOUT_ACK = 2.0  # segundos para timeout do ACK

# Cores para logs
VERMELHO = "\033[91m"
AMARELO = "\033[93m"
VERDE = "\033[92m"
AZUL = "\033[94m"
CIANO = "\033[96m"
MAGENTA = "\033[95m"
RESET = "\033[0m"

# ===================== ESTADO DO TRANSPORTE =====================
# Número de sequência esperado (Stop-and-Wait)
seq_esperado = 0
# Lock para acesso thread-safe
lock = threading.Lock()
# Dicionário de clientes conectados: { (ip, porta): {"vip": ..., "mac": ..., "seq": ...} }
clientes = {}


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
        src_mac=SERVIDOR_MAC,
        dst_mac=mac_destino,
        pacote_dict=dados_pacote_dict
    )
    bytes_quadro = quadro.serializar()
    log_enlace(f"Quadro serializado ({len(bytes_quadro)} bytes) | "
               f"SRC_MAC={SERVIDOR_MAC} -> DST_MAC={mac_destino}")
    enviar_pela_rede_ruidosa(sock, bytes_quadro, endereco_real)


# =================================================================
# CAMADA 4 (TRANSPORTE): Envio confiável com Stop-and-Wait
# =================================================================
def enviar_confiavel(sock, payload_app, vip_destino, mac_destino, endereco_real, seq_num):
    """
    Envia um segmento de dados com Stop-and-Wait.
    Retransmite até receber ACK com o seq_num correto.
    """
    segmento = Segmento(seq_num=seq_num, is_ack=False, payload=payload_app)
    pacote = Pacote(
        src_vip=SERVIDOR_VIP,
        dst_vip=vip_destino,
        ttl=64,
        segmento_dict=segmento.to_dict()
    )

    max_tentativas = 10
    tentativa = 0

    while tentativa < max_tentativas:
        tentativa += 1
        log_transporte(f"Enviando segmento SEQ={seq_num} (tentativa {tentativa})")

        # Camada 3 -> Camada 2 -> Camada 1
        enviar_quadro(sock, pacote.to_dict(), mac_destino, endereco_real)

        # Aguarda ACK (usa timeout no socket)
        sock.settimeout(TIMEOUT_ACK)
        try:
            dados_brutos, addr = sock.recvfrom(BUFFER_SIZE)
            # Camada 2: Verifica integridade do quadro
            quadro_dict, integro = Quadro.deserializar(dados_brutos)
            if not integro:
                log_enlace("Quadro de ACK recebido CORROMPIDO! (Erro CRC) -> Descartando.")
                continue

            log_enlace("Quadro de ACK recebido - CRC OK ✓")

            # Camada 3: Verifica VIP
            pacote_recebido = quadro_dict['data']
            seg_recebido = pacote_recebido['data']

            if seg_recebido.get('is_ack') and seg_recebido.get('seq_num') == seq_num:
                log_transporte(f"ACK recebido para SEQ={seq_num} ✓")
                return True
            else:
                log_transporte(f"ACK inesperado (seq={seg_recebido.get('seq_num')}), aguardando...")

        except socket.timeout:
            log_transporte(f"TIMEOUT! ACK não recebido para SEQ={seq_num}. Retransmitindo...")

    log_transporte(f"FALHA: Número máximo de tentativas atingido para SEQ={seq_num}")
    return False


# =================================================================
# CAMADA 4 (TRANSPORTE): Envio de ACK
# =================================================================
def enviar_ack(sock, seq_num, vip_destino, mac_destino, endereco_real):
    """Envia um ACK para o remetente."""
    segmento_ack = Segmento(seq_num=seq_num, is_ack=True, payload={})
    pacote_ack = Pacote(
        src_vip=SERVIDOR_VIP,
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
    """Thread que escuta mensagens dos clientes."""
    global seq_esperado

    sock.settimeout(None)  # Sem timeout para a thread de recebimento

    while True:
        try:
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

            # Verifica TTL
            if ttl <= 0:
                log_rede("TTL expirado! Pacote descartado.")
                continue

            # Verifica se o pacote é destinado a este servidor
            if vip_destino != SERVIDOR_VIP:
                log_rede(f"Pacote não é para este host ({SERVIDOR_VIP}). Descartando.")
                continue

            # ========== CAMADA 4: TRANSPORTE ==========
            segmento_dict = pacote_dict['data']
            seq_num = segmento_dict.get('seq_num', 0)
            is_ack = segmento_dict.get('is_ack', False)

            # Se for ACK, ignora (tratado na thread de envio)
            if is_ack:
                log_transporte(f"ACK recebido para SEQ={seq_num} (processado pela thread de envio)")
                continue

            # Registra o cliente
            if endereco_remetente not in clientes:
                clientes[endereco_remetente] = {
                    "vip": vip_origem,
                    "mac": mac_remetente,
                    "seq_esperado": 0
                }

            cliente_info = clientes[endereco_remetente]
            seq_esperado_cliente = cliente_info["seq_esperado"]

            log_transporte(f"Segmento recebido: SEQ={seq_num} | Esperado={seq_esperado_cliente}")

            if seq_num == seq_esperado_cliente:
                # Pacote correto: envia ACK e processa
                enviar_ack(sock, seq_num, vip_origem, mac_remetente, endereco_remetente)

                # Alterna o número de sequência esperado (0 -> 1 -> 0)
                cliente_info["seq_esperado"] = 1 - seq_esperado_cliente

                # ========== CAMADA 5: APLICAÇÃO ==========
                payload = segmento_dict.get('payload', {})
                processar_mensagem_aplicacao(payload, vip_origem)
            else:
                # Pacote duplicado: reenvia ACK do anterior
                log_transporte(f"Segmento DUPLICADO (SEQ={seq_num}). Reenviando ACK anterior.")
                enviar_ack(sock, seq_num, vip_origem, mac_remetente, endereco_remetente)

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
# THREAD DE ENVIO (Servidor também pode enviar mensagens)
# =================================================================
def thread_enviar(sock):
    """Thread que permite ao servidor enviar mensagens para clientes."""
    seq_envio = 0

    while True:
        try:
            msg = input()  # Aguarda input do servidor
            if not msg.strip():
                continue

            timestamp = time.strftime("%H:%M:%S")
            payload_app = {
                "type": "MSG",
                "sender": SERVIDOR_VIP,
                "message": msg,
                "timestamp": timestamp
            }

            # Envia para todos os clientes registrados
            for endereco, info in list(clientes.items()):
                log_aplicacao(f"Enviando mensagem para {info['vip']}...")
                sucesso = enviar_confiavel(
                    sock, payload_app,
                    info['vip'], info['mac'],
                    endereco, seq_envio
                )
                if sucesso:
                    log_aplicacao(f"Mensagem entregue a {info['vip']} ✓")
                else:
                    log_aplicacao(f"Falha ao entregar mensagem a {info['vip']} ✗")

            seq_envio = 1 - seq_envio

        except (KeyboardInterrupt, EOFError):
            print("\n[SERVIDOR] Encerrando...")
            break


# =================================================================
# MAIN
# =================================================================
def main():
    print("=" * 60)
    print(f"{VERDE}  SERVIDOR Mini-NET{RESET}")
    print(f"  VIP: {SERVIDOR_VIP} | MAC: {SERVIDOR_MAC}")
    print(f"  Escutando em {SERVIDOR_IP}:{SERVIDOR_PORTA}")
    print("=" * 60)

    # Cria socket UDP
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((SERVIDOR_IP, SERVIDOR_PORTA))

    log_fisica(f"Socket UDP criado e vinculado a {SERVIDOR_IP}:{SERVIDOR_PORTA}")

    # Inicia thread de recebimento
    t_receber = threading.Thread(target=thread_receber, args=(sock,), daemon=True)
    t_receber.start()
    log_aplicacao("Thread de recebimento iniciada.")

    # Thread principal: envio de mensagens
    print(f"\n{CIANO}Digite mensagens para enviar aos clientes (ou Ctrl+C para sair):{RESET}\n")
    thread_enviar(sock)

    sock.close()


if __name__ == "__main__":
    main()
