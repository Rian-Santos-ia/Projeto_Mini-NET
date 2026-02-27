# Mini-NET Chat — Projeto Integrador de Redes de Computadores

## Descrição

Implementação de uma pilha de protocolos de rede para um sistema de **chat em tempo real** sobre UDP, simulando as camadas do modelo OSI/TCP-IP.

O sistema opera sobre um **canal propositalmente defeituoso** (com perda de pacotes e corrupção de dados) e implementa mecanismos para garantir a entrega confiável das mensagens. Cada cliente expõe uma **interface web** acessível pelo navegador.

---

## Alunos

Caio Lucca dos Santos Oliveira - 202403896

Rian de Souza Santos - 202403923

---

## Como Executar

### Pré-requisitos
- Python 3.8+
- Um navegador de internet qualquer
- Apenas bibliotecas padrão (nenhuma instalação extra necessária)

### Execução

```bash
python main.py
```

O `main.py` detecta automaticamente o emulador de terminal disponível e abre uma janela separada para cada componente — **Roteador**, **Servidor**, **HOST_A**, **HOST_B** — cada uma com seus logs isolados.

Em seguida, acesse no navegador:

```
HOST_A -> http://127.0.0.1:8080
HOST_B -> http://127.0.0.1:8081
```

Abra cada endereço em uma aba diferente para simular os dois participantes do chat.

---

# Vídeo

O vídeo de demonstração está disponível nesse [link](https://drive.google.com/drive/folders/1avFgB1uCh81HbiZ4BBKPHUTwPl7npq4z?usp=sharing).

---

## Arquitetura

```

┌──────────────────┐        ┌─────────────┐        ┌──────────────┐
│  CLIENT (HOST_A) │  ──→   │   ROTEADOR  │  ──→   │   SERVIDOR   │
│  rede: 5002      │  ←──   │  porta 6000 │  ←──   │  porta 5001  │
│  web:  8080      │        └─────────────┘        └──────────────┘
├──────────────────┤
│  CLIENT (HOST_B) │
│  rede: 5003      │
│  web:  8081      │
└──────────────────┘

```

Todo o tráfego de rede passa pelo roteador, que consulta sua tabela de rotas estática e encaminha para o destinatário real. O servidor faz o broadcast das mensagens diretamente aos clientes, sem passar novamente pelo roteador.

---

## Camadas Implementadas

| Camada | PDU | Responsabilidade | Arquivo |
|--------|-----|-----------------|---------|
| 5 — Aplicação | JSON | Formato das mensagens, broadcast entre clientes | `client.py` / `server.py` / `interface.py` |
| 4 — Transporte | Segmento | Stop-and-Wait, SEQ/ACK, timeout, retransmissão | `client.py` / `server.py` |
| 3 — Rede | Pacote | Endereçamento virtual (VIP), TTL, roteamento | `roteador.py` |
| 2 — Enlace | Quadro | Endereçamento MAC, integridade por CRC32 | `protocol.py` |
| 1 — Física | Bytes | Simulação de perda, corrupção e latência | `protocol.py` |

---

## Arquivos

| Arquivo | Descrição |
|---------|-----------|
| `main.py` | Ponto de entrada — abre um terminal separado para cada componente |
| `protocol.py` | Biblioteca base (fornecida pelo professor): `Segmento`, `Pacote`, `Quadro`, `enviar_pela_rede_ruidosa` |
| `server.py` | Servidor do chat: recebe mensagens e faz broadcast para todos os clientes conectados |
| `client.py` | Lógica de rede do cliente: gerencia envio confiável, recebimento e histórico de mensagens |
| `interface.py` | Interface HTTP do cliente: serve o frontend e expõe `/send`, `/messages`, `/info`, `/online` |
| `roteador.py` | Roteador intermediário: decrementa TTL, consulta tabela de rotas e reencaminha quadros |
| `index.html` | Frontend do chat: interface web com polling, status de entrega e envio de imagens |

---

## Adicionando um Novo Cliente

1. Inclua uma entrada em `HOSTS` no `main.py`:
```python
("HOST_C", "AA:BB:CC:DD:EE:04", 5004, 8082),
```

2. Adicione o VIP em `TABELA_ROTEAMENTO` e `TABELA_ARP` no `roteador.py`:
```python
"HOST_C": ("127.0.0.1", 5004),  # TABELA_ROTEAMENTO
"HOST_C": "AA:BB:CC:DD:EE:04",  # TABELA_ARP
```

3. Adicione em `_ARP` no `server.py`:
```python
"HOST_C": ("AA:BB:CC:DD:EE:04", 5004),
```


---

## Configuração do Canal Ruidoso

Em `protocol.py`, ajuste as probabilidades de falha da camada física:

```python
PROBABILIDADE_PERDA     = 0.2   # 20% de chance de pacote perdido
PROBABILIDADE_CORRUPCAO = 0.2   # 20% de chance de corrupção de bits
```

Para demonstrar a resiliência do protocolo, aumente para `0.5` (50%) e observe as retransmissões em tempo real na interface web — o ícone de status alterna entre 🔄 *retransmitindo* e ✓✓ *entregue* conforme o Stop-and-Wait opera.

---

## Interface Web

Cada cliente possui uma interface acessível pelo navegador com:

- **Mensagens em tempo real** via polling a cada 1 segundo
- **Status de entrega** por mensagem: 🕐 enviando → 🔄 retransmitindo → ✓✓ entregue / ✗ falha
- **Presentes no chat** exibidos no cabeçalho, atualizados a cada 3 segundos
- **Envio de imagens** via botão 📎 (comprimidas automaticamente para caber no limite UDP)

---

## Logs por Camada

Cada janela de terminal exibe os logs coloridos do seu componente:


| Cor | Camada |
| :-- | :-- |
| 🔴 Vermelho | Física — bytes transmitidos, erros |
| 🟣 Magenta | Enlace — CRC, endereços MAC |
| 🔵 Azul | Rede — VIP, TTL, roteamento |
| 🟡 Amarelo | Transporte — SEQ, ACK, timeout, retransmissão |
| 🟢 Verde | Aplicação — mensagens do chat |


---

## Formato das Mensagens (Camada de Aplicação)

```json
{
    "type":      "MSG",
    "sender":    "HOST_A",
    "message":   "olá!",
    "timestamp": "14:30:25"
}
```

| Tipo | Descrição |
| :-- | :-- |
| `MSG` | Mensagem de texto |
| `IMG` | Imagem em base64 (JPEG comprimido) |
| `JOIN` | Notificação de entrada no chat |
| `LEAVE` | Notificação de saída do chat |

```
