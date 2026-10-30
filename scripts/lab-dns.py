"""Loopback-only DNS integration for the portable Linux guest.

Resolve using the host's normal resolver; never expose a public DNS listener.
The guest uses 10.0.2.2:10053 via QEMU user networking. Only A/AAAA supported.
"""

import socket
import socketserver
import struct


class DNS(socketserver.BaseRequestHandler):
    def handle(self):
        data, transport = self.request
        try:
            if len(data) < 12 or struct.unpack("!H", data[4:6])[0] != 1:
                return
            offset, labels = 12, []
            while data[offset]:
                length = data[offset]
                if length > 63:
                    return
                offset += 1
                labels.append(data[offset:offset + length].decode("ascii"))
                offset += length
            offset += 1
            kind, cls = struct.unpack("!HH", data[offset:offset + 4])
            end, answers = offset + 4, []
            if kind in (1, 28) and cls == 1:
                family = socket.AF_INET if kind == 1 else socket.AF_INET6
                try:
                    addresses = socket.getaddrinfo(".".join(labels), None, family, socket.SOCK_STREAM)
                    for ip in sorted({row[4][0] for row in addresses})[:8]:
                        packed = socket.inet_pton(family, ip)
                        answers.append(b"\xc0\x0c" + struct.pack("!HHIH", kind, 1, 60, len(packed)) + packed)
                except socket.gaierror:
                    pass
            response = data[:2] + struct.pack("!HHHHH", 0x8180, 1, len(answers), 0, 0) + data[12:end] + b"".join(answers)
            transport.sendto(response, self.client_address)
        except (ValueError, IndexError, UnicodeError, OSError, struct.error):
            return


if __name__ == "__main__":
    with socketserver.ThreadingUDPServer(("127.0.0.1", 10053), DNS) as server:
        server.daemon_threads = True
        server.serve_forever()
