// Runtime backend URL. Overwritten at container start from the SYNORA_API_URL
// environment variable (see Dockerfile entrypoint). Local default below.
window.__SYNORA_API_URL__ = "http://localhost:8000";
// Set SYNORA_AUTH_URL at runtime to require Neon Auth in the frontend.
