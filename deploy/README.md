# Ubuntu VPS

Deployment directory: `/opt/tiktok-streak`. Runtime user: `tiktok-streak`.

Services:

- `tiktok-streak`: dashboard and daily worker; uses `TZ=Asia/Ho_Chi_Minh`.
- `tiktok-streak-display` and `tiktok-streak-window`: private Chrome desktop.
- `tiktok-streak-vnc` and `tiktok-streak-novnc`: browser screen for login/recovery.
- `tiktok-streak-auth`: login form and private web sessions on loopback port 8766.

Open the authenticated public HTTPS links directly; no Windows launcher or SSH tunnel is required:

- Dashboard: `https://160.250.180.133:8443/`.
- Chrome screen: `https://160.250.180.133:8443/browser/`.

The login page is `https://160.250.180.133:8443/login`. Nginx uses an internal
`auth_request` subrequest to check a server session before serving the dashboard,
API or noVNC WebSocket. Browser HTTP Basic authentication is no longer used.
Anonymous page visits redirect to the login form; anonymous API calls return 401.
The dedicated web username, salt and scrypt password hash are stored privately
in `/var/lib/tiktok-streak/web-auth.json`. Passwords are never stored in source.
Sessions are stored as token hashes in `web-sessions.sqlite3` in that directory.
The browser gets a Secure, HttpOnly, SameSite cookie lasting 7 days. Logout revokes
the session on the server; credential changes invalidate existing sessions.
Repeated failed logins are limited and foreign-origin login/logout requests are blocked.
The owner's Windows account has a private recovery copy at
`C:\Users\Lwent\.ssh\tiktok-streak-web-access.json`, outside the repository.
Do not put credentials in URLs, web assets, or source control.

The proxy uses the existing Let's Encrypt IP certificate and its enabled
Certbot renewal timer. The deploy hook reloads Nginx after this certificate renews.
The app accepts this exact HTTPS origin through `--public-origin`; noVNC uses
`TIKTOK_PUBLIC_ORIGIN`. Unrelated origins remain blocked.
Existing services on ports 80 and 443 keep their own routing.

Dashboard port 8765, browser-screen port 6080 and VNC port 5900 still listen only
on loopback. Chrome's CDP debugging endpoint is disabled in production.
`start.bat` and `start-vps.bat` only open the public dashboard link;
`open-browser-vps.bat` opens its Chrome screen.

For the optional SSH fallback, use `start-vps-ssh.bat`. This workstation has a
dedicated SSH key restricted to starting the Streak service and forwarding only
ports 8765 and 6080; it cannot run arbitrary shell commands. The fallback dashboard
opens at `http://127.0.0.1:8765`. Closing the tunnel does not stop the VPS worker.
On the VPS dashboard, Stop disables the sending schedule while keeping the
dashboard service available. Web Logout only ends the management session;
it does not log out of TikTok or disable the running schedule.

Install `tiktok-streak-auth.service` and provision its private credential file
before enabling `tiktok-streak-public.nginx`. Keep the previous Nginx site as a
root-only backup, run `nginx -t`, then reload Nginx. The auth service runs as
`tiktok-streak` with access only to its private state directory for writes.
The old `.htpasswd` file is no longer part of the public authentication path.

The VPS service uses `--persist-automation`. Once the user enables automatic sending,
its approved account and chat selection are saved privately in `automation.json`.
After a service restart, sending resumes only after the same account is authenticated
and the approved chats are verified again. A Stop action or account change disables
that saved automation. Installing the service does not itself enable sending.

Cookie migration uses the owner's running Chrome context to export TikTok cookies
through SSH into a private `session-import.json`. The application deletes this file
after authenticating the expected account. Do not put this file or the browser profile
in Git or web assets. Existing Windows Chrome databases are not copied to Linux.

Useful commands on the VPS:

```sh
systemctl status tiktok-streak
journalctl -u tiktok-streak -n 50 --no-pager
systemctl restart tiktok-streak
```

For a fresh Ubuntu 24.04 host, install Python venv support, Google Chrome, `libatomic1`,
Xvfb, xauth, Openbox, x11vnc, noVNC/websockify and fonts. Install Python requirements
in `/opt/tiktok-streak/.venv`. Create the isolated service user, its private Xauthority
file, and install the provided systemd units before enabling them.
