# client.py
# Lógica de rede do cliente Mini-NET.
# Este módulo é importado pela interface.py, que instancia ClienteMiniNET
# e expõe seus dados via servidor HTTP.

import socket
import threading
import queue
from protocol import Segmento, Pacote, Quadro, enviar_pela_rede_ruidosa

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


# Endereço do roteador — todo tráfego de saída passa por ele
ROTEADOR_IP    = "127.0.0.1"
ROTEADOR_PORTA = 6000

BUFFER_SIZE = 65536  # máximo UDP (~65KB), necessário para suportar envio de imagens
TIMEOUT_ACK = 3.0    # segundos aguardando ACK antes de retransmitir (Stop-and-Wait)

# Códigos ANSI para colorir os logs por camada no terminal
VERMELHO = "\033[91m"; AMARELO = "\033[93m"; VERDE  = "\033[92m"
AZUL     = "\033[94m"; MAGENTA = "\033[95m"; RESET  = "\033[0m"

def log_fisica(m):     print(f"   {VERMELHO}[FÍSICA]{RESET} {m}")
def log_enlace(m):     print(f"  {MAGENTA}[ENLACE]{RESET} {m}")
def log_rede(m):       print(f"  {AZUL}[REDE]{RESET} {m}")
def log_transporte(m): print(f"  {AMARELO}[TRANSPORTE]{RESET} {m}")
def log_aplicacao(m):  print(f"  {VERDE}[APLICAÇÃO]{RESET} {m}")


class ClienteMiniNET:
    """
    Representa um cliente na rede Mini-NET.

    Gerencia as camadas 2 (enlace), 3 (rede) e 4 (transporte) para
    envio e recebimento de mensagens via UDP com entrega confiável
    usando Stop-and-Wait com retransmissão.

    Instanciado pela interface.py com VIP, MAC e porta vindos
    dos argumentos de linha de comando.
    """

    def __init__(self, cliente_vip, cliente_mac, cliente_porta,
                 destino_vip="SERVIDOR", destino_mac="AA:BB:CC:DD:EE:02"):
        # Identidade deste cliente na rede
        self.CLIENTE_VIP   = cliente_vip
        self.CLIENTE_MAC   = cliente_mac
        self.CLIENTE_PORTA = cliente_porta

        # Destino padrão de toda mensagem enviada (o servidor de chat)
        self.DESTINO_VIP = destino_vip
        self.DESTINO_MAC = destino_mac

        # Contadores de sequência Stop-and-Wait (alternam entre 0 e 1)
        self.seq_envio    = 0  # próximo SEQ a enviar
        self.seq_esperado = 0  # próximo SEQ esperado ao receber

        self.lock      = threading.Lock()  # protege seq_envio contra acesso concorrente
        self.fila_acks = queue.Queue()     # ACKs recebidos → consumidos por enviar_confiavel

        # Histórico de mensagens lido pela interface.py para exibir no navegador
        self.mensagens = []

        # Socket UDP que representa este host na rede simulada
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", self.CLIENTE_PORTA))

        # Thread de recebimento roda em paralelo para não bloquear o envio
        threading.Thread(target=self._thread_receber, daemon=True).start()
        log_aplicacao(f"Cliente {self.CLIENTE_VIP} iniciado na porta {self.CLIENTE_PORTA}")

    # ------------------------------------------------------------------
    # CAMADA 2 — Enlace
    # Empacota o pacote numa Quadro com MACs de origem/destino,
    # calcula CRC e envia pelo canal ruidoso (protocol.py).
    # ------------------------------------------------------------------

    def _enviar_quadro(self, dados_pacote_dict, mac_destino, endereco_real):
        quadro       = Quadro(src_mac=self.CLIENTE_MAC, dst_mac=mac_destino,
                              pacote_dict=dados_pacote_dict)
        bytes_quadro = quadro.serializar()
        log_enlace(f"Quadro ({len(bytes_quadro)}b) | {self.CLIENTE_MAC} -> {mac_destino}")
        # Passa pelo canal ruidoso definido em protocol.py,
        # que pode descartar ou corromper o quadro aleatoriamente
        enviar_pela_rede_ruidosa(self.sock, bytes_quadro, endereco_real)

    # ------------------------------------------------------------------
    # CAMADA 4 — Transporte (envio)
    # Implementa Stop-and-Wait: envia um segmento e aguarda ACK.
    # Retransmite até 10 vezes em caso de timeout ou ACK errado.
    # msg_idx aponta para self.mensagens para atualizar o status
    # de entrega exibido pela interface.py no navegador.
    # ------------------------------------------------------------------

    def enviar_confiavel(self, payload_app, msg_idx=None):
        with self.lock:
            seq_atual = self.seq_envio

        segmento = Segmento(seq_num=seq_atual, is_ack=False, payload=payload_app)
        pacote   = Pacote(src_vip=self.CLIENTE_VIP, dst_vip=self.DESTINO_VIP,
                          ttl=64, segmento_dict=segmento.to_dict())

        for tentativa in range(1, 21):
            log_transporte(f"Enviando SEQ={seq_atual} (tentativa {tentativa})")
            self._enviar_quadro(pacote.to_dict(), self.DESTINO_MAC,
                                (ROTEADOR_IP, ROTEADOR_PORTA))
            try:
                seg = self.fila_acks.get(timeout=TIMEOUT_ACK)
                if seg.get('seq_num') == seq_atual:
                    log_transporte(f"ACK SEQ={seq_atual} ✓")
                    with self.lock:
                        self.seq_envio = 1 - self.seq_envio  # alterna 0↔1
                    if msg_idx is not None:
                        self.mensagens[msg_idx]['status'] = 'entregue'
                    return True
                else:
                    log_transporte(f"ACK inesperado seq={seg.get('seq_num')}")
            except queue.Empty:
                log_transporte(f"TIMEOUT! Retransmitindo SEQ={seq_atual}...")
                if msg_idx is not None:
                    self.mensagens[msg_idx]['status'] = 'retransmitindo'

        if msg_idx is not None:
            self.mensagens[msg_idx]['status'] = 'falha'
        log_transporte(f"FALHA após 10 tentativas para SEQ={seq_atual}")
        return False

    # ------------------------------------------------------------------
    # CAMADA 4 — Transporte (ACK)
    # Confirma ao remetente que o segmento de número seq_num foi recebido.
    # ------------------------------------------------------------------

    def _enviar_ack(self, seq_num, vip_destino, mac_destino, endereco):
        seg_ack = Segmento(seq_num=seq_num, is_ack=True, payload={})
        pkt_ack = Pacote(src_vip=self.CLIENTE_VIP, dst_vip=vip_destino,
                         ttl=64, segmento_dict=seg_ack.to_dict())
        log_transporte(f"Enviando ACK SEQ={seq_num}")
        self._enviar_quadro(pkt_ack.to_dict(), mac_destino, endereco)

    # ------------------------------------------------------------------
    # Thread de recebimento
    # Roda em paralelo ao envio. Processa cada quadro recebido descendo
    # pelas camadas 2→3→4→5 e:
    #   - Se for ACK: deposita em self.fila_acks para enviar_confiavel consumir
    #   - Se for dado novo: envia ACK e adiciona em self.mensagens
    #   - Se for duplicata: reenvia ACK sem adicionar (idempotência)
    # ------------------------------------------------------------------

    def _thread_receber(self):
        while True:
            try:
                dados_brutos, endereco = self.sock.recvfrom(BUFFER_SIZE)

                # Camada 2: verifica integridade pelo CRC
                quadro_dict, integro = Quadro.deserializar(dados_brutos)
                if not integro:
                    log_enlace("Quadro CORROMPIDO! Descartando.")
                    continue

                mac_remetente = quadro_dict.get('src_mac', 'UNKNOWN')
                log_enlace(f"Quadro OK ✓ | MAC={mac_remetente}")

                # Camada 3: verifica TTL e se o pacote é para este host
                pacote_dict = quadro_dict['data']
                vip_origem  = pacote_dict.get('src_vip', '?')
                vip_destino = pacote_dict.get('dst_vip', '?')
                ttl         = pacote_dict.get('ttl', 0)
                log_rede(f"{vip_origem} -> {vip_destino} | TTL={ttl}")

                if ttl <= 0 or vip_destino != self.CLIENTE_VIP:
                    log_rede("Pacote descartado (TTL ou destino inválido).")
                    continue

                # Camada 4: distingue ACK de dado
                seg_dict = pacote_dict['data']
                seq_num  = seg_dict.get('seq_num', 0)
                is_ack   = seg_dict.get('is_ack', False)

                if is_ack:
                    # Só deposita na fila se o SEQ for relevante (0 ou 1)
                    if seg_dict.get('seq_num') in (0, 1):
                        log_transporte(f"ACK SEQ={seq_num} -> fila")
                        self.fila_acks.put(seg_dict)
                    continue

                log_transporte(f"Segmento SEQ={seq_num} | Esperado={self.seq_esperado}")

                if seq_num == self.seq_esperado:
                    self._enviar_ack(seq_num, vip_origem, mac_remetente, endereco)
                    self.seq_esperado = 1 - self.seq_esperado  # alterna 0↔1

                    # Camada 5: entrega à aplicação — interface.py lê self.mensagens
                    payload = seg_dict.get('payload', {})
                    self.mensagens.append({
                        "sender":    payload.get('sender',    vip_origem),
                        "message":   payload.get('message',   ''),
                        "filename":  payload.get('filename',  ''),
                        "timestamp": payload.get('timestamp', ''),
                        "type":      payload.get('type',      'MSG'),
                        "own":       False,
                        "status":    "entregue"
                    })
                    log_aplicacao(f"[{payload.get('sender')}]: {payload.get('message', '📎 imagem')[:60]}")
                else:
                    # Duplicata: ACK já foi enviado antes, reenvia para garantir
                    log_transporte(f"Duplicado SEQ={seq_num}. Reenviando ACK.")
                    self._enviar_ack(seq_num, vip_origem, mac_remetente, endereco)

            except Exception as e:
                log_fisica(f"Erro: {e}")
