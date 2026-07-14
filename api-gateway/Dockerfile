FROM node:20-slim

WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm ci --production

# Copy application
COPY server.js .

# Expose port
EXPOSE 3000

CMD ["node", "server.js"]
