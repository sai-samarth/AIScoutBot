'use strict';

const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} = require('@whiskeysockets/baileys');
const qrcode = require('qrcode-terminal');
const axios = require('axios');
const path = require('path');
const logger = require('./logger');

const SESSION_DIR = path.join(__dirname, '..', 'session');
const RECONNECT_DELAY_MS = 5000;
const BOT_INCOMING_URL = process.env.BOT_INCOMING_URL || 'http://localhost:8000/incoming';

async function initWhatsApp(app) {
  const { state, saveCreds } = await useMultiFileAuthState(SESSION_DIR);
  const { version } = await fetchLatestBaileysVersion();

  logger.info({ version }, 'Connecting to WhatsApp');

  const sock = makeWASocket({
    version,
    auth: state,
    logger: logger.child({ module: 'baileys' }),
    printQRInTerminal: false,
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      logger.info('Scan this QR code with your WhatsApp app:');
      qrcode.generate(qr, { small: true });
    }

    if (connection === 'close') {
      const statusCode = lastDisconnect?.error?.output?.statusCode;
      const loggedOut = statusCode === DisconnectReason.loggedOut;
      logger.warn({ statusCode, loggedOut }, 'Connection closed');

      if (loggedOut) {
        logger.error('Logged out — delete gateway/session/ and restart to re-scan QR');
      } else {
        logger.info(`Reconnecting in ${RECONNECT_DELAY_MS}ms...`);
        setTimeout(() => initWhatsApp(app), RECONNECT_DELAY_MS);
      }
    }

    if (connection === 'open') {
      logger.info('WhatsApp connected');
      app.locals.sock = sock;
      app.locals.sendMessage = sendMessage;
    }
  });

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return;

    for (const msg of messages) {
      if (!msg.message) continue;
      if (msg.key.fromMe) continue;

      const jid = msg.key.remoteJid;
      const sender = msg.key.participant || msg.key.remoteJid;
      const text =
        msg.message.conversation ||
        msg.message.extendedTextMessage?.text ||
        '';

      const quoted = msg.message.extendedTextMessage?.contextInfo;
      const quotedMessageId = quoted?.stanzaId || null;
      const quotedText = quoted?.quotedMessage?.conversation ||
        quoted?.quotedMessage?.extendedTextMessage?.text || null;
      const mentionedJids = quoted?.mentionedJid || [];

      logger.info({ jid, sender, text: text.slice(0, 80) }, 'Incoming message');

      // Best-effort forward to bot — do not await, do not block
      axios.post(BOT_INCOMING_URL, { jid, sender, text, quotedMessageId, quotedText, mentionedJids })
        .catch((err) => logger.warn({ err: err.message }, 'Failed to forward message to bot'));
    }
  });

  async function sendMessage(jid, text) {
    const result = await sock.sendMessage(jid, { text });
    const messageId = result?.key?.id || null;
    logger.info({ jid, chars: text.length, messageId }, 'Message sent');
    return messageId;
  }

  return { sendMessage };
}

module.exports = { initWhatsApp };
