# server.py
# Servidor de chat da rede Mini-NET.
# Recebe mensagens dos clientes, processa na camada de aplicação
# e faz broadcast para todos os outros clientes conectados.

import socket
import threading
import queue
from protocol import Segmento, Pacote, Quadro, enviar_pela_rede_ruidosa

SERVIDOR_IP    = "127.0.0.1"
SERVIDOR_PORTA = 5001
SERVIDOR_VIP   = "SERVIDOR"
SERVIDOR_MAC   = "AA:BB:CC:DD:EE:02"
BUFFER_SIZE    = 65536  # mesmo limite do cliente — necessário para imagens
TIMEOUT_ACK    = 3.0    # ligeiramente maior que o cliente por ter mais carga

VERMELHO = "\033[91m"; AMARELO = "\033[93m"; VERDE  = "\033[92m"
AZUL     = "\033[94m"; MAGENTA = "\033[95m"; RESET  = "\033[0m"

def log_fisica(m):     print(f"   {VERMELHO}[FÍSICA]{RESET} {m}")
def log_enlace(m):     print(f"  {MAGENTA}[ENLACE]{RESET} {m}")
def log_rede(m):       print(f"  {AZUL}[REDE]{RESET} {m}")
def log_transporte(m): print(f"  {AMARELO}[TRANSPORTE]{RESET} {m}")
def log_aplicacao(m):  print(f"  {VERDE}[APLICAÇÃO]{RESET} {m}")

# Clientes conectados: { vip: { endereco, seq_esperado, seq_envio } }
# Indexado por VIP porque o endereço que chega é sempre o do roteador
clientes = {}
lock_cl  = threading.Lock()

# Filas de ACK ativas durante broadcasts: { (vip, seq, tid): Queue }
# Cada enviar_confiavel cria sua própria fila identificada pelo thread_id,
# evitando que broadcasts paralelos consumam ACKs um do outro
filas_ack  = {}
lock_filas = threading.Lock()

# Tabela ARP local: VIP -> MAC real do cliente.
# Necessária porque o roteador sobrescreve o MAC de origem dos quadros —
# ao receber um pacote, o MAC que chega é sempre o do roteador (FF:FF:FF:00:00:01).
# O servidor usa esta tabela para montar corretamente o MAC de destino nas respostas.
# Para adicionar um novo cliente, inclua uma entrada em _ARP abaixo.
_ARP = {
    "HOST_A": ("AA:BB:CC:DD:EE:01", 5002),
    "HOST_B": ("AA:BB:CC:DD:EE:03", 5003),
    "HOST_C": ("AA:BB:CC:DD:EE:04", 5004),
}
tabela_mac = {}  # populada dinamicamente no primeiro contato de cada cliente

def _mac_por_vip(vip):
    return _ARP.get(vip, ("FF:FF:FF:FF:FF:FF", 0))[0]

def _porta_por_vip(vip):
    return _ARP.get(vip, ("127.0.0.1", 5002))[1]


# ------------------------------------------------------------------
# CAMADA 2 — Enlace
# Empacota e envia um quadro diretamente ao destinatário via
# canal ruidoso (protocol.py). O servidor responde direto ao
# cliente, sem passar pelo roteador.
# ------------------------------------------------------------------

def enviar_quadro(sock, dados_pacote_dict, mac_destino, endereco_real):
    quadro = Quadro(src_mac=SERVIDOR_MAC, dst_mac=mac_destino,
                    pacote_dict=dados_pacote_dict)
    b = quadro.serializar()
    log_enlace(f"Quadro ({len(b)}b) | {SERVIDOR_MAC} -> {mac_destino}")
    enviar_pela_rede_ruidosa(sock, b, endereco_real)


# ------------------------------------------------------------------
# CAMADA 4 — Transporte (ACK)
# Confirma recebimento de um segmento ao cliente.
# Usa tabela_mac para obter o MAC real — não o MAC do roteador.
# ------------------------------------------------------------------

def enviar_ack(sock, seq_num, vip_destino, endereco_real):
    mac_destino = tabela_mac.get(vip_destino, "FF:FF:FF:FF:FF:FF")
    seg = Segmento(seq_num=seq_num, is_ack=True, payload={})
    pkt = Pacote(src_vip=SERVIDOR_VIP, dst_vip=vip_destino,
                 ttl=64, segmento_dict=seg.to_dict())
    log_transporte(f"Enviando ACK SEQ={seq_num} para {vip_destino} @ {endereco_real}")
    enviar_quadro(sock, pkt.to_dict(), mac_destino, endereco_real)


# ------------------------------------------------------------------
# CAMADA 4 — Transporte (envio confiável)
# Stop-and-Wait com retransmissão, igual ao cliente.
# Cada chamada registra uma fila própria em filas_ack indexada por
# (vip, seq, thread_id) — assim broadcasts simultâneos para clientes
# diferentes não consomem ACKs um do outro.
# ------------------------------------------------------------------

def enviar_confiavel(sock, payload_app, vip_destino, endereco_real, seq_num):
    tid         = threading.get_ident()
    chave       = (vip_destino, seq_num, tid)
    fila_local  = queue.Queue()
    mac_destino = tabela_mac.get(vip_destino, "FF:FF:FF:FF:FF:FF")

    with lock_filas:
        filas_ack[chave] = fila_local

    segmento = Segmento(seq_num=seq_num, is_ack=False, payload=payload_app)
    pacote   = Pacote(src_vip=SERVIDOR_VIP, dst_vip=vip_destino,
                      ttl=64, segmento_dict=segmento.to_dict())

    try:
        for tentativa in range(1, 21):
            log_transporte(f"Enviando SEQ={seq_num} -> {vip_destino} (tentativa {tentativa})")
            enviar_quadro(sock, pacote.to_dict(), mac_destino, endereco_real)

            try:
                seg = fila_local.get(timeout=TIMEOUT_ACK)
                if seg.get('is_ack') and seg.get('seq_num') == seq_num:
                    log_transporte(f"ACK SEQ={seq_num} de {vip_destino} ✓")
                    return True
            except queue.Empty:
                log_transporte(f"TIMEOUT SEQ={seq_num} -> {vip_destino}. Retransmitindo...")
    finally:
        # Garante remoção da fila mesmo em caso de exceção
        with lock_filas:
            filas_ack.pop(chave, None)

    log_transporte(f"FALHA: 10 tentativas para {vip_destino}")
    return False


# ------------------------------------------------------------------
# CAMADA 5 — Aplicação (broadcast)
# Reencaminha a mensagem para todos os clientes exceto o remetente.
# Cada destinatário tem seu próprio contador seq_envio em clientes[vip],
# evitando dessincronização quando múltiplas mensagens são enviadas.
# Roda em thread separada para não bloquear thread_receber.
# ------------------------------------------------------------------

def retransmitir_para_clientes(sock, payload, vip_origem):
    with lock_cl:
        destinatarios = {
            vip: dict(info) for vip, info in clientes.items()
            if vip != vip_origem
        }

    if not destinatarios:
        log_aplicacao("Nenhum outro cliente para reencaminhar.")
        return

    for vip_destino, info in destinatarios.items():
        log_aplicacao(f"Reencaminhando {vip_origem} -> {vip_destino}...")

        with lock_cl:
            seq = clientes[vip_destino].get("seq_envio", 0)

        ok = enviar_confiavel(sock, payload, vip_destino, info['endereco'], seq)

        if ok:
            with lock_cl:
                clientes[vip_destino]["seq_envio"] = 1 - seq

        log_aplicacao(f"{'✓ Entregue' if ok else '✗ Falha'} para {vip_destino}")


def processar_mensagem_aplicacao(sock, payload, vip_origem):
    tipo   = payload.get('type', '?')
    sender = payload.get('sender', vip_origem)
    ts     = payload.get('timestamp', '')

    if tipo == "MSG":
        log_aplicacao(f"💬 [{sender}] ({ts}): {payload.get('message', '')[:60]}")
    elif tipo == "IMG":
        log_aplicacao(f"🖼  [{sender}] ({ts}): imagem recebida")
    elif tipo == "JOIN":
        log_aplicacao(f"🟢 {sender} entrou no chat!")
    elif tipo == "LEAVE":
        log_aplicacao(f"🔴 {sender} saiu do chat!")

    # Broadcast em thread separada — libera thread_receber imediatamente
    threading.Thread(
        target=retransmitir_para_clientes,
        args=(sock, payload, vip_origem),
        daemon=True
    ).start()


# ------------------------------------------------------------------
# Thread de recebimento
# Única consumidora do socket. Desce pelas camadas 2→3→4 e:
#   - ACKs: deposita na fila correta em filas_ack para enviar_confiavel
#   - Dados novos: envia ACK e aciona a camada de aplicação
#   - Duplicatas: reenvia ACK (remetente não recebeu o ACK anterior)
# ------------------------------------------------------------------

def thread_receber(sock):
    sock.settimeout(None)

    while True:
        try:
            dados_brutos, _ = sock.recvfrom(BUFFER_SIZE)

            # Camada 2: verifica CRC
            quadro_dict, integro = Quadro.deserializar(dados_brutos)
            if not integro:
                log_enlace("Quadro CORROMPIDO! Descartando.")
                continue

            # MAC de origem ignorado — é sempre o do roteador após encaminhamento
            log_enlace("Quadro OK ✓")

            # Camada 3
            pacote_dict = quadro_dict['data']
            vip_origem  = pacote_dict.get('src_vip', '?')
            vip_destino = pacote_dict.get('dst_vip', '?')
            ttl         = pacote_dict.get('ttl', 0)
            log_rede(f"{vip_origem} -> {vip_destino} | TTL={ttl}")

            if ttl <= 0 or vip_destino != SERVIDOR_VIP:
                log_rede("Descartado (TTL ou destino).")
                continue

            # Camada 4
            seg_dict = pacote_dict['data']
            seq_num  = seg_dict.get('seq_num', 0)
            is_ack   = seg_dict.get('is_ack', False)

            if is_ack:
                # Deposita nas filas de todos os enviar_confiavel aguardando este ACK
                log_transporte(f"ACK SEQ={seq_num} de {vip_origem}")
                with lock_filas:
                    destinos = [
                        fila for (vip, seq, _), fila in filas_ack.items()
                        if vip == vip_origem and seq == seq_num
                    ]
                for fila in destinos:
                    fila.put(seg_dict)
                continue

            # Registra cliente novo na primeira mensagem recebida.
            # Como o endereço UDP que chega é o do roteador, usa _ARP
            # para descobrir o endereço real do cliente pelo VIP.
            with lock_cl:
                if vip_origem not in clientes:
                    mac_real         = _mac_por_vip(vip_origem)
                    endereco_cliente = ("127.0.0.1", _porta_por_vip(vip_origem))
                    tabela_mac[vip_origem] = mac_real
                    clientes[vip_origem]   = {
                        "endereco":     endereco_cliente,
                        "seq_esperado": 0,
                        "seq_envio":    0
                    }
                    log_aplicacao(f"Novo cliente: {vip_origem} @ {endereco_cliente}")

                info    = clientes[vip_origem]
                seq_esp = info["seq_esperado"]

            log_transporte(f"Segmento SEQ={seq_num} | Esperado={seq_esp}")

            if seq_num == seq_esp:
                # ACK enviado antes do processamento para liberar o cliente rápido
                enviar_ack(sock, seq_num, vip_origem, info['endereco'])
                with lock_cl:
                    clientes[vip_origem]["seq_esperado"] = 1 - seq_esp
                processar_mensagem_aplicacao(sock, seg_dict.get('payload', {}), vip_origem)
            else:
                log_transporte(f"Duplicado SEQ={seq_num}. Reenviando ACK.")
                enviar_ack(sock, seq_num, vip_origem, info['endereco'])

        except Exception as e:
            log_fisica(f"Erro: {e}")


def main():
    print("=" * 60)
    print(f"{VERDE}  SERVIDOR Mini-NET{RESET}")
    print(f"  VIP : {SERVIDOR_VIP} | MAC: {SERVIDOR_MAC}")
    print(f"  Bind: {SERVIDOR_IP}:{SERVIDOR_PORTA}")
    print("=" * 60)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((SERVIDOR_IP, SERVIDOR_PORTA))
    log_fisica(f"Socket UDP em {SERVIDOR_IP}:{SERVIDOR_PORTA}")

    threading.Thread(target=thread_receber, args=(sock,), daemon=True).start()
    log_aplicacao("Pronto para receber conexões.\n")

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print(f"\n{AMARELO}[SERVIDOR] Encerrando...{RESET}")
        sock.close()

if __name__ == "__main__":
    main()
