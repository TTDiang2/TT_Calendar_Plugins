# 🧩 TT Calendar Subscription Plugins

Community plugins for [TT Calendar](https://github.com/TTDiang2/TT_Calendar) (v2.3+). Subscribe to any calendar you want — drop a `.py` into `plugins/` and restart.

> **Main repo** (the application) does NOT ship these plugins in its official binaries. Download them from this repo, drop them into your `plugins/` folder, restart, and you're done.
>
> 🇨🇳 [中文版 README](README.zh-CN.md)

---

## 📦 Available Plugins

| Plugin | Data Source | Description | Credentials |
|---|---|---|---|
| [`investing.py`](investing.py) | [investing.com](https://www.investing.com) Economic Calendar | 16 country layers of macro indicators: time · currency · importance · actual/forecast/previous · vs expectation badges. Organised by country. | ✅ Cloudflare cookie required (see below) |
| [`jisilu.py`](jisilu.py) | Jisilu Investment Calendar | 15 event types — IPOs, convertible bonds, dividends, REITs, stock index futures/options, etc. Organised by event type. | ❌ None needed |

## ⚙️ Installation

1. **Download the plugin file**: Click the filename above, then click **Download raw file** on the right (or `git clone` this repo and copy the `.py` files)
2. **Drop into TT Calendar's plugins folder**:

   - **Source build**: `TT_Calendar/plugins/` directory
   - **Packaged build (3 exes)**: Create a `plugins/` folder next to the exe

3. **Restart the app** — that's it. The sidebar will show plugin-managed layer groups, and the subscription panel can add the new sources.

> Multiple plugins? Put all `.py` files in `plugins/`. Uninstall = delete the file.

## 📖 Usage

### Adding a Subscription

1. Open the app → open the **Subscription** panel in the sidebar (bottom or top, depending on theme)
2. Click **+ Add Subscription**, pick an installed source (e.g. "Investing.com – Economic Calendar"), save
3. Click **Update Now** on that subscription card (or restart the app to auto-refresh) → events are written to their respective layers

### Layer Switching

Layers are grouped by plugin in the sidebar. **Checked = shown and written**; unchecked layers skip the database entirely:

- `Investing · US / China / Japan / Eurozone …` (16 country layers + "Other" catch-all)
- `Jisilu · IPOs / Convertible Bonds / A-Share Dividends …` (15 type-based layers)

### Event Details

Click a date → the detail panel shows fields declared by the plugin (e.g. Investing's time · currency · stat period · importance stars + actual/forecast/previous values + vs-expectation badges). Field rendering is handled by the app automatically — no frontend component to install.

### investing plugin: Cloudflare cookie (the only one that needs it)

investing.com is behind Cloudflare protection; plain requests get blocked. On first use:

1. Open https://cn.investing.com/economic-calendar in **Edge** and pass the CAPTCHA
2. Press `F12` → Application → Cookies → select `cn.investing.com`, select all, copy as JSON
3. Save to `data/investing_cookies.json` (the app data dir; for the packaged build, put it next to the exe in a `data/` folder)

   ```json
   { "cf_clearance": "…", "__cf_bm": "…" }
   ```

4. Go back to the app and click "Update Now" — when the cookie expires (~half a day to a day), just re-export it

## 🧪 Tests

Plugin tests run inside the **TT Calendar source tree** (they depend on the `tt_calendar` package):

```bash
# From the TT_Calendar project root
python -m pytest ../TT_Calendar_Plugins/tests -q
```

- `tests/test_investing_source.py` — investing parser unit tests (uses real network-scraped fixtures, no live HTTP)

## 🤝 Contribute a Plugin

Wrote a new subscription plugin? Share it with the community:

1. Place your `.py` in a local `plugins/` directory first (protocol docs: [docs/SUBSCRIPTION_PLUGIN_GUIDE.md](https://github.com/TTDiang2/TT_Calendar/blob/main/docs/SUBSCRIPTION_PLUGIN_GUIDE.md))
2. Open a PR to this repo: place the plugin file at the repo root, named `source_id.py`
3. Add a row to the table above, with installation notes and credential requirements

**Protocol quick reference**: a `Source` subclass must implement `source_id / display_name / layer_specs() / fetch(start, end)`. Optional hooks: `field_specs()` (event field UI spec) and `refresh_past_days / refresh_future_days` (refresh window).

---

TT Calendar main repo: [TTDiang2/TT_Calendar](https://github.com/TTDiang2/TT_Calendar) · License: MIT
