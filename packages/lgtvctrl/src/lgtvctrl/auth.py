"""Authentication and pairing with LG webOS TV."""

import asyncio
import json
import re
import socket
import string
import subprocess
import urllib.parse
import urllib.request
from xml.parsers import expat

from lgtvctrl import betterdisplay, platforms
from lgtvctrl.config import CONFIG_DIR, CONFIG_FILE, KEYFILE_PATH, Config, read_json

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
SSDP_ST = "urn:lge-com:service:webos-second-screen:1"
SSDP_MX = 2

MAC_RE = re.compile(r"(?i)\b([0-9a-f]{1,2}(?:[:-][0-9a-f]{1,2}){5})\b")


async def ainput(prompt: str) -> str:
    return (await asyncio.to_thread(input, prompt)).strip()


def read_config() -> dict:
    return read_json(CONFIG_FILE)


def write_config(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2) + "\n")


IPV4_OCTETS = 4
IPV4_OCTET_MAX = 255

MAC_OCTETS = 6
MAC_OCTET_MAX_DIGITS = 2

# UPnP LOCATION URLs are fetched over plain HTTP; anything else is a
# hostile or unsupported responder.
DESCRIPTION_SCHEME = "http"

SSDP_RECV_BYTES = 4096
DEFAULT_TV_NAME = "LG TV"


def validate_ipv4(ip: str) -> bool:
    try:
        octets = [int(part) for part in ip.split(".")]
    except ValueError:
        return False
    return len(octets) == IPV4_OCTETS and all(
        0 <= octet <= IPV4_OCTET_MAX for octet in octets
    )


UPNP_NS = "urn:schemas-upnp-org:device-1-0"
DESCRIPTION_MAX_BYTES = 64 * 1024


def _parse_device_description(xml_text: str) -> tuple[str | None, str | None]:
    """Read friendlyName and modelNumber from a UPnP device description.

    The document comes from whatever answered an SSDP multicast, so any device
    on the network can supply it. Entity declarations are refused outright:
    ElementTree does not resolve external entities, but it does expand internal
    ones, which is enough for a billion-laughs denial of service. Only the two
    fields needed are read, so a full document model is never built.
    """
    wanted = {f"{UPNP_NS} friendlyName", f"{UPNP_NS} modelNumber"}
    found: dict[str, list[str]] = {}
    path: list[str] = []

    def start(name: str, _attrs: dict[str, str]) -> None:
        path.append(name)

    def end(_name: str) -> None:
        path.pop()

    def characters(data: str) -> None:
        if path and path[-1] in wanted:
            found.setdefault(path[-1], []).append(data)

    def reject_entity(*_args: object, **_kwargs: object) -> None:
        raise ValueError("entity declarations are not accepted")

    parser = expat.ParserCreate(namespace_separator=" ")
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = characters
    parser.EntityDeclHandler = reject_entity

    try:
        parser.Parse(xml_text, True)
    except (expat.ExpatError, ValueError):
        return None, None

    def field(local: str) -> str | None:
        text = "".join(found.get(f"{UPNP_NS} {local}", [])).strip()
        return text or None

    return field("friendlyName"), field("modelNumber")


def _fetch_device_info(location_url: str) -> tuple[str | None, str | None]:
    """Fetch and read a UPnP description advertised in an SSDP response.

    The URL comes from a LOCATION header supplied by whatever answered the
    multicast, so it is attacker-controllable. urlopen would honour file:// and
    other schemes, which would turn a hostile responder into a local file read;
    only http is accepted.
    """
    if urllib.parse.urlparse(location_url).scheme != DESCRIPTION_SCHEME:
        return None, None
    try:
        with urllib.request.urlopen(location_url, timeout=2) as resp:
            xml_data = resp.read(DESCRIPTION_MAX_BYTES).decode("utf-8", errors="ignore")
    except (OSError, ValueError):
        return None, None
    return _parse_device_description(xml_data)


def _msearch_datagram() -> bytes:
    return (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
        'MAN: "ssdp:discover"\r\n'
        f"MX: {SSDP_MX}\r\n"
        f"ST: {SSDP_ST}\r\n\r\n"
    ).encode()


def _location_header(payload: bytes) -> str:
    """The LOCATION header of an SSDP response, or "" when absent."""
    text = payload.decode("utf-8", errors="ignore")
    for line in text.splitlines():
        if line.lower().startswith("location:"):
            return line.split(":", 1)[1].strip()
    return ""


def _describe_responder(ip: str, payload: bytes) -> dict[str, str]:
    location = _location_header(payload)
    name, model = _fetch_device_info(location) if location else (None, None)
    return {"ip": ip, "name": name or DEFAULT_TV_NAME, "model": model or ""}


def discover_tvs(timeout: float = 3.0) -> list[dict[str, str]]:
    tvs: list[dict[str, str]] = []
    seen: set[str] = set()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(timeout)
        sock.sendto(_msearch_datagram(), (SSDP_ADDR, SSDP_PORT))

        while True:
            try:
                data, (ip, _) = sock.recvfrom(SSDP_RECV_BYTES)
            except TimeoutError:
                break
            if ip in seen:
                continue
            seen.add(ip)
            tvs.append(_describe_responder(ip, data))
    finally:
        sock.close()

    return tvs


def _normalize_mac(mac: str) -> str | None:
    mac = mac.replace("-", ":").lower()
    parts = mac.split(":")
    if len(parts) != MAC_OCTETS:
        return None
    for p in parts:
        if not (1 <= len(p) <= MAC_OCTET_MAX_DIGITS) or any(
            c not in string.hexdigits for c in p
        ):
            return None
    return ":".join(p.zfill(2) for p in parts)


def _warm_arp_cache(ip: str) -> None:
    """Touch the host so it appears in the ARP table. Failure is expected."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(b"\0", (ip, 9))
    except OSError:
        # Best effort: the probe only warms the ARP cache.
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            s.connect((ip, 3000))
    except OSError:
        # Best effort: an unreachable TV is the normal case here.
        pass


def _mac_from_arp_output(out: str, ip: str, *, match_parenthesised: bool) -> str | None:
    """Find the MAC for `ip` in `arp` output."""
    needle = f"({ip})" if match_parenthesised else ip
    for line in out.splitlines():
        if needle in line:
            m = MAC_RE.search(line)
            return _normalize_mac(m.group(1)) if m else None
    return None


def _lookup_mac(ip: str) -> str | None:
    """Read the ARP table for this platform."""
    if platforms.is_linux():
        out = subprocess.check_output(
            ["ip", "neigh", "show", ip], text=True, stderr=subprocess.DEVNULL
        )
        m = re.search(r"lladdr\s+([0-9a-f:]{17})", out, re.IGNORECASE)
        return _normalize_mac(m.group(1)) if m else None

    if platforms.is_macos():
        out = subprocess.check_output(
            ["arp", "-an"], text=True, stderr=subprocess.DEVNULL
        )
        return _mac_from_arp_output(out, ip, match_parenthesised=True)

    out = subprocess.check_output(["arp", "-a"], text=True, stderr=subprocess.DEVNULL)
    return _mac_from_arp_output(out, ip, match_parenthesised=False)


def mac_from_ip(ip: str) -> str | None:
    _warm_arp_cache(ip)
    try:
        return _lookup_mac(ip)
    except (OSError, subprocess.SubprocessError):
        return None


def _betterdisplay_installed() -> bool:
    try:
        result = subprocess.run(
            ["brew", "list", "--cask", "betterdisplay"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _betterdisplay_api_ready() -> bool:
    return betterdisplay.api_ready()


def setup_betterdisplay() -> None:
    """Install BetterDisplay via Homebrew if not already installed (macOS only),
    then verify the HTTP API is reachable."""
    if not platforms.is_macos():
        return

    if not _betterdisplay_installed():
        answer = (
            input(
                "BetterDisplay is required for display wake recovery. "
                "Install via Homebrew? [Y/n]: "
            )
            .strip()
            .lower()
        )
        if answer in ("n", "no"):
            print("Skipping BetterDisplay installation.")
            return

        print("Installing BetterDisplay...")
        try:
            subprocess.run(
                ["brew", "install", "--cask", "betterdisplay"],
                check=True,
            )
        except FileNotFoundError:
            print(
                "Warning: Homebrew not found. Install BetterDisplay manually from https://betterdisplay.pro"
            )
            return
        except subprocess.CalledProcessError:
            print(
                "Warning: BetterDisplay installation failed. Install it manually from https://betterdisplay.pro"
            )
            return

    if not _betterdisplay_api_ready():
        print(
            "\nAction required: BetterDisplay's HTTP API is not enabled.\n"
            "  Open BetterDisplay → Settings → Advanced → "
            "Enable HTTP API (port 55777)\n"
            "  'tv power on' will fall back to WOL-only until this is done.\n"
        )


async def _select_discovered(tvs: list[dict[str, str]]) -> str:
    """Print the discovered TVs and return the chosen one's address."""
    for i, tv in enumerate(tvs, 1):
        model = f" [{tv['model']}]" if tv["model"] else ""
        print(f"{i}. {tv['name']}{model} ({tv['ip']})")
    if len(tvs) == 1:
        return str(tvs[0]["ip"])
    while True:
        try:
            return str(tvs[int(await ainput("Select TV: ")) - 1]["ip"])
        except (ValueError, IndexError):
            continue


async def _prompt_for_ip() -> str:
    """Ask for an address until a valid IPv4 one is given."""
    while True:
        ip = await ainput("TV IP: ")
        if validate_ipv4(ip):
            return ip


async def _choose_tv() -> str:
    """Pick a discovered TV, falling back to a typed IP address."""
    tvs = await asyncio.to_thread(discover_tvs)
    return await _select_discovered(tvs) if tvs else await _prompt_for_ip()


async def _pair(tv_ip: str) -> tuple[str | None, str | None]:
    """Pair with the TV, returning (pc_input, mac) discovered while connected."""
    await ainput("TV ON, accept pairing prompt. ENTER to pair... ")

    # Imported here rather than at module scope: pairing is the only thing that
    # needs the TV client, so parsing helpers stay importable without it.
    from bscpylgtv import WebOsClient  # type: ignore[import-untyped]

    client = await WebOsClient.create(
        ip=tv_ip,
        client_key=None,
        key_file_path=str(KEYFILE_PATH),
        timeout_connect=Config.TIMEOUT,
        ping_interval=None,
        states=[],
    )

    pc_input: str | None = None
    mac: str | None = None
    try:
        await client.connect()
        try:
            inputs = await client.get_inputs()
            pc_input = next(
                (i.get("label") for i in inputs if i.get("hdmiSignalExist")), None
            )
        except (OSError, KeyError, TypeError, ValueError):
            # The TV answers inconsistently across firmware; no input is fine.
            pc_input = None
        mac = await asyncio.to_thread(mac_from_ip, tv_ip)
    finally:
        try:
            await client.disconnect()
        except OSError:
            # Already disconnecting; the connection is being torn down anyway.
            pass
    return pc_input, mac


def _save_pairing(tv_ip: str, pc_input: str | None, mac: str | None) -> None:
    """Persist the pairing result and report what was learned."""
    data = read_config()
    data["ip"] = tv_ip
    if pc_input:
        data["pc_input"] = pc_input
    if mac:
        data["mac"] = mac
    write_config(data)
    Config.clear_cache()

    print("OK")
    print(f"ip: {tv_ip}")
    if pc_input:
        print(f"pc_input: {pc_input}")
    if mac:
        print(f"mac: {mac}")


async def setup() -> None:
    setup_betterdisplay()

    if CONFIG_FILE.exists():
        print(f"Config exists: {CONFIG_FILE}")
        if (await ainput("Reconfigure? (y/N): ")).lower() not in ("y", "yes"):
            return

    tv_ip = await _choose_tv()
    pc_input, mac = await _pair(tv_ip)

    if not KEYFILE_PATH.exists():
        raise ConnectionError("Pairing failed: keyfile missing")
    if not Config.extract_client_key(str(KEYFILE_PATH), tv_ip):
        raise ConnectionError("Pairing failed: client key missing")

    _save_pairing(tv_ip, pc_input, mac)
