# Credit QR desk

Staff-only desk mode for issuing unique Cursor credit links at the door. Attendees show their **Luma ticket QR**; the Pi looks them up, claims one unused link from a local pool, and prints a thermal QR slip.

The feedback form is unchanged. The credit desk is served only from the Raspberry Pi at `/credits` — do **not** expose it on the public Netlify frontend.

## Architecture

```
Tablet (LAN)  →  Pi /credits  →  Luma API (guest lookup)
                      ↓
                 SQLite pool (unique links)
                      ↓
                 Thermal printer (QR slip)
```

- **Luma** confirms the guest is approved. It does not record check-in from this app.
- **SQLite** on the Pi is the source of truth for one link per guest.
- **Rescan** reprints the same QR; a guest never gets a second link.

## Setup

### 1. Environment

Add to `.env` on the Pi (see [env.example](env.example)):

```bash
LUMA_API_KEY=your_luma_api_key
LUMA_EVENT_ID=evt-your-event-id
CREDITS_PIN=1234
```

Get the Luma API key from your calendar’s API settings. The event ID is in Luma check-in URLs: `https://luma.com/check-in/evt-xxx?pk=...`.

### 2. Install dependencies

```bash
pip3 install -r requirements.txt
# or from backend/: pip3 install -r requirements.txt
```

### 3. Run the app

All-in-one (recommended for the desk):

```bash
python3 app.py
```

Or split deploy with `backend/api.py` — credits still work at `http://[PI_IP]:5000/credits`.

### 4. Load credit links

Before doors open:

1. Open `http://[PI_IP]:5000/credits` on a tablet (same Wi‑Fi as the Pi).
2. Enter the staff PIN.
3. Expand **Import credit links** and paste Cursor’s list — **one unique redeem URL per line**.
4. Load more links than expected RSVPs.

### 5. Test print

Import one throwaway link, scan a test Luma ticket (or use email lookup), and confirm the QR prints and scans on a phone.

## Event-day workflow

1. Guest shows Luma ticket QR on their phone.
2. Staff tablet camera scans it → printer outputs a credit slip.
3. Guest scans the printed QR to redeem.
4. **Lost slip:** scan the same Luma ticket again → reprints the same credit QR.
5. **Dead phone:** use **Email lookup** with the address they used on Luma.

## Security notes

- Keep `/credits` on the **local network** only. Do not tunnel it publicly with ngrok/Cloudflare unless you add extra auth.
- Redeem URLs are stored in `data/credits.sqlite` on the Pi. Back up that file if you need an audit trail.
- Full URLs are never returned to the browser or printed as text — only as a QR (plus a 4-character ref suffix for staff).

## API endpoints

All require an unlocked session (PIN cookie) except the page itself.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/credits` | Desk UI |
| POST | `/credits/unlock` | `{ "pin": "..." }` |
| GET | `/credits/status` | Pool counts + recent names |
| POST | `/credits/import` | `{ "urls": "..." }` or list |
| POST | `/credits/issue` | `{ "scanned_url": "..." }` or `{ "email": "..." }` |
| POST | `/credits/reprint` | `{ "guest_id": "gst-..." }` |

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "LUMA_API_KEY is not configured" | Set env vars and restart the Pi app |
| Need to debug Luma responses | Check Pi logs (`journalctl -u ticket-printer -f` or terminal running `python3 app.py`). Each lookup logs status + full JSON body when `LUMA_LOG_RESPONSES=true` (default). Set `LUMA_LOG_RESPONSES=false` to reduce noise after debugging. |
| "Guest is not approved" | Guest is waitlisted/declined on Luma |
| "No credit links remaining" | Import more URLs in the desk admin panel |
| "Not a Luma check-in URL" | Guest must show the ticket QR from Luma (not a random QR) |
| Camera not working | Use HTTPS is not required on LAN; grant camera permission in the browser |
| Printer fails after scan | Check `/health` and USB connection |
