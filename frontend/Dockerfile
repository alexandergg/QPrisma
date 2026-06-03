# Dockerfile para QPrisma Frontend
# Next.js 16 application

# =============================================================================
# Stage 1: Dependencies
# =============================================================================
FROM node:26-alpine AS deps

WORKDIR /app

# Copiar package files
COPY package.json package-lock.json* ./

# Instalar dependencias
RUN npm ci

# =============================================================================
# Stage 2: Builder
# =============================================================================
FROM node:26-alpine AS builder

WORKDIR /app

# Copiar dependencias desde stage anterior
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Variables de entorno para build
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

# IMPORTANT: NEXT_PUBLIC_* variables are baked into the build
# These URLs are what the BROWSER uses, not the container
# For local Docker development, browser accesses localhost
# For cloud deployment, pass via --build-arg
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

# Microsoft Entra ID (SSO) — required for MSAL to send client_id
ARG NEXT_PUBLIC_ENTRA_CLIENT_ID
ARG NEXT_PUBLIC_ENTRA_AUTHORITY=https://login.microsoftonline.com/common
ARG NEXT_PUBLIC_ENTRA_REDIRECT_URI=http://localhost:3000
ARG NEXT_PUBLIC_ENTRA_API_SCOPE=api://qprisma/access_as_user
ENV NEXT_PUBLIC_ENTRA_CLIENT_ID=${NEXT_PUBLIC_ENTRA_CLIENT_ID}
ENV NEXT_PUBLIC_ENTRA_AUTHORITY=${NEXT_PUBLIC_ENTRA_AUTHORITY}
ENV NEXT_PUBLIC_ENTRA_REDIRECT_URI=${NEXT_PUBLIC_ENTRA_REDIRECT_URI}
ENV NEXT_PUBLIC_ENTRA_API_SCOPE=${NEXT_PUBLIC_ENTRA_API_SCOPE}

# Fail fast if Entra client ID is missing — prevents silent SSO breakage
RUN if [ -z "$NEXT_PUBLIC_ENTRA_CLIENT_ID" ]; then \
      echo "ERROR: NEXT_PUBLIC_ENTRA_CLIENT_ID is required. Pass it via --build-arg." >&2; \
      exit 1; \
    fi

# Build de producción
RUN npm run build

# =============================================================================
# Stage 3: Runner (Production)
# =============================================================================
FROM node:26-alpine AS runner

WORKDIR /app

# Crear usuario no-root
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Variables de entorno
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Copiar archivos necesarios
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

# Cambiar ownership
RUN chown -R nextjs:nodejs /app

USER nextjs

EXPOSE 3000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://0.0.0.0:3000 || exit 1

CMD ["node", "server.js"]
