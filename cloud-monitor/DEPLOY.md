# Stage 3 — Deploy to Zoho Catalyst AppSail

## What you install on the PC

| Tool | Required? | Why |
|------|-----------|-----|
| **Catalyst CLI** (`catalyst`) | **Yes** | Login, link project, deploy AppSail |
| **Node.js / npm** | Yes (you already have it) | Used to install Catalyst CLI |
| **Docker** | **No for Path A** | Only needed if you deploy a custom container image |

**AppSail is not installed on your PC.**  
It is a **cloud service** in Catalyst. You deploy your app *to* AppSail.

---

## Path A (recommended) — Managed Python, no Docker

### A1. Install Catalyst CLI

```bash
npm install -g zcatalyst-cli
catalyst --version
```

If `catalyst` is not found, ensure npm global bin is on PATH (nvm users usually already are).

### A2. Login to Catalyst (India DC)

```bash
catalyst login
```

Browser opens → accept.  
Your console is `console.catalyst.zoho.in` (India).

### A3. Initialize AppSail in `cloud-monitor`

```bash
cd ~/Documents/Device_Testing/cloud-monitor
catalyst init
```

When prompted (typical flow):

1. Select your org / portal  
2. Associate project **Device-Monitor**  
3. Select **AppSail**  
4. Choose **Catalyst-Managed Runtime** (not Docker Image)  
5. Sample project? → **N**  
6. This directory as source? → **Y**  
7. App name → e.g. `device-monitor`  
8. Build path → `.` (current directory)  
9. Stack → pick a Python option (CLI stores it as e.g. `python_3_9`)

`app-config.json` must use lowercase stack ids, e.g. **`python_3_9`** (not `Python_3_11`).

Keep env vars:

- `MONITOR_STORE=catalyst`
- `MONITOR_DEVICES_TABLE=Devices`  
  (Do **not** use env keys starting with `CATALYST_` — AppSail rejects them as reserved.)

### A4. Install Python deps into the deploy folder (managed runtime)

AppSail uploads your files; include dependencies Catalyst expects. Common approach:

```bash
cd ~/Documents/Device_Testing/cloud-monitor
source .venv/bin/activate
pip install -r requirements.txt -t .
```

Or follow Catalyst’s Python AppSail dependency layout if the CLI creates a `requirements` / lib folder during init — prefer the structure the CLI documents after `catalyst init`.

### A5. Deploy

```bash
cd ~/Documents/Device_Testing/cloud-monitor
catalyst deploy appsail
```

Or:

```bash
catalyst deploy
```

### A6. Copy the public URL

CLI/console prints an HTTPS endpoint, e.g.:

`https://...catalyst.../server/.../`

Test:

```bash
curl https://YOUR-APPSAIL-URL/health
curl https://YOUR-APPSAIL-URL/api/monitor/devices
```

---

## Path B (optional) — Docker image AppSail

Use only if Path A fails or you prefer containers.

### B1. Install Docker (Ubuntu)

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

sudo usermod -aG docker $USER
```

Log out and back in (or reboot), then:

```bash
docker --version
docker run hello-world
```

### B2. Build image for Catalyst (linux/amd64)

```bash
cd ~/Documents/Device_Testing/cloud-monitor
docker build --platform linux/amd64 -t device-monitor:latest .
```

### B3. Init AppSail as Docker Image

```bash
catalyst init
# choose Docker Image → local docker:// → device-monitor:latest
catalyst deploy appsail
```

---

## After deploy (Stages 4–5 preview)

1. Set Android `monitor_transport` to `cloud` and put AppSail HTTPS URL in `monitor_cloud_base_url` (keep Electron `monitor-config.js` mode in sync)  
2. Point Electron API base URL to the same URL  
3. Test phone on **mobile data**

---

## Your Catalyst IDs (from Stage 0)

- Data center: **India** (`zoho.in`)
- Org: `60093791767`
- Project: `92089000000013050` (**Device-Monitor**)
- Table: **Devices**
