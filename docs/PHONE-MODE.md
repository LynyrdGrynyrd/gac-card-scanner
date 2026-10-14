# Scan with phone (phone mode)

**What it does:** on *Scan cards*, click **📱 Scan with phone**. A QR code appears. Scan it with a phone on the same
Wi-Fi; the phone opens a small page where you photograph the front (and optionally the back) of each card and tap
**Send card to computer**. Cards land in this computer's job queue / review queue, in the batch named on the phone
(attributed to the person who showed the QR code).

## Security model
- The main app keeps listening on `127.0.0.1` only. Clicking "Scan with phone" starts a **second, upload-only server**
  on this computer's LAN address, port **8766** (`PHONE_PORT`). It stops when the code expires (15 min,
  `PHONE_TOKEN_MINUTES`), when you click *Stop phone scanning*, or when an admin turns phone mode off.
- That server answers only: the phone page, its icons/manifest/service worker, `POST /m/api/upload`, and the progress
  (state words only) of that phone's own uploads. No card data, queue, exports or admin pages are reachable.
- Pairing token: 128-bit random, single live code per user, moved into an HttpOnly SameSite=Strict cookie on first open
  (removed from the address bar). Expired/invalid tokens are refused; >10 bad attempts/min from one IP → 1-minute block.
- Uploads need a same-origin `Origin` header + a CSRF double-submit header; max 20 cards/min and 300 per code
  (`PHONE_RATE_PER_MIN`, `PHONE_MAX_UPLOADS`); same 25 MB / image-format / duplicate-photo checks as the desktop.
- Admin → Settings → "Allow Scan with phone" turns the feature off (and closes any open code at once). Default: allowed,
  but nothing listens on the LAN until someone shows a QR code. Each QR shown is written to the audit log.
- The firewall may ask to allow incoming connections the first time (Windows Defender / macOS). Allow on **private** networks only.
- `PHONE_HOST=<ip>` overrides the auto-detected LAN address (e.g. a computer with several network cards).

## Camera limitations over plain http (no HTTPS on the LAN)
Browsers only allow **live camera access (`getUserMedia`) and service workers in a secure context** (https or
localhost). The LAN page is plain http, so:
- The phone page uses `<input type="file" accept="image/*" capture="environment">`: tapping **📷 Front** opens the
  phone's normal camera app (iOS Safari, Android Chrome) and works over http. This is the normal path.
- Live preview with a "card fills the frame" guide (turns green; lightweight edge check, no library) is used
  automatically only when the page *is* in a secure context (e.g. if `enable-phone-access` HTTPS certificates are set up
  and the phone trusts them).
- Edge detection / perspective crop is done on the computer after upload (`ocr.crop_card`), so a slightly tilted photo is fine.
- "Add to Home Screen" works from the browser menu (manifest + icons are served). Without a secure context the service
  worker doesn't run, so it behaves like a bookmark (needs the computer to be on and a fresh QR code after expiry).
- jscanify (MIT) was evaluated for in-browser edge detection; it needs OpenCV.js (~8–10 MB, Apache-2.0) on the phone and,
  without live preview over http, would only run on the still photo, which the server already crops. Not bundled.

## Docker
Phone mode does **not** work under the shipped `docker-compose.yml`: port 8766 isn't published and the container's LAN
address is not the host's. To use it in Docker, publish `8766:8766` on the host's LAN address and set
`PHONE_HOST=<host LAN IP>`; otherwise run the scanner with the normal start scripts for phone scanning.

## Troubleshooting
- Toast "No Wi-Fi/LAN address found": the computer has no network address; connect it to Wi-Fi.
- Phone can't open the link: phone on guest Wi-Fi / client isolation, or firewall blocking port 8766.
- "This pairing has expired": show a new code (codes last 15 minutes).
