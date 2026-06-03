# Pi Hotspot Project

## Concept

Raspberry Pi acts as a self-contained Wi-Fi access point serving a web-based control app. A display on the Pi shows a QR code so a phone (or computer) can connect and launch the control page — no internet required.

## Target Hardware & OS

- Raspberry Pi 4B
- Raspberry Pi OS Trixie (Debian 13)
- OLED or attached display for QR code

---

## Phase 1: Basic Hotspot

Get the AP up and reachable before adding any access controls.

### Step 1 — Create the AP profile

#### WPA2 (confirmed working)

```bash
sudo nmcli connection add con-name "Fallback-AP" \
  type wifi ifname wlan0 ssid "DragonControl" \
  802-11-wireless.mode ap \
  802-11-wireless.band bg \
  802-11-wireless.hidden yes \
  wifi-sec.pairwise ccmp \
  wifi-sec.proto rsn \
  wifi-sec.key-mgmt wpa-psk \
  wifi-sec.psk "yourpassword" \
  ipv4.method shared \
  ipv4.addresses 192.168.4.1/24 \
  autoconnect yes \
  connection.autoconnect-priority -10
```

**WPA3-SAE note:** brcmfmac firmware 7.45.265 has `extsae` and `iw phy` reports SAE support, but that reflects **client-mode SAE** only. AP-mode SAE via wpa_supplicant times out with `supplicant-timeout` on this hardware. WPA2 RSN/CCMP is the confirmed working option.

### Step 2 — Verify the AP is working

```bash
# Manually activate to test (don't wait for fallback trigger)
sudo nmcli connection up "Fallback-AP"

# Confirm it's active and wlan0 has the right IP
nmcli connection show --active
ip addr show wlan0

# Watch NM logs if something's wrong
sudo journalctl -u NetworkManager -f
```

Connect a device to "DragonControl" (hidden network — enter the SSID manually). Confirm:
- Device gets a DHCP address in `192.168.4.0/24`
- Can SSH to `192.168.4.1` from the connected device

### Step 3 — Verify fallback behavior

```bash
# Bring the AP down
sudo nmcli connection down "Fallback-AP"

# Simulate no known networks by disabling your home SSID temporarily,
# or just manually trigger: NM should auto-activate Fallback-AP after other connections fail
```

### Connection file location (Trixie gotcha)

Earlier Trixie builds stored `.nmconnection` files in `/run/` (non-persistent) — later updates fixed this to `/etc/NetworkManager/system-connections/`. After creation, verify:

```bash
ls /etc/NetworkManager/system-connections/Fallback-AP.nmconnection
# If missing, copy it:
sudo cp /run/NetworkManager/system-connections/Fallback-AP.nmconnection \
        /etc/NetworkManager/system-connections/
sudo chmod 600 /etc/NetworkManager/system-connections/Fallback-AP.nmconnection
```

---

## Phase 2: MAC Allowlist

Add this only after Phase 1 is confirmed working. NetworkManager does not natively enforce MAC allowlists for AP mode — the implementation uses `nftables` with a `netdev ingress` hook (Layer 2, before any IP processing), applied dynamically via an NM dispatcher script.

**What this blocks:** Any frame from a non-listed MAC — including DHCP, ARP, and all data — is dropped before reaching the kernel network stack. Unlisted devices may complete the WPA handshake at the 802.11 layer (handled by firmware below this hook), but they will never receive a DHCP lease or exchange any traffic.

### Approved devices

| Device  | MAC                 |
|---------|---------------------|
| MacBook | `16:f7:93:b0:e2:41` |
| iPhone  | `56:4a:10:91:c0:95` |
| iPad    | `3a:e9:96:72:0d:3a` |

**Private Wi-Fi Addresses:** iOS 14+/macOS Big Sur+ assign a stable but randomized MAC per network. The MACs above must be the ones each device uses specifically for "DragonControl" — not the hardware MAC. Verify them after first connection (see Device Enrollment below).

### nftables config

Save as `/etc/nftables.d/ap-mac-filter.nft`:

```nft
#!/usr/sbin/nft -f
# MAC allowlist for DragonControl AP
# Loaded dynamically by NM dispatcher — do NOT add to /etc/nftables.conf

table netdev ap_filter {
    set allowed_macs {
        type ether_addr
        elements = {
            16:f7:93:b0:e2:41,   # MacBook
            56:4a:10:91:c0:95,   # iPhone
            3a:e9:96:72:0d:3a    # iPad
        }
    }

    chain ingress_wlan0 {
        type filter hook ingress device wlan0 priority 0; policy accept;
        ether saddr @allowed_macs accept
        drop
    }
}
```

### NetworkManager dispatcher script

Save as `/etc/NetworkManager/dispatcher.d/95-ap-mac-filter` (must be executable, root-owned):

```bash
#!/bin/bash
# Applies/removes MAC allowlist when Fallback-AP activates or deactivates

IFACE="$1"
ACTION="$2"

[ "$IFACE" != "wlan0" ] && exit 0

case "$ACTION" in
    up)
        if nmcli -t -f NAME connection show --active 2>/dev/null | grep -qF "Fallback-AP"; then
            nft -f /etc/nftables.d/ap-mac-filter.nft
        fi
        ;;
    down)
        nft delete table netdev ap_filter 2>/dev/null || true
        ;;
esac
```

### Setup steps

```bash
# Install files
sudo cp ap-mac-filter.nft /etc/nftables.d/
sudo cp 95-ap-mac-filter /etc/NetworkManager/dispatcher.d/
sudo chmod 755 /etc/NetworkManager/dispatcher.d/95-ap-mac-filter
sudo chown root:root /etc/NetworkManager/dispatcher.d/95-ap-mac-filter

# Verify nftables syntax
sudo nft -c -f /etc/nftables.d/ap-mac-filter.nft

# Restart AP to trigger dispatcher
sudo nmcli connection down "Fallback-AP" && sudo nmcli connection up "Fallback-AP"

# Confirm rules loaded
sudo nft list table netdev ap_filter

# Check dispatcher fired
sudo journalctl -u NetworkManager | grep dispatcher
```

### Device enrollment

Connect each device first with the filter disabled, then confirm their per-network MACs:

1. With AP running and filter not yet installed, connect each device to "DragonControl"
2. Check the per-network MAC on each device:
   - iPhone/iPad: Settings → Wi-Fi → DragonControl → ⓘ → "Wi-Fi Address"
   - MacBook: System Settings → Wi-Fi → DragonControl → Details → "Private Wi-Fi address"
3. Update the `elements` set in `ap-mac-filter.nft` if any MAC differs from the table above
4. Install and activate the filter per Setup steps above

### SSH recovery (if locked out by MAC filter)

All changes take effect immediately — no reboot or NM restart required:

```bash
# Drop filter entirely
sudo nft delete table netdev ap_filter

# Edit a MAC then hot-reload
sudo nano /etc/nftables.d/ap-mac-filter.nft
sudo nft -f /etc/nftables.d/ap-mac-filter.nft

# Check current state
sudo nft list table netdev ap_filter 2>/dev/null || echo "Filter not loaded"
```

---

## Core Features (reference)

### Web Control App
- Lightweight web server (Flask, FastAPI, or Node/Express) hosted on the Pi
- Serves a control UI at `http://192.168.4.1:<port>`
- Optional: captive portal DNS via dnsmasq so phones auto-open the page on connect

### QR Code Display
- Use `qrencode` to generate QR codes shown on the Pi's display
- Wi-Fi join QR for hidden SSID: `WIFI:T:WPA;S:DragonControl;P:yourpassword;H:true;;`
  - `H:true` tells the device the network is hidden
- URL QR: `http://192.168.4.1:<port>` (or combine with auth token)

### SSH / SCP Access
- Full SSH and SCP access available from any device on the hotspot
- Protected by standard Pi login credentials (key-based auth recommended)

### Low TX Power (Short Range)
- Reduce Wi-Fi transmit power via `iwconfig wlan0 txpower 5` to limit range to ~3-5 meters
- Alternative: keep AP off by default, enable on button press or trigger, disable after timeout

## Security Notes

- **Hidden SSID** — minimal obscurity; `airodump-ng` still detects it from probe responses
- **WPA2/WPA3** — passphrase-protected with RSN/CCMP
- **WPA3/brcmfmac:** AP-mode SAE fails with `supplicant-timeout` despite firmware 7.45.265 having `extsae`. `iw phy`'s `SAE with AUTHENTICATE command` reflects client-mode only — AP-mode SAE is a separate codepath and does not work on this hardware. WPA2 RSN/CCMP is the confirmed working option.
- **MAC allowlist** (Phase 2) — Layer 2 drop via nftables; not foolproof against spoofing, but combined with a strong passphrase and hidden SSID it's a solid barrier
- Web app should have its own auth layer regardless (PIN, token, or session limit)

## Key Packages

- `NetworkManager` (nmcli) — AP mode, fallback logic, DHCP via `ipv4.method shared`
- `nftables` — MAC allowlist enforcement (pre-installed on Trixie)
- `dnsmasq` (optional) — captive portal DNS redirect
- `qrencode` — QR code generation
- Web framework of choice

## Open Questions

- [ ] Which web framework to use?
- [ ] What does the control app actually control? (eyes, doom, animations?)
- [ ] Single or dual QR code (Wi-Fi join + URL vs captive portal auto-redirect)?
- [ ] Button/trigger to enable AP on demand vs always-on fallback?
- [ ] Second Wi-Fi adapter or Ethernet for internet uplink when in AP mode?
- [x] ~~MAC filtering approach~~ — nftables `netdev ingress` allowlist via NM dispatcher (Phase 2)
- [x] ~~Hidden SSID~~ — `802-11-wireless.hidden yes`
- [x] ~~WPA2 or WPA3~~ — WPA2 RSN/CCMP confirmed working; WPA3-SAE AP mode fails on brcmfmac despite `extsae` firmware flag
