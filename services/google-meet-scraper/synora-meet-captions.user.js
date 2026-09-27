// ==UserScript==
// @name         Synora Google Meet Live Caption Interceptor
// @namespace    https://synora.internal
// @version      1.0.0
// @description  Captures free real-time closed captions from Google Meet and streams them to Synora without any Google Cloud quota or Workspace subscription.
// @author       Synora Team
// @match        https://meet.google.com/*
// @grant        GM_xmlhttpRequest
// @connect      localhost
// @connect      127.0.0.1
// ==/UserScript==

(function () {
  'use strict';

  console.log('[Synora] Google Meet Live Caption Scraper activated.');

  let capturedUtterances = [];
  let lastSpeaker = '';
  let lastText = '';
  const SYNORA_INGEST_URL = 'http://localhost:8000/meetings/ingest-transcript';

  // 1. Create a floating Synora badge on the Google Meet UI
  const badge = document.createElement('div');
  badge.id = 'synora-stream-badge';
  badge.innerHTML = `
    <div style="
      position: fixed;
      bottom: 85px;
      left: 20px;
      z-index: 999999;
      background: #0f172a;
      color: #fff;
      border: 1px solid #3b82f6;
      border-radius: 8px;
      padding: 10px 14px;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      font-size: 12px;
      box-shadow: 0 4px 14px rgba(0,0,0,0.4);
      display: flex;
      flex-direction: column;
      gap: 6px;
    ">
      <div style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
        <span style="font-weight: 600; color: #60a5fa; display: flex; align-items: center; gap: 6px;">
          <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#22c55e;"></span>
          Synora Zero-Quota Stream
        </span>
        <span id="synora-utterance-count" style="font-weight: bold; background: #1e293b; padding: 2px 6px; border-radius: 4px;">0 lines</span>
      </div>
      <div style="display: flex; gap: 6px; margin-top: 4px;">
        <button id="synora-btn-send" style="
          background: #2563eb;
          color: white;
          border: none;
          border-radius: 4px;
          padding: 4px 8px;
          cursor: pointer;
          font-size: 11px;
          font-weight: 600;
        ">Push to Synora</button>
        <button id="synora-btn-copy" style="
          background: #334155;
          color: white;
          border: none;
          border-radius: 4px;
          padding: 4px 8px;
          cursor: pointer;
          font-size: 11px;
        ">Copy Text</button>
      </div>
    </div>
  `;
  document.body.appendChild(badge);

  const countEl = document.getElementById('synora-utterance-count');
  const sendBtn = document.getElementById('synora-btn-send');
  const copyBtn = document.getElementById('synora-btn-copy');

  // 2. Closed Captions DOM Observer
  function startObserver() {
    const observer = new MutationObserver(() => {
      // Find Google Meet caption wrappers
      // Selectors match Google Meet's responsive live captions DOM
      const captionNodes = document.querySelectorAll(
        'div[jsname="YSxPC"], div[jscontroller="D1tHje"], div[aria-live="polite"]'
      );

      captionNodes.forEach((node) => {
        // Find speaker container and speech text
        const speakerEl =
          node.querySelector('div.zs7LEd, span.NWdfDe, div.bj4p3b') ||
          node.parentElement?.querySelector('div.zs7LEd, span.NWdfDe, div.bj4p3b');
        const textEl =
          node.querySelector('div.ygKcRe, span.VbkSUe, div.iTTPOb') ||
          node;

        if (textEl && textEl.innerText) {
          const currentText = textEl.innerText.trim();
          const speakerName = speakerEl ? speakerEl.innerText.trim() : (lastSpeaker || 'Speaker');

          if (currentText && currentText !== lastText) {
            // Check if current text is just an expansion of previous utterance from same speaker
            if (lastSpeaker === speakerName && currentText.startsWith(lastText)) {
              if (capturedUtterances.length > 0) {
                capturedUtterances[capturedUtterances.length - 1].text = currentText;
              }
            } else if (currentText.length > 2) {
              capturedUtterances.push({
                speaker: speakerName,
                text: currentText,
                timestamp: new Date().toISOString(),
              });
              lastSpeaker = speakerName;
            }
            lastText = currentText;

            if (countEl) {
              countEl.innerText = `${capturedUtterances.length} lines`;
            }
          }
        }
      });
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  }

  // 3. Send Captions to Synora API
  async function sendToSynora() {
    if (capturedUtterances.length === 0) {
      alert('[Synora] No captions captured yet. Make sure CC is turned ON in Google Meet!');
      return;
    }

    sendBtn.innerText = 'Sending...';
    sendBtn.disabled = true;

    const meetingTitle = document.title.replace(' - Google Meet', '').trim() || 'Google Meet Conference';

    const payload = {
      project_id: 'proj_default',
      title: meetingTitle,
      provider: 'google_meet_captions',
      entries: capturedUtterances.map((u) => ({
        speaker: u.speaker,
        text: u.text,
      })),
      auto_process: true,
    };

    try {
      const response = await fetch(SYNORA_INGEST_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-User-ID': 'usr_synesis_default',
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${await response.text()}`);
      }

      const data = await response.json();
      alert(`[Synora Success] Ingested ${data.entries_count} dialogue lines! Pipeline knowledge extracted.`);
      sendBtn.innerText = 'Pushed ✓';
      setTimeout(() => {
        sendBtn.innerText = 'Push to Synora';
        sendBtn.disabled = false;
      }, 3000);
    } catch (err) {
      console.error('[Synora Error]', err);
      alert(`[Synora Error] Failed to send transcript: ${err.message}`);
      sendBtn.innerText = 'Push to Synora';
      sendBtn.disabled = false;
    }
  }

  sendBtn?.addEventListener('click', sendToSynora);

  copyBtn?.addEventListener('click', () => {
    if (capturedUtterances.length === 0) {
      alert('[Synora] No captions to copy.');
      return;
    }
    const formatted = capturedUtterances.map((u) => `${u.speaker}: ${u.text}`).join('\n');
    navigator.clipboard.writeText(formatted);
    copyBtn.innerText = 'Copied!';
    setTimeout(() => {
      copyBtn.innerText = 'Copy Text';
    }, 2000);
  });

  // Start watching DOM when page is loaded
  window.addEventListener('load', startObserver);
  setTimeout(startObserver, 2000);
})();
