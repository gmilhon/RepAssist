# Dark Mode, the Claude-style Composer & Tray, and the Scanners

Three experience enhancements that make Rep Assist feel like a first-party mobile
assistant: a full **dark mode**, a **Claude-app-style composer** with a draggable
**bottom-sheet tray** that replaces the old hamburger drawer, and two camera
scanners — **Scan Barcode** and **Scan Bill** — the latter turning a photo of a
competitor's bill into a switch quote.

| Area | What changed | Key files |
|---|---|---|
| 🎨 **Dark mode** | Light/Dark/**System** in Settings → Appearance; OS-default, persisted, no reload | `theme.ts`, `index.html`, `styles.css`, `SettingsPage.tsx` |
| 💬 **Composer** | Rounded box, growing textarea, controls bottom-aligned inside (taller on mobile) | `ChatWidget.tsx`, `styles.css` |
| 🗂️ **Tray** | `+` opens a draggable bottom sheet (half → full); the app's single nav + action surface | `AppTray.tsx`, `App.tsx` |
| 🔎 **Scan Barcode** | Camera → UPC → catalog product card | `Scanner.tsx`, `api/shop.py`, `switch_analysis.py` |
| 🧾 **Scan Bill** | Camera → vision OCR → competitor-switch analysis + auto quote | `Scanner.tsx`, `llm.py`, `switch_analysis.py`, `schemas.py`, `api/shop.py` |

---

## 1. Dark mode

**Where reps set it.** Settings → **Appearance** offers **System / Light / Dark**.
*System* (the default) follows the device's `prefers-color-scheme`; Light/Dark
override it. The choice is saved per-device in `localStorage` and applies live.

**How it works.**
- `frontend/src/theme.ts` is the controller: `getThemePref()` / `setThemePref()`
  store `"light" | "dark" | "system"`; `resolveTheme()` collapses that to an
  actual `light`/`dark`; the resolved value is written to `<html data-theme>`,
  which drives the CSS variable palette. `watchSystemTheme()` (started in
  `main.tsx`) re-resolves when the OS flips while the preference is *System*.
- An **inline script in `index.html`** applies the same logic *before first paint*,
  so there's no flash of the wrong theme on load.
- `styles.css` was converted from ~435 hardcoded colors to a **semantic
  variable palette** — `:root` holds the light values, `:root[data-theme="dark"]`
  overrides them. Tokens are grouped by role: structural (`--bg`, `--card`,
  `--surface-2/3`, `--line`, `--ink/-2/-3`) and status families with four roles
  each — `-ink` (text), `-solid` (saturated fill w/ white text), `-bg` (tint),
  `-border`. A dedicated **`--chrome`** token keeps always-dark surfaces (topbar,
  customer-checkout hero) dark in *both* themes so they never invert.
- `color-scheme` is set per theme, so native controls (date pickers, scrollbars)
  match automatically.

The conversion was mechanical and role-aware: `background: #fff` → a surface
token, but `color: #fff` (white text on a colored button) stays white; saturated
status colors resolve to `-solid` when used as a fill and `-ink` when used as
text.

---

## 2. The composer & the tray

### Composer (Claude-app style)

The chat composer (`ChatWidget.tsx`) is a single rounded container: an
auto-growing `<textarea>` on top, and a control row **bottom-aligned inside** the
box — `+` on the left, then mic (voice-to-text), 🎧 Live Listen, and a filled
round **↑ send**. Enter sends; Shift+Enter inserts a newline. On phones the input
starts noticeably taller, matching the Claude mobile app.

### Tray (bottom sheet)

The old hamburger (`☰`) and the `AppDrawer` are **gone**. The `+` — in the
composer, and a matching launcher in the topbar for the non-chat views — opens
`AppTray`, a **draggable bottom sheet**:

- Opens to a **half** snap (~56% of the viewport); drag the grip up to **full**
  (~92%); flick or drag down to dismiss. Pointer-based, works with touch & mouse,
  velocity-aware snapping.
- Expanding a submenu at the half snap auto-pops the sheet to full.

**Contents** (top → bottom):

```
✏️  New chat
[ 🔎 Scan Barcode ][ 🧾 Scan Bill ][ 📝 Check In ]
📊  Performance ▸  (Store Manager · District · Territory)
📦  Recent Orders
🎫  My Tickets
🗂️  Resolution Desk
✨  System Enhancements
🚀  The Opener
⚙️  Settings
🩺  System Performance ▸  (Performance · CX Monitor · Production)
```

The tray is now the app's **single navigation + quick-action surface**. Existing
wiring is reused: *Check In* opens the check-in card; *Recent Orders / My Tickets
/ System Enhancements / The Opener* are the in-chat MCP lookup cards; the two
submenus and *Resolution Desk / Settings* switch views. (*Resolution Desk* was
folded into the tray so removing the hamburger doesn't orphan that view. Viewing
the live queue remains on the topbar **Live Queue** badge.)

---

## 3. The scanners

Both open a camera modal (`Scanner.tsx`) with graceful fallbacks — manual UPC
entry for barcodes, photo upload for bills — so they still work where the camera
or `BarcodeDetector` isn't available (desktop, denied permission, unsupported
browser).

### Scan Barcode

Reads a **UPC** with the browser `BarcodeDetector`, then calls
`GET /api/shop/product-by-upc`, which resolves it against a demo `UPC_MAP` over
the catalog (`switch_analysis.product_for_upc`). The result is a product card in
the chat with price/monthly and **Add to cart** / **Ask about it** actions.

### Scan Bill → switch analysis

The signature flow. A photo of a **competitor's** wireless bill →
`POST /api/shop/scan-bill`:

1. **Vision extraction** — `llm.analyze_competitor_bill()` sends the image to
   Claude vision and parses a structured `CompetitorBill` (carrier, plan, line
   count, per-line charges, streaming add-ons, home internet, total). Like every
   other LLM call in the app, it **degrades to a deterministic offline sample**
   (`_mock_competitor_bill`) with zero credentials or on any error.
2. **Switch quote** — `switch_analysis.build_switch_quote()` maps their plan tier
   to our nearest Unlimited plan (priced with a realistic **multi-line** table),
   folds each streaming service into a **$10/mo perk**, and adds fiber/FWA home
   internet when they have it.
3. **Savings** — the card leads with monthly/annual savings (their effective
   spend vs. our bundle), a side-by-side of their bill and our matching quote,
   and a summary line.
4. **"Paying anyone else directly?"** — quick-add chips for services they pay a
   3rd party for (Netflix, Disney+, Max, YouTube TV, …) and a home-internet
   toggle. Each selection calls `POST /api/shop/switch-quote` to **re-quote live**,
   showing how bundling those into perks increases the savings. **Build this quote
   in the cart** hands the result to the existing shop graph.

The offline sample (Rival Wireless, 3 lines, Netflix, fiber, $307.99/mo) produces
a ~**$63/mo (~$756/yr)** win, so the flow demos fully offline.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/api/shop/product-by-upc?upc=` | Resolve a scanned UPC to a catalog product |
| `POST` | `/api/shop/scan-bill` | Vision-OCR a bill photo → `{bill, quote}` |
| `POST` | `/api/shop/switch-quote` | Recompute the quote with rep-entered 3rd-party services |

---

## Notes for future work

- The old drawer's **Coaching** quick-action has no tray entry yet; add one if it's
  still wanted.
- Cross-references in older docs that mention the `☰` drawer (e.g. field
  dashboards' "Nav (☰ → Field)") now resolve through the `+` tray under
  **Performance**.
