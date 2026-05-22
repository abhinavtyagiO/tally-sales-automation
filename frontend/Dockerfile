FROM node:22-alpine AS deps
WORKDIR /app
RUN corepack enable
RUN corepack prepare pnpm@10.32.1 --activate
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:22-alpine AS builder
WORKDIR /app
RUN corepack enable
RUN corepack prepare pnpm@10.32.1 --activate
COPY --from=deps /app/node_modules ./node_modules
COPY frontend ./
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_GOOGLE_CLIENT_ID
ARG NEXT_PUBLIC_ENABLE_DEV_LOGIN=false
ARG NEXT_PUBLIC_CONNECTOR_MODE=polling
ARG NEXT_PUBLIC_HELPER_DOWNLOAD_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_GOOGLE_CLIENT_ID=$NEXT_PUBLIC_GOOGLE_CLIENT_ID
ENV NEXT_PUBLIC_ENABLE_DEV_LOGIN=$NEXT_PUBLIC_ENABLE_DEV_LOGIN
ENV NEXT_PUBLIC_CONNECTOR_MODE=$NEXT_PUBLIC_CONNECTOR_MODE
ENV NEXT_PUBLIC_HELPER_DOWNLOAD_URL=$NEXT_PUBLIC_HELPER_DOWNLOAD_URL
RUN pnpm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000

CMD ["node", "server.js"]
