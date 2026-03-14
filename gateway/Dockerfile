FROM node:20-slim

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*

# Rewrite SSH git URLs to HTTPS so npm can install Baileys' libsignal-node dep without SSH keys
RUN git config --global url."https://github.com/".insteadOf "ssh://git@github.com/"

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev

COPY src/ ./src/

# session/ is provided via a named volume — do not COPY it
RUN mkdir -p session

CMD ["node", "src/index.js"]
