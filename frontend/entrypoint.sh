#!/bin/sh
# Inject the backend URL at container start so the same image works against
# any backend without rebuilding (NEXT_PUBLIC_* would bake it at build time).
if [ -n "$SYNORA_API_URL" ]; then
  printf 'window.__SYNORA_API_URL__ = "%s";\n' "$SYNORA_API_URL" > ./public/runtime-config.js
fi
exec node server.js
