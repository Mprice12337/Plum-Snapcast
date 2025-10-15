FROM node:18-alpine

WORKDIR /app

# Accept build arguments
ARG VITE_SNAPCAST_HOST=localhost
ARG VITE_SNAPCAST_PORT=1704
ARG VITE_SNAPCAST_WEB_PORT=1780

# Set environment variables for build
ENV VITE_SNAPCAST_HOST=$VITE_SNAPCAST_HOST
ENV VITE_SNAPCAST_PORT=$VITE_SNAPCAST_PORT
ENV VITE_SNAPCAST_WEB_PORT=$VITE_SNAPCAST_WEB_PORT

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

# Copy built app to nginx
COPY --from=0 /app/dist /usr/share/nginx/html

# Create custom nginx config for React routing
RUN echo 'server { \
    listen 80; \
    server_name _; \
    root /usr/share/nginx/html; \
    index index.html; \
    location / { \
        try_files $uri $uri/ /index.html; \
    } \
}' > /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]