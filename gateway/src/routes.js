'use strict';

const logger = require('./logger');

function registerRoutes(app) {

  // POST /send — send a WhatsApp message
  app.post('/send', async (req, res) => {
    const { jid, text } = req.body;

    if (!app.locals.sendMessage) {
      return res.status(503).json({ error: 'WhatsApp not connected' });
    }
    if (!jid || !text) {
      return res.status(400).json({ error: 'jid and text are required' });
    }

    try {
      const messageId = await app.locals.sendMessage(jid, text);
      res.json({ ok: true, messageId });
    } catch (err) {
      logger.error({ err: err.message, jid }, 'Failed to send message');
      res.status(500).json({ error: err.message });
    }
  });

  // GET /groups — list all groups the bot is a member of
  app.get('/groups', async (req, res) => {
    if (!app.locals.sock) {
      return res.status(503).json({ error: 'WhatsApp not connected' });
    }

    try {
      const groups = await app.locals.sock.groupFetchAllParticipating();
      const result = Object.values(groups).map((g) => ({
        id: g.id,
        subject: g.subject,
        participantCount: g.participants?.length ?? 0,
      }));
      res.json({ groups: result });
    } catch (err) {
      logger.error({ err: err.message }, 'Failed to fetch groups');
      res.status(500).json({ error: err.message });
    }
  });

  // GET /me — return the bot's own WhatsApp JID
  app.get('/me', (req, res) => {
    if (!app.locals.sock?.user) {
      return res.status(503).json({ error: 'Not connected' });
    }
    res.json({
      jid: app.locals.sock.user.id,
      lid: app.locals.sock.user.lid || null,
    });
  });

  // GET /healthz — connection status check
  app.get('/healthz', (req, res) => {
    const connected = !!app.locals.sock;
    res.status(connected ? 200 : 503).json({ connected });
  });
}

module.exports = { registerRoutes };
