# Mini-NET: Projeto Integrador — Redes de Computadores

## Descrição

Implementação de uma pilha de protocolos de rede para um sistema de chat sobre UDP, simulando as camadas do modelo OSI/TCP-IP.

O sistema opera sobre um **canal propositalmente defeituoso** (com perda de pacotes e corrupção de dados) e implementa mecanismos para garantir a entrega confiável das mensagens.

## Arquitetura

```
┌─────────────┐         ┌─────────────┐         ┌─────────────┐
│   CLIENT     │  ──→   │   ROTEADOR   │  ──→   │   SERVIDOR   │
│  (HOST_A)    │  ←──   │              │  ←──   │              │
│  porta 5002  │         │  porta 6000  │         │  porta 5001  │
└─────────────┘         └─────────────┘         └─────────────┘
```

### Camadas Implementadas

| Camada | PDU | Responsabilidade | Arquivo |
|--------|-----|-----------------|---------|
| 5 - Aplicação | JSON | Formato das mensagens do chat | client.py / server.py |
| 4 - Transporte | Segmento | Stop-and-Wait, SEQ/ACK, Timeout, Retransmissão | client.py / server.py |
| 3 - Rede | Pacote | Endereçamento Virtual (VIP), TTL, Roteamento | roteador.py |
| 2 - Enlace | Quadro | Endereçamento MAC, CRC32 (FCS) | protocolo.py |
| 1 - Física | Bits | Simulação de perda, corrupção e latência | protocolo.py |

## Arquivos

- **`protocolo.py`** — Biblioteca base (fornecida pelo professor). Contém as classes `Segmento`, `Pacote`, `Quadro` e a função `enviar_pela_rede_ruidosa`.
- **`server.py`** — Servidor do chat. Recebe e exibe mensagens, pode responder aos clientes.
- **`client.py`** — Cliente do chat. Envia mensagens ao servidor via roteador.
- **`roteador.py`** — Roteador intermediário. Recebe pacotes, consulta a tabela de rotas e encaminha.

## Como Executar

### Pré-requisitos
- Python 3.8+
- Apenas bibliotecas padrão (nenhuma instalação extra necessária)

### Passo a Passo

Abra **3 terminais** separados e execute na seguinte ordem:

**Terminal 1 — Roteador:**
```bash
python3 roteador.py
```

**Terminal 2 — Servidor:**
```bash
python3 server.py
```

**Terminal 3 — Cliente:**
```bash
python3 client.py
```

Depois, basta digitar mensagens no terminal do **Cliente**. Elas serão roteadas até o **Servidor**. O servidor também pode enviar mensagens de volta.

Para encerrar o cliente, digite `sair`.

### Múltiplos Clientes

Para adicionar mais clientes, edite as constantes no `client.py`:

```python
CLIENTE_PORTA = 5003        # Porta diferente
CLIENTE_VIP = "HOST_B"      # VIP diferente
CLIENTE_MAC = "AA:BB:CC:DD:EE:03"  # MAC diferente
```

Os VIPs `HOST_A`, `HOST_B` e `HOST_C` já estão pré-configurados na tabela de roteamento.

## Configuração da Simulação de Falhas

No arquivo `protocolo.py`, é possível ajustar:

```python
PROBABILIDADE_PERDA = 0.2      # 20% de chance de pacote perdido
PROBABILIDADE_CORRUPCAO = 0.2  # 20% de chance de corrupção de bits
```

Para teste de estresse, aumente para 0.5 (50%).

## Logs Coloridos

O sistema usa cores no terminal para diferenciar as camadas:

- 🔴 **Vermelho** — Camada Física (erros, perda)
- 🟣 **Magenta** — Camada de Enlace (CRC, MACs)
- 🔵 **Azul** — Camada de Rede (VIP, TTL, roteamento)
- 🟡 **Amarelo** — Camada de Transporte (SEQ, ACK, timeout, retransmissão)
- 🟢 **Verde** — Camada de Aplicação (mensagens do chat)

## Formato JSON da Aplicação

```json
{
    "type": "MSG",
    "sender": "HOST_A",
    "message": "Olá, servidor!",
    "timestamp": "14:30:25"
}
```

Tipos suportados: `MSG` (mensagem), `JOIN` (entrada no chat), `LEAVE` (saída do chat).