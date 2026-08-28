# Gateway tunnel (optional): lab server behind NAT → gateway VM

The lab server that runs drone-life usually sits behind a school NAT with no
inbound port. These two autossh units hold a **reverse SSH tunnel** from the
lab server to a small internet-facing gateway VM (the "OCI VM" in
[DEPLOY.md](../../DEPLOY.md#oci-vm-reverse-proxy)), so the gateway's nginx can
reach the game on its own loopback. In DEPLOY.md's nginx snippet this is what
makes `LAB` simply `127.0.0.1`.

| file | what |
|---|---|
| `autossh-reverse-tunnel.service` | one `-R` forward (typically SSH into the lab server via the gateway) |
| `autossh-web-tunnel.service` | two `-R` forwards: lab `:80` → gateway `localhost:8080`, lab `:8000` → gateway `localhost:8000` — **this is the one drone-life needs** |
| `autossh-web-tunnel.env` | the extra variables the web unit reads; append them to the shared env file |

Both units read the same `/etc/default/autossh-reverse-tunnel`. You can run
only the web unit; it still needs `TUNNEL_KEY` and `TUNNEL_REMOTE` in that file.

## Install (on the lab server, as an admin)

```bash
cd /opt/drone-life                       # the paths below are relative to the clone
# 1. a key for the tunnel, owned by the user the units run as (edit User= in
#    both .service files — they say `lamb`; use the account that owns this key)
sudo -u dronelife ssh-keygen -t ed25519 -N "" -f /home/dronelife/.ssh/tunnel_ed25519
sudo cat /home/dronelife/.ssh/tunnel_ed25519.pub     # → gateway, step 3

# 2. the shared env file (root:root 0600). Fill in every value.
sudo install -m 0600 -o root -g root /dev/null /etc/default/autossh-reverse-tunnel
sudo tee /etc/default/autossh-reverse-tunnel >/dev/null <<'ENV'
TUNNEL_KEY=/home/dronelife/.ssh/tunnel_ed25519
TUNNEL_REMOTE=tunneler@gateway.example.org
# generic unit: bind ON the gateway → forward to this box (e.g. SSH access)
TUNNEL_BIND=localhost:2222
TUNNEL_FORWARD=localhost:22
ENV
sudo sh -c 'cat docs/deploy/gateway-tunnel/autossh-web-tunnel.env >> /etc/default/autossh-reverse-tunnel'

# 3. on the GATEWAY: an unprivileged `tunneler` user whose authorized_keys holds
#    the public key from step 1. Restrict it to forwarding only:
#      restrict,port-forwarding ssh-ed25519 AAAA... tunnel
#    (no GatewayPorts needed — everything binds to the gateway's localhost)

# 4. back on the lab server: accept the gateway's host key ONCE as the tunnel
#    user — the units run with StrictHostKeyChecking=yes and BatchMode=yes,
#    so an unknown host key makes them fail silently forever
sudo -u dronelife ssh -i /home/dronelife/.ssh/tunnel_ed25519 tunneler@gateway.example.org true

# 5. install and start
sudo apt install -y autossh
sudo cp docs/deploy/gateway-tunnel/autossh-reverse-tunnel.service \
        docs/deploy/gateway-tunnel/autossh-web-tunnel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now autossh-web-tunnel          # and autossh-reverse-tunnel if you want it
systemctl status autossh-web-tunnel --no-pager
```

## Check (on the gateway)

```bash
ss -ltn | grep -E ':(8000|8080|2222) '     # expect 127.0.0.1:8000 (and :8080 / :2222)
curl -s localhost:8000/healthz             # the lab server's drone-life answers
```

Then point nginx at it: `proxy_pass http://127.0.0.1:8000;` in the snippet in
[DEPLOY.md](../../DEPLOY.md#oci-vm-reverse-proxy).

## Two consequences for DEPLOY.md's settings

- **Firewall**: with the tunnel, port 8000 on the lab server is reached over
  its own loopback (sshd delivers the forwarded connection locally). Nothing
  needs to be opened in the lab-server firewall at all.
- **`FORWARDED_ALLOW_IPS`**: for the same reason the proxy's requests arrive
  from `127.0.0.1`, which is uvicorn's default trusted peer — so the
  `FORWARDED_ALLOW_IPS=10.0.0.5` example in DEPLOY.md is only for a direct
  (wireguard / LAN) route to the gateway. Through this tunnel, set
  `FORWARDED_ALLOW_IPS=127.0.0.1` (or leave it unset).

## Troubleshooting

| symptom | check | fix |
|---|---|---|
| unit restarts every 10 s | `journalctl -u autossh-web-tunnel -n 30` | step 4 (host key) or the key isn't in `authorized_keys` on the gateway |
| `remote port forwarding failed` | `ss -ltn` on the gateway shows `:8000` already taken | free the port on the gateway or change `TUNNEL_BIND_APP` (then nginx's `proxy_pass`) |
| gateway shows the port but `curl` hangs | `curl -s localhost:8000/healthz` on the **lab** server | drone-life itself is down — see DEPLOY.md's "When things break" |
