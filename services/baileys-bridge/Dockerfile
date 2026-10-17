FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json ./
COPY src ./src
RUN npx tsc

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --from=build /app/dist ./dist
# Session credentials: mount a persistent disk here (BAILEYS_AUTH_DIR).
RUN mkdir -p /data/baileys_auth_info
ENV BAILEYS_AUTH_DIR=/data/baileys_auth_info
CMD ["node", "dist/index.js"]
