'use strict';

const express = require('express');
const logger = require('./logger');
const { initWhatsApp } = require('./whatsapp');
const { registerRoutes } = require('./routes');

const PORT = parseInt(process.env.GATEWAY_PORT || '3001', 10);

async function main() {
  logger.info('Starting WhatsApp Scout Gateway');

  const app = express();
  app.use(express.json());

  registerRoutes(app);

  // Start HTTP server before WhatsApp connects so /healthz is immediately available
  app.listen(PORT, () => {
    logger.info({ port: PORT }, 'HTTP server listening');
  });

  // Initiate WhatsApp connection (will set app.locals.sock once connected)
  await initWhatsApp(app);
}

main().catch((err) => {
  logger.error({ err: err.message }, 'Fatal startup error');
  process.exit(1);
});
