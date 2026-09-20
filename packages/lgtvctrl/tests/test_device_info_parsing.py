"""UPnP description XML arrives from whatever answered an SSDP multicast.

Any device on the LAN can reply, so the document is untrusted. CPython's
ElementTree does not resolve external entities, but it does expand internal
ones, which is enough for a billion-laughs denial of service.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lgtvctrl.auth import _parse_device_description

UPNP_NS = "urn:schemas-upnp-org:device-1-0"
VALID = (
    f'<root xmlns="{UPNP_NS}"><device>'
    "<friendlyName>Living Room</friendlyName>"
    "<modelNumber>OLED65</modelNumber>"
    "</device></root>"
)


def test_reads_name_and_model() -> None:
    assert _parse_device_description(VALID) == ("Living Room", "OLED65")


def test_entity_declaration_is_refused() -> None:
    """A hostile SSDP responder must not be able to expand entities."""
    bomb = '<!DOCTYPE r [<!ENTITY a "' + "A" * 200 + '">]><r>' + "&a;" * 200 + "</r>"
    assert _parse_device_description(bomb) == (None, None)


def test_malformed_xml_yields_no_fields() -> None:
    assert _parse_device_description("<not-xml") == (None, None)


def test_non_http_location_is_refused_without_fetching() -> None:
    """A hostile SSDP responder must not turn LOCATION into a local file read."""
    from lgtvctrl.auth import _fetch_device_info

    assert _fetch_device_info("file:///etc/passwd") == (None, None)
    assert _fetch_device_info("ftp://example.invalid/x") == (None, None)
