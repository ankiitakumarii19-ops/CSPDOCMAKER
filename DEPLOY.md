# Putting CSPdocMaker on the server

Two parts: **A** puts the code on GitHub (from the laptop), **B** puts it on
the server and starts it. Do them in order. Commands in grey boxes are typed
exactly as shown, except the parts in `<angle brackets>`, which you replace.

What runs on the server, all inside Docker: the website, the backend, the
background jobs (sheet refresh every 15 min, pending requests, agents), the
database, Redis, and Caddy — the front door that gets the HTTPS certificate
for your domain by itself.

What **never** goes to GitHub: `backend/.env`, `backend/credentials/`,
`deploy/.env.production`, `LOGIN-FOR-TESTING.txt`. They are git-ignored.
You copy the two secret items to the server by hand (step B5).

---

## A. Laptop → GitHub (once)

**A1. Create an empty, PRIVATE repository.** On github.com: **New
repository** → name `cspdocmaker` → **Private** → do *not* add a README,
.gitignore or licence → **Create repository**.
It must be private: the code contains test data and the project tracker.

**A2. Connect the project and push.** In PowerShell on the laptop:

```powershell
cd C:\CSPDOCMAKER
git remote add origin https://github.com/<your-github-name>/cspdocmaker.git
git push -u origin main
```

A browser window asks you to sign in to GitHub the first time. When it
finishes, refresh the GitHub page: the files are there.

**Later, after any change on the laptop:** `git push` (the app's own changes
are committed as they are made).

---

## B. GitHub → server (once)

Log in: `ssh <user>@<server>`. Everything below runs on the server.

**B1. Install Docker** (Ubuntu / Debian):

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
exit
```

Log in again (`ssh <user>@<server>`) so the new permission applies, then
check: `docker compose version` prints a version.

**B2. Check the domain points here, and open the web ports.**

```bash
curl -4 -s ifconfig.me ; echo          # this server's public address
getent hosts <your-domain>             # must show the same address
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp   # only if ufw is in use
```

If the two addresses differ, the domain's DNS "A record" must be changed to
this server's address first (whoever manages the domain does this). Ports
80 and 443 must also be open in any cloud firewall / security group.

**B3. Let the server read the private repository** (a read-only "deploy
key", so no password is stored on the server):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/cspdocmaker_deploy -N "" -C cspdocmaker-server
cat ~/.ssh/cspdocmaker_deploy.pub
```

Copy the line it prints. On GitHub: the repository → **Settings → Deploy
keys → Add deploy key** → title `server`, paste, leave "Allow write access"
**unticked** → **Add key**. Then on the server:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github-cspdocmaker
  HostName github.com
  User git
  IdentityFile ~/.ssh/cspdocmaker_deploy
EOF
```

**B4. Get the code into your folder.** The folder must be empty.

```bash
cd <your-folder>
git clone github-cspdocmaker:<your-github-name>/cspdocmaker.git .
```

(Answer `yes` to the GitHub fingerprint question the first time.)

**B5. Copy the two secret items from the laptop.** In PowerShell **on the
laptop**:

```powershell
scp C:\CSPDOCMAKER\backend\credentials\google_service_account.json <user>@<server>:<your-folder>/backend/credentials/
scp C:\CSPDOCMAKER\backend\.env <user>@<server>:<your-folder>/deploy/laptop.env
```

(Add `-P <port>` after `scp` if the server's SSH port is not 22.)

Then on the server, build the settings file:

```bash
cd <your-folder>
chmod 644 backend/credentials/google_service_account.json
sh deploy/make-env.sh <your-domain> deploy/laptop.env
```

It copies the values marked **COPY** from the laptop's settings, makes the
three fresh secrets marked **NEW**, sets the domain, and then deletes
`deploy/laptop.env`. It prints only setting names, never values. If it lists
anything as "still empty", add it with `nano deploy/.env.production`
(save with Ctrl+O, Enter, Ctrl+X).

**B6. Start everything.**

```bash
docker compose -f docker-compose.prod.yml --env-file deploy/.env.production up -d --build
```

The first time takes 5–15 minutes (it installs LibreOffice and the fonts).

**B7. Check it is working.**

```bash
docker compose -f docker-compose.prod.yml --env-file deploy/.env.production ps
curl -s https://<your-domain>/api/health
```

Every line in `ps` says `running` (the `api` line also `healthy`), and the
health check prints `"status":"healthy"`. Then open
`https://<your-domain>` in a browser — the padlock shows HTTPS — and sign in.

**B8. Only if the app lives under a path of a domain another web server
already serves** — e.g. `https://indev.eko.in/csp-docmaker` (make-env.sh
set this up when you gave it `indev.eko.in/csp-docmaker`).

The app then does not touch ports 80/443: it listens privately on
`127.0.0.1:8088`, and the web server that owns the domain forwards the path
to it. Check locally first:

```bash
curl -s http://127.0.0.1:8088/csp-docmaker/api/health
```

Then whoever runs that web server adds the forwarding rule. For **nginx**,
inside the `server { ... }` block for the domain (the one with its HTTPS
certificate):

```nginx
# One block for /csp-docmaker and everything under it. No redirect of its
# own: the app already sends /csp-docmaker/ to /csp-docmaker.
location /csp-docmaker {
    proxy_pass http://127.0.0.1:8088;          # no path here: keep /csp-docmaker
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    client_max_body_size 25m;                  # template and photo uploads
    proxy_read_timeout 180s;                   # making documents takes ~30 s
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
curl -s https://indev.eko.in/csp-docmaker/api/health
```

The last line prints `"status":"healthy"`; then open
`https://indev.eko.in/csp-docmaker` in a browser.

---

## Good to know

**A fresh start.** The server's database starts empty. Its first sheet
refresh records every CSP already in the sheet as *existing* and processes
none of them — nobody is emailed or messaged because the app moved. Only CSPs
added to the sheet after that are handled automatically. People sign up once
on the server (`https://<your-domain>/auth/signup`); roles still come from
the sheet.

**Turn the laptop's copy off** once the server is live. Two copies reading
the same sheet could both act on the same new CSP.

**Updating the server** after a `git push` from the laptop:

```bash
cd <your-folder>
git pull
docker compose -f docker-compose.prod.yml --env-file deploy/.env.production up -d --build
```

**Looking at problems.**

```bash
# live log of the backend (Ctrl+C to stop watching)
docker compose -f docker-compose.prod.yml --env-file deploy/.env.production logs -f api worker
# one run, step by step, from an Error ID a user sends you
docker compose -f docker-compose.prod.yml --env-file deploy/.env.production exec api python scripts/show_run.py <error-id>
# check WhatsApp
docker compose -f docker-compose.prod.yml --env-file deploy/.env.production exec api python scripts/check_whatsapp.py
```

**Every document as a file** (No. 105). Besides the database, every PDF the
app makes is saved in the `CSP_Documents` folder BESIDE the app folder (on
the server: `/home/Ankita/CSP_Documents`), one folder per CSP, named by
name and code: `CSP_Documents/Rajiv Kumar (1A850395)/CSP ID Card v2.pdf`.
A folder named by the code alone, or under a name later corrected in the
sheet, is renamed automatically. Beside, not inside, so
re-cloning or cleaning the app folder never touches the documents.
Documents made earlier are written within 15 minutes of the app starting.
The app runs as user 1000 inside Docker, so the folder must be writable by
it — once, from the app folder:

```bash
mkdir -p ../CSP_Documents
sudo chown 1000:1000 ../CSP_Documents   # or, without sudo: chmod 777 ../CSP_Documents
ls ../CSP_Documents                      # one folder per CSP: Name (code)
```

If a document cannot be written there the reason is in the log
(`document_archive: could not save ...`); the document is still safe in the
database and is written on a later run once the folder is fixed.

**Looking at the database itself:**

```bash
docker compose -f docker-compose.prod.yml --env-file deploy/.env.production exec postgres psql -U cspdocmaker cspdocmaker
```

then, for example, `\dt` (the tables), `select csp_id, name, district from
csp_records;` or `select csp_id, document_type, version, created_at from
stored_documents order by created_at desc limit 20;` — and `\q` to leave.
In the app, the **Database** page shows the same: every CSP's record, photo
and documents.

**Backups** of the database (documents are stored in it):

```bash
docker compose -f docker-compose.prod.yml --env-file deploy/.env.production exec -T postgres \
  pg_dump -U cspdocmaker cspdocmaker | gzip > ~/cspdocmaker-$(date +%F).sql.gz
```

Run it daily (e.g. from `crontab -e`) and keep copies off the server.
