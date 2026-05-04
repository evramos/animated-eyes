# Pi Hotspot Project

## Concept

Raspberry Pi acts as a self-contained Wi-Fi access point serving a web-based control app. A display on the Pi shows a QR code so a phone (or computer) can connect and launch the control page — no internet required.

## Target Hardware & OS

- Raspberry Pi 4B
- Raspberry Pi OS Trixie (Debian 13)
- OLED or attached display for QR code

## Core Features

### Wi-Fi Fallback AP Mode
- On boot, Pi tries to connect to known Wi-Fi networks
- If no known network is available, Pi switches to hotspot mode (e.g., SSID: "DragonControl")
- Uses NetworkManager with `autoconnect-priority -10` on the AP profile so it only activates as a fallback
- Trixie-specific: include `wifi-sec.pairwise ccmp` and `wifi-sec.proto rsn` for stable connections

### Web Control App
- Lightweight web server (Flask, FastAPI, or Node/Express) hosted on the Pi
- Serves a control UI at `http://192.168.4.1:<port>`
- Optional: captive portal DNS via dnsmasq so phones auto-open the page on connect

### QR Code Display
- Use `qrencode` to generate QR codes shown on the Pi's display
- Wi-Fi join QR: `WIFI:T:WPA;S:DragonControl;P:yourpassword;;`
- URL QR: `http://192.168.4.1:<port>` (or combine with auth token)

### SSH / SCP Access
- Full SSH and SCP access available from any device on the hotspot
- Protected by standard Pi login credentials (key-based auth recommended)
- Works simultaneously alongside web UI usage

### Low TX Power (Short Range)
- Reduce Wi-Fi transmit power via `iwconfig wlan0 txpower 5` to limit range to ~3-5 meters
- Note: power savings are minimal — this is mainly a range-limiting measure
- Alternative: keep Wi-Fi off by default, enable AP only on button press or trigger, disable after timeout

## Security

- WPA2 passphrase on the hotspot
- QR code is convenience, not security — anyone with the password can join manually
- Web app should have its own auth layer (PIN, token, or session limit)
- QR URL can include a one-time token: `http://192.168.4.1:<port>/?token=abc123`
- MAC filtering available via hostapd but easily spoofed

## Key Packages

- `NetworkManager` (nmcli) — AP mode, fallback logic, DHCP via `ipv4.method shared`
- `dnsmasq` (optional) — captive portal DNS redirect
- `qrencode` — QR code generation
- Web framework of choice

## NetworkManager AP Command (Trixie-tested)

```bash
nmcli connection add con-name "Fallback-AP" \
  type wifi ifname wlan0 ssid "DragonControl" \
  802-11-wireless.mode ap \
  802-11-wireless.band bg \
  wifi-sec.pairwise ccmp \
  wifi-sec.proto rsn \
  wifi-sec.key-mgmt wpa-psk \
  wifi-sec.psk "yourpassword" \
  ipv4.method shared \
  ipv4.addresses 192.168.4.1/24 \
  autoconnect yes \
  connection.autoconnect-priority -10
```

## Trixie Notes

- NetworkManager uses Netplan under the hood on Trixie
- Earlier Trixie builds stored `.nmconnection` files in `/run/` (non-persistent) — later updates fixed this to `/etc/NetworkManager/system-connections/`
- Verify connection file location after creation; copy from `/run/` to `/etc/` if needed

## Open Questions

- [ ] Which web framework to use?
- [ ] What does the control app actually control? (eyes, doom, animations?)
- [ ] Single or dual QR code (Wi-Fi join + URL vs captive portal auto-redirect)?
- [ ] Button/trigger to enable AP on demand vs always-on fallback?
- [ ] Second Wi-Fi adapter or Ethernet for internet uplink when in AP mode?
