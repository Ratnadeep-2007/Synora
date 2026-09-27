# Synora - WhatsApp Baileys Bridge

Daemon using [`@whiskeysockets/baileys`](https://github.com/whiskeysockets/Baileys) to ingest group chat messages into Synora.

## Features
- **Baileys WebSocket Client**: Direct connection to WhatsApp Web multi-device protocol without Chromium/Puppeteer.
- **Group Chat Focus**: Listens to messages in WhatsApp groups (`@g.us`).
- **Autonomous Project Understanding**: Synora automatically identifies which project the team is discussing (e.g. Healthcare Claims Engine vs Core Architecture).
- **Live Excalidraw Whiteboard Updates**: Changes discussed in WhatsApp are automatically reflected on the relevant project's visual Excalidraw whiteboard.

## Quickstart

```bash
cd services/baileys-bridge
npm install
npm start
```

1. Scan the terminal QR code using WhatsApp (Linked Devices).
2. Any architectural decisions or requirements discussed in connected groups are immediately routed and visualized in Synora!

## Test / Simulation Mode

```bash
npm run simulate
```
This tests the full end-to-end pipeline against the Synora backend without requiring a connected physical device.
