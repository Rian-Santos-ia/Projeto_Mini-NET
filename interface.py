"""
interface.py - Interface Web para o Cliente Mini-NET.

Uso:
		python3 interface.py <VIP> <MAC> <PORTA_UDP> <PORTA_HTTP>

Exemplo:
		python3 interface.py HOST_A AA:BB:CC:DD:EE:01 5002 8080
		python3 interface.py HOST_B AA:BB:CC:DD:EE:03 5003 8081
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import json
import time
import threading
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

from client import ClienteMiniNET, log_aplicacao, VERMELHO, AMARELO, VERDE, RESET

# ===================== ARGUMENTOS =====================
def uso():
		print("Uso: python3 interface.py <VIP> <MAC> <PORTA_UDP> <PORTA_HTTP>")
		print("Ex:  python3 interface.py HOST_A AA:BB:CC:DD:EE:01 5002 8080")
		sys.exit(1)

if len(sys.argv) != 5:
		uso()

CLIENTE_VIP   = sys.argv[1]
CLIENTE_MAC   = sys.argv[2]
CLIENTE_PORTA = int(sys.argv[3])
HTTP_PORTA    = int(sys.argv[4])

# ===================== HTML =====================
HTML_PATH = os.path.join(os.path.dirname(__file__), "index.html")

def carregar_html():
		with open(HTML_PATH, "r", encoding="utf-8") as f:
				return f.read().encode("utf-8")

# ===================== HANDLER HTTP =====================
def criar_handler(cliente):
		"""Cria o Handler com acesso à instância do cliente via closure."""

		class Handler(BaseHTTPRequestHandler):

				def log_message(self, format, *args):
						pass  # silencia logs do http.server

				def do_GET(self):
						parsed = urlparse(self.path)

						if parsed.path == '/':
								self._responder(200, 'text/html', carregar_html())

						elif parsed.path == '/info':
								info = json.dumps({"vip": cliente.CLIENTE_VIP}).encode()
								self._responder(200, 'application/json', info)

						elif parsed.path == '/messages':
								params = parse_qs(parsed.query)
								since  = int(params.get('since', ['0'])[0])
								novas  = cliente.mensagens[since:]
								self._responder(200, 'application/json',
																json.dumps(novas).encode())
								
						elif self.path == '/online':
							# Retorna a lista de VIPs conectados ao servidor.
							# O cliente conhece apenas a si mesmo, então inclui o próprio VIP
							# mais os remetentes que já apareceram em self.mensagens.
							vistos = {m['sender'] for m in cliente.mensagens if not m['own']}
							vistos.add(cliente.CLIENTE_VIP)
							payload = json.dumps({"online": sorted(vistos)}).encode()
							self._responder(200, 'application/json', payload)

						else:
								self._responder(404, 'text/plain', b'Not found')

				def do_POST(self):
					if self.path == '/send':
							length = int(self.headers.get('Content-Length', 0))
							body   = json.loads(self.rfile.read(length))
							texto  = body.get('message', '').strip()
							tipo   = body.get('type', 'MSG')          # ← novo
							fname  = body.get('filename', '')          # ← novo

							if not texto:
									self._responder(400, 'application/json', b'{"ok": false}')
									return

							timestamp = time.strftime("%H:%M:%S")
							payload   = {
									"type":      tipo,                     # ← passa o tipo real
									"sender":    cliente.CLIENTE_VIP,
									"message":   texto,
									"filename":  fname,                    # ← novo
									"timestamp": timestamp
							}

							msg_idx = len(cliente.mensagens)
							cliente.mensagens.append({
									"sender":    cliente.CLIENTE_VIP,
									"message":   texto,
									"filename":  fname,
									"timestamp": timestamp,
									"type":      tipo,
									"own":       True,
									"status":    "enviando"
							})

							threading.Thread(
									target=cliente.enviar_confiavel,
									args=(payload, msg_idx),
									daemon=True
							).start()

							self._responder(200, 'application/json', b'{"ok": true}')

				def _responder(self, code, content_type, body):
						self.send_response(code)
						self.send_header('Content-Type', content_type)
						self.send_header('Content-Length', len(body))
						self.end_headers()
						self.wfile.write(body)

		return Handler


# ===================== MAIN =====================
def main():
		cliente = ClienteMiniNET(
				cliente_vip=CLIENTE_VIP,
				cliente_mac=CLIENTE_MAC,
				cliente_porta=CLIENTE_PORTA
		)

		# Envia JOIN em background
		join_payload = {
				"type":      "JOIN",
				"sender":    CLIENTE_VIP,
				"message":   f"{CLIENTE_VIP} entrou no chat",
				"timestamp": time.strftime("%H:%M:%S")
		}
		threading.Thread(
				target=cliente.enviar_confiavel,
				args=(join_payload,),
				daemon=True
		).start()

		# Inicia HTTP
		handler  = criar_handler(cliente)
		servidor = HTTPServer(('127.0.0.1', HTTP_PORTA), handler)
		print(f"\n  {VERDE}[WEB]{RESET} {CLIENTE_VIP} disponível em "
					f"http://127.0.0.1:{HTTP_PORTA}\n")

		try:
				servidor.serve_forever()
		except KeyboardInterrupt:
				print(f"\n{AMARELO}[{CLIENTE_VIP}] Encerrando...{RESET}")
				servidor.shutdown()
				cliente.sock.close()


if __name__ == "__main__":
		main()
