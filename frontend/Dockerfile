FROM node:18-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy source code
COPY . .

# Build the app
RUN npm run build

# Serve the built app
FROM nginx:alpine

# Copy built app to a temporary location
COPY --from=0 /app/dist /tmp/dist

# Create custom nginx config for React routing with Snapcast proxy
RUN echo 'server { \
    listen 80; \
    server_name _; \
    root /usr/share/nginx/html; \
    index index.html; \
    \
    # Proxy requests to Snapcast server to avoid CORS issues \
    location /snapcast-api/ { \
        proxy_pass http://snapcast-host:1780/; \
        proxy_set_header Host $host; \
        proxy_set_header X-Real-IP $remote_addr; \
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; \
        proxy_set_header X-Forwarded-Proto $scheme; \
    } \
    \
    location / { \
        try_files $uri $uri/ /index.html; \
    } \
}' > /etc/nginx/conf.d/default.conf

# Create startup script that copies files to volume and starts nginx
RUN echo '#!/bin/sh' > /docker-entrypoint.sh && \
    echo 'cp -r /tmp/dist/* /usr/share/nginx/html/' >> /docker-entrypoint.sh && \
    echo 'exec nginx -g "daemon off;"' >> /docker-entrypoint.sh && \
    chmod +x /docker-entrypoint.sh

EXPOSE 80

CMD ["/docker-entrypoint.sh"]