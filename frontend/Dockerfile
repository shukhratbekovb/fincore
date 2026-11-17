FROM node:24-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM dependencies AS build
ENV NEXT_TELEMETRY_DISABLED=1
COPY . .
RUN mkdir -p public && npm run build

FROM node:24-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
RUN addgroup -S -g 10001 fincore && adduser -S -u 10001 -G fincore fincore
COPY --from=build --chown=fincore:fincore /app/.next/standalone ./
COPY --from=build --chown=fincore:fincore /app/.next/static ./.next/static
COPY --from=build --chown=fincore:fincore /app/public ./public
USER 10001:10001
EXPOSE 3000
CMD ["node", "server.js"]
