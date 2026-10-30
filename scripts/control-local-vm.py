"""Control the existing folder-contained Linux test VM; install no host services."""

import argparse
import json
from pathlib import Path
import socket
import ssl
import subprocess
import sys

import paramiko


ROOT = Path(__file__).resolve().parents[1] / ".approval-lab" / "portable-vm"


def connect():
    client = paramiko.SSHClient()
    # Trust the host key pinned during provisioning. Never silently replace it.
    client.load_host_keys(str(ROOT / "known_hosts"))
    client.connect("127.0.0.1", port=22322, username="lab", key_filename=str(ROOT / "lab-key"),
                   allow_agent=False, look_for_keys=False, timeout=10, banner_timeout=10)
    return client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "status", "exec", "stop", "upload", "network"])
    parser.add_argument("arguments", nargs="*")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    if args.action == "start":
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 22322)) == 0:
                raise SystemExit("SSH port is already in use; inspect status before starting a VM")
        if not (ROOT / "vm.qcow2").is_file():
            raise SystemExit("Existing provisioned VM disk required")
        command = [str(ROOT / "qemu/qemu-system-x86_64.exe"), "-L", "qemu/share", "-accel", "tcg,thread=multi",
                   "-smp", "2", "-m", "2048", "-display", "none", "-monitor", "none", "-serial", "file:serial.log",
                   "-no-reboot", "-drive", "file=vm.qcow2,if=virtio,format=qcow2", "-cdrom", "seed.iso",
                   "-netdev", "user,id=net0,hostfwd=tcp:127.0.0.1:22322-:22", "-device", "virtio-net-pci,netdev=net0"]
        with (ROOT / "qemu.log").open("ab") as log:
            process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        (ROOT / "process.json").write_text(json.dumps({"pid": process.pid, "ssh_port": 22322}))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as dns_probe:
            try:
                dns_probe.bind(("127.0.0.1", 10053))
                dns_free = True
            except OSError:
                dns_free = False
        if dns_free:
            with (ROOT / "dns.log").open("ab") as log:
                dns = subprocess.Popen([sys.executable, str(Path(__file__).with_name("lab-dns.py"))],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                (ROOT / "dns-process.json").write_text(json.dumps({"pid": dns.pid}))
        # A running guest may still need time to boot; status checks pinned SSH.
        print("Portable VM started. PID:", process.pid)
        return
    client = connect()
    try:
        if args.action == "network":
            # Public CA certificates only; private keys are never exported.
            certificates = [ssl.DER_cert_to_PEM_cert(data) for data, encoding, trust in ssl.enum_certificates("ROOT") if encoding == "x509_asn"]
            with client.open_sftp() as transfer:
                with transfer.open("/home/lab/windows-public-roots.crt", "w") as output:
                    output.write("".join(certificates))
            command = "sudo cp /home/lab/windows-public-roots.crt /usr/local/share/ca-certificates/host-lab-roots.crt; sudo update-ca-certificates; sudo resolvectl dns ens3 10.0.2.2:10053"
            _, output, errors = client.exec_command(command, timeout=45)
            print(output.read().decode(errors="replace"), end="")
            print(errors.read().decode(errors="replace"), end="", file=sys.stderr)
            raise SystemExit(output.channel.recv_exit_status())
        if args.action == "upload":
            if len(args.arguments) != 2:
                parser.error("upload needs local_path and guest_path")
            with client.open_sftp() as transfer:
                transfer.put(args.arguments[0], args.arguments[1])
            return
        command = "uname -a; uptime" if args.action == "status" else "sudo poweroff" if args.action == "stop" else args.arguments[0] if len(args.arguments) == 1 else None
        if command is None:
            parser.error("exec needs one quoted guest shell command")
        _, output, errors = client.exec_command(command, timeout=45)
        print(output.read().decode(errors="replace"), end="")
        print(errors.read().decode(errors="replace"), end="", file=sys.stderr)
        if args.action != "stop":
            raise SystemExit(output.channel.recv_exit_status())
    finally:
        client.close()


if __name__ == "__main__":
    main()
