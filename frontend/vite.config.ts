import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
    plugins: [react()],
    server: {
        host: '0.0.0.0',  // This allows external access
        port: 5173
    },
    preview: {
        host: '0.0.0.0',  // For preview mode as well
        port: 5173
    }
})