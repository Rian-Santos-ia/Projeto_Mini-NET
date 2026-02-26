"""
protocolo.py - Biblioteca base para o Projeto Mini-NET

ESTE ARQUIVO DEVE SER IMPORTADO PELOS ALUNOS, NÃO MODIFICADO.
Ele contém:
1. Estruturas de Dados para as Camadas (Transporte, Rede, Enlace).
2. Funções de utilidade para cálculo de CRC (Integridade).
3. O simulador de canal físico (perda e corrupção de pacotes).
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import json
import zlib
import random
import time
import socket

# --- CONFIGURAÇÃO DA SIMULAÇÃO ---
# Chance de um pacote ser totalmente perdido (0.0 a 1.0)
PROBABILIDADE_PERDA = 0.2  # 20%

# Chance de um pacote sofrer corrupção de bits (0.0 a 1.0)
PROBABILIDADE_CORRUPCAO = 0.2 # 20%

# Tempo de atraso simulado na rede (latência)
LATENCIA_MIN = 0.1
LATENCIA_MAX = 0.5

# =================================================================
# CAMADA 4: TRANSPORTE (Segmento)
# =================================================================
class Segmento:
    """
    Representa a PDU (Protocol Data Unit) da Camada de Transporte.
    Responsável por: Confiabilidade (SEQ/ACK) e Portas (aqui simplificado).
    """
    def __init__(self, seq_num, is_ack, payload):
        self.seq_num = seq_num  # Número de sequência (0 ou 1 para Stop-and-Wait)
        self.is_ack = is_ack    # Booleano: É um ACK ou são dados?
        self.payload = payload  # O JSON da aplicação (dicionário)

    def to_dict(self):
        """Converte o objeto em dicionário para serialização."""
        return {
            "seq_num": self.seq_num,
            "is_ack": self.is_ack,
            "payload": self.payload
        }

# =================================================================
# CAMADA 3: REDE (Pacote)
# =================================================================
class Pacote:
    """
    Representa a PDU da Camada de Rede.
    Responsável por: Endereçamento Lógico (VIP) e Roteamento (TTL).
    """
    def __init__(self, src_vip, dst_vip, ttl, segmento_dict):
        self.src_vip = src_vip  # IP Virtual de Origem (ex: "HOST_A")
        self.dst_vip = dst_vip  # IP Virtual de Destino (ex: "SERVIDOR")
        self.ttl = ttl          # Time To Live
        self.data = segmento_dict # O Dicionário do Segmento (Payload)

    def to_dict(self):
        return {
            "src_vip": self.src_vip,
            "dst_vip": self.dst_vip,
            "ttl": self.ttl,
            "data": self.data
        }

# =================================================================
# CAMADA 2: ENLACE (Quadro/Frame)
# =================================================================
class Quadro:
    """
    Representa a PDU da Camada de Enlace.
    Responsável por: Endereçamento Físico (MAC) e Verificação de Erro (FCS/CRC).
    """
    def __init__(self, src_mac, dst_mac, pacote_dict):
        self.src_mac = src_mac  # Endereço MAC Origem
        self.dst_mac = dst_mac  # Endereço MAC Destino
        self.data = pacote_dict # O Dicionário do Pacote (Payload)
        self.fcs = 0            # Frame Check Sequence (CRC32)

    def serializar(self):
        """
        Prepara o quadro para envio:
        1. Gera o JSON.
        2. Calcula o CRC32.
        3. Anexa o CRC.
        4. Retorna em bytes.
        """
        # Cria estrutura temporária sem o FCS para calcular o hash
        dados_para_calculo = {
            "src_mac": self.src_mac,
            "dst_mac": self.dst_mac,
            "data": self.data,
            "fcs": 0
        }

        # Converte para bytes de forma ordenada para garantir determinismo
        json_str = json.dumps(dados_para_calculo, sort_keys=True)
        bytes_dados = json_str.encode('utf-8')

        # Calcula o CRC32
        crc = zlib.crc32(bytes_dados)

        # Cria o dicionário final com o CRC correto
        dados_finais = dados_para_calculo.copy()
        dados_finais['fcs'] = crc

        return json.dumps(dados_finais).encode('utf-8')

    @staticmethod
    def deserializar(bytes_recebidos):
        """
        Recebe bytes crus da rede e tenta reconstruir o Quadro.
        Retorna: (Dicionário do Quadro, Booleano indicando se é válido)
        """
        try:
            # Tenta decodificar o JSON
            dados_dict = json.loads(bytes_recebidos.decode('utf-8'))

            # Extrai o FCS que veio no pacote
            fcs_recebido = dados_dict.get('fcs', 0)

            # Prepara para recalcular o CRC (zera o FCS localmente)
            dados_para_calculo = dados_dict.copy()
            dados_para_calculo['fcs'] = 0

            # Recalcula
            json_str = json.dumps(dados_para_calculo, sort_keys=True)
            fcs_calculado = zlib.crc32(json_str.encode('utf-8'))

            # Verifica integridade
            if fcs_recebido == fcs_calculado:
                return dados_dict, True  # Quadro Íntegro
            else:
                return dados_dict, False # Quadro Corrompido (Erro de Bit)

        except (json.JSONDecodeError, UnicodeDecodeError):
            # Se o JSON quebrou, é porque houve corrupção grave
            return None, False

# =================================================================
# CAMADA 1: FÍSICA (Simulador de Canal)
# =================================================================
def enviar_pela_rede_ruidosa(socket_udp, bytes_dados, endereco_destino):
    """
    Simula o meio físico (cabos/ar).
    Deve ser usada NO LUGAR de socket.sendto().

    Parâmetros:
      socket_udp: O socket configurado.
      bytes_dados: O quadro serializado (bytes).
      endereco_destino: Tupla (IP, Porta) real do destino.
    """
    print(f"   [FÍSICA] Tentando transmitir {len(bytes_dados)} bytes...")

    # 1. SIMULAÇÃO DE PERDA (Congestionamento)
    if random.random() < PROBABILIDADE_PERDA:
        print("   [FÍSICA] O pacote foi perdido na rede (Drop).")
        return # Simplesmente não envia, simulando perda total.

    # 2. SIMULAÇÃO DE CORRUPÇÃO (Ruído Elétrico)
    # Copia os bytes para poder modificar (bytes são imutáveis em Python)
    array_dados = bytearray(bytes_dados)

    if random.random() < PROBABILIDADE_CORRUPCAO:
        print("   [FÍSICA] Interferência eletromagnética! Bits trocados.")

        # Escolhe um byte aleatório para corromper
        if len(array_dados) > 0:
            pos = random.randint(0, len(array_dados) - 1)
            # Operação XOR com 0xFF inverte todos os bits daquele byte
            array_dados[pos] = array_dados[pos] ^ 0xFF

    # 3. LATÊNCIA (Atraso de propagação)
    time.sleep(random.uniform(LATENCIA_MIN, LATENCIA_MAX))

    # 4. ENVIO REAL
    socket_udp.sendto(bytes(array_dados), endereco_destino)
    print("   [FÍSICA] Sinal enviado para o meio físico.")