# ==============================================================================
# Aegis Sovereign Knowledge Appliance — Web Portal Dockerfile
# Multi-stage production build for standalone Next.js deployment.
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Dependencies
# ------------------------------------------------------------------------------
FROM node:20-alpine AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app

# Copy dependency manifests
COPY web/packages/ui/package.json ./web/packages/ui/
COPY web/apps/portal/package.json ./web/apps/portal/

# Install dependencies across packages
WORKDIR /app/web/packages/ui
RUN npm install --ignore-scripts

WORKDIR /app/web/apps/portal
RUN npm install --ignore-scripts

# ------------------------------------------------------------------------------
# Stage 2: Builder
# ------------------------------------------------------------------------------
FROM node:20-alpine AS builder
WORKDIR /app

# Copy installed node_modules from deps
COPY --from=deps /app/web/packages/ui/node_modules ./web/packages/ui/node_modules
COPY --from=deps /app/web/apps/portal/node_modules ./web/apps/portal/node_modules

# Copy source trees
COPY web/packages/ui ./web/packages/ui
COPY web/apps/portal ./web/apps/portal

WORKDIR /app/web/apps/portal
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

# Build Next.js in standalone mode
RUN npm run build

# ------------------------------------------------------------------------------
# Stage 3: Production Runner
# ------------------------------------------------------------------------------
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Create unprivileged system user for air-gapped security
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy built standalone server and static assets
COPY --from=builder /app/web/apps/portal/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/web/apps/portal/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/web/apps/portal/.next/static ./.next/static

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:3000/ || exit 1

CMD ["node", "server.js"]
