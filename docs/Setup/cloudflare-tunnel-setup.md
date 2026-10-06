# Cloudflare Tunnel Setup Guide

Connect your parked domain to the local agent running on your machine.
No port forwarding, no static IP required.

---

## Prerequisites
- Domain registered anywhere (GoDaddy, Namecheap, etc.) — currently parked
- Free Cloudflare account at https://cloudflare.com
- Agent installed and running at W:\LocalAgent

---

## Step 1: Move DNS to Cloudflare

1. Log in to Cloudflare → **Add a site** → enter your domain name
2. Choose the **Free plan**
3. Cloudflare shows two nameservers (e.g. `ara.ns.cloudflare.com`, `bob.ns.cloudflare.com`)
4. Go to your domain registrar → find DNS/Nameserver settings → replace existing nameservers with Cloudflare's two
5. Save. Propagation takes up to 24h, usually under 1h.

To confirm: `nslookup -type=NS yourdomain.com` should return Cloudflare nameservers.

---

## Step 2: Install cloudflared on Windows

Download the installer:
https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.msi

Run the `.msi` installer. After install, verify:
```bash
cloudflared --version
```

---

## Step 3: Authenticate with Cloudflare

```bash
cloudflared tunnel login
```

A browser window opens. Log in to Cloudflare and **select your domain**. A certificate is saved to:
`C:\Users\<you>\.cloudflared\cert.pem`

---

## Step 4: Create a named tunnel

```bash
cloudflared tunnel create local-agent
```

Note the tunnel ID printed (e.g. `abc123de-...`). A credentials file is saved to:
`C:\Users\<you>\.cloudflared\<tunnel-id>.json`

---

## Step 5: Create tunnel config file

Create `C:\Users\<you>\.cloudflared\config.yml`:

```yaml
tunnel: <your-tunnel-id>
credentials-file: C:\Users\<YourUsername>\.cloudflared\<tunnel-id>.json

ingress:
  - hostname: yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
```

Replace `<your-tunnel-id>`, `<YourUsername>`, and `yourdomain.com` with your actual values.

---

## Step 6: Route DNS to tunnel

```bash
cloudflared tunnel route dns local-agent yourdomain.com
```

This creates a CNAME record in Cloudflare DNS pointing your domain to the tunnel.

---

## Step 7: Test — run server + tunnel

**Terminal 1 — Start the agent server:**
```bash
cd W:\LocalAgent
.venv\Scripts\activate
python server.py
```

Wait for "Server ready." (model loads ~10s).

**Terminal 2 — Start the tunnel:**
```bash
cloudflared tunnel run local-agent
```

Open `https://yourdomain.com` on your phone. You should see the chat interface.
Enter your AGENT_SECRET token when prompted (find it in `W:\LocalAgent\.env`).

---

## Step 8: Auto-start on Windows boot

**Install cloudflared as a Windows service:**
```bash
cloudflared service install
```

Starts automatically on boot. To control it:
```bash
# Check status
sc query cloudflared

# Start / Stop manually
sc start cloudflared
sc stop cloudflared
```

**Auto-start the agent server via Task Scheduler:**

1. The launcher already exists: `W:\LocalAgent\scripts\start_server.bat` (activates the venv and runs `python server.py`).

2. Open **Task Scheduler** → Create Basic Task
   - Name: `LocalAgent Server`
   - Trigger: **When the computer starts**
   - Action: Start a program → `W:\LocalAgent\scripts\start_server.bat`
   - Check "Run whether user is logged on or not"

---

## Step 9: Install PWA on phone

1. Open `https://yourdomain.com` in Chrome (Android) or Safari (iOS)
2. Tap the browser menu → **Add to Home Screen** (Android) or **Share → Add to Home Screen** (iOS)
3. The agent opens as a standalone app — no browser chrome
4. Allow notifications when prompted (required for reminders)

---

## Troubleshooting

**"Unable to reach site" on phone:**
- Check tunnel is running: `cloudflared tunnel info local-agent`
- Check server is running on port 8000
- Verify DNS propagation: https://dnschecker.org

**Token rejected (WebSocket closes immediately):**
- Double-check AGENT_SECRET in `.env` matches what you entered in the prompt
- Session storage caches the token — clear site data in browser settings to re-enter it

**Push notifications not arriving:**
- VAPID keys must be set in `.env` before the server starts
- On iOS, PWA must be installed to home screen (not just open in browser) for push to work
- Check browser console for push registration errors
