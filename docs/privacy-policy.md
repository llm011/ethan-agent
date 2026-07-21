# Privacy Policy — Ethan Browser Extension

**Last updated: 2026-07-01**

## Overview

Ethan Browser is a Chrome extension that connects your browser to a locally-running Ethan Agent service over WebSocket. This policy describes exactly what data the extension touches, where it stays, and what it never does.

**Short version: all data stays on your device. Nothing is sent to any external server.**

---

## What the extension does

Ethan Browser acts as a bridge between the Chrome browser and a personal AI agent (`ethan serve`) running on the same machine. When the agent issues a browser command — navigate to a URL, click an element, take a screenshot, read page content — the extension carries out that command on the active tab and returns the result back to the local server.

---

## Permissions and why they are needed

| Permission | Why it's needed |
|---|---|
| `debugger` | Attaches Chrome DevTools Protocol (CDP) to tabs so the agent can take screenshots, click elements, type text, read DOM content, and evaluate JavaScript. Required for browser automation. |
| `tabs` | Identifies open tabs so the agent can target the correct one. |
| `tabGroups` | Allows the agent to read and manage tab groups. |
| `storage` | Saves the local server URL (`ws://localhost:8900/ws/browser`) and auth token entered in the popup. Stored in `chrome.storage.local` — never synced to the cloud. |
| `alarms` | Fires a periodic keepalive alarm (~every 30s) to ensure the offscreen document stays alive as a fallback. |
| `offscreen` | Creates an offscreen document to maintain a persistent WebSocket connection. In Manifest V3, the service worker is terminated after ~30 seconds of inactivity, making it impossible to keep long-lived connections directly. The offscreen document hosts the WebSocket client for real-time communication with the local agent server. |

Host permissions are restricted to `localhost` and `127.0.0.1` only. The extension **cannot** make requests to any external domain.

---

## Data collection and storage

The extension stores only two pieces of data locally in `chrome.storage.local`:

- **Server URL** — the WebSocket address of your local Ethan server (default: `ws://localhost:8900/ws/browser`).
- **Auth token** — a token you enter manually to authenticate with the local server.

Both values are stored on your device only, never transmitted to any server other than the local one you configured.

---

## Data the extension processes during operation

While handling agent commands, the extension may temporarily process:

- **Page content** (text, DOM structure, screenshots) — captured from the active tab and sent only to the local Ethan server on your machine. This data is never stored by the extension itself and never sent to any third party.
- **Tab metadata** (URL, title, tab ID) — used to route commands to the correct tab. Not stored.

---

## What we never do

- We do not collect analytics, usage statistics, or telemetry.
- We do not transmit any data to external servers, cloud services, or third parties.
- We do not track browsing history.
- We do not sell, share, or disclose any user data.
- All WebSocket communication is limited to `localhost` / `127.0.0.1`.

---

## Third-party services

None. The extension communicates exclusively with a server running locally on your own machine.

---

## Changes to this policy

If this policy is updated, the date at the top of this page will change. Because this extension processes no data externally, material changes are unlikely.

---

## Contact

For questions about this privacy policy, open an issue at:  
**https://github.com/llm011/ethan-agent/issues**
