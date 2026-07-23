FROM node:22-alpine

WORKDIR /app

# Instala uma versão fixa do PNPM e evita o download automático pelo Corepack.
RUN corepack disable \
    && npm install --global pnpm@11.16.0 --force

# Ajustes para conexões lentas ou instáveis.
RUN pnpm config set fetch-retries 5 \
    && pnpm config set fetch-retry-mintimeout 20000 \
    && pnpm config set fetch-retry-maxtimeout 120000 \
    && pnpm config set fetch-timeout 600000 \
    && pnpm config set network-concurrency 4

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./

RUN pnpm install --frozen-lockfile

COPY . .

EXPOSE 3000

CMD ["pnpm", "dev", "--webpack", "--hostname", "0.0.0.0"]
