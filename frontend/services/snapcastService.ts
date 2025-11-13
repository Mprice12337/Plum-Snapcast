interface SnapcastServerInfo {
    name: string;
    version: string;
    host: string;
}

interface SnapcastStreamProperties {
    canPlay?: boolean;
    canPause?: boolean;
    canSeek?: boolean;
    canGoNext?: boolean;
    canGoPrevious?: boolean;
    loopStatus?: string;
    playbackStatus?: string;
    position?: number;
    metadata?: {
        [key: string]: any;
    };
}

interface SnapcastStream {
    id: string;
    status: string;
    uri: {
        raw: string;
        scheme: string;
        host: string;
        path: string;
        fragment: string;
        query: Record<string, string>;
    };
    meta?: {
        title?: string;
        artist?: string;
        album?: string;
        artData?: string;
        duration?: number;
    };
    properties?: SnapcastStreamProperties;
}

interface SnapcastClient {
    id: string;
    host: {
        name: string;
        ip: string;
    };
    config: {
        name: string;
        volume: {
            percent: number;
            muted: boolean;
        };
    };
    connected: boolean;
}

interface SnapcastGroup {
    id: string;
    name: string;
    stream_id: string;
    clients: SnapcastClient[];
    muted: boolean;
}

interface SnapcastError {
    code: number;
    message: string;
    data?: any;
}

interface SnapcastResponse {
    id?: number;
    jsonrpc: string;
    result?: {
        server?: {
            server: SnapcastServerInfo;
            streams: SnapcastStream[];
            groups: SnapcastGroup[];
        };
    };
    error?: SnapcastError;
    method?: string;
    params?: any;
}

export class SnapcastService {
    private ws: WebSocket | null = null;
    private messageId = 1;
    private callbacks: Map<number, (response: any) => void> = new Map();
    private host: string;
    private port: number;
    private isConnected = false;
    private metadataUpdateListeners: Set<(streamId: string, metadata: any) => void> = new Set();
    private playbackStateListeners: Set<(streamId: string, playbackStatus: string, properties: SnapcastStreamProperties) => void> = new Set();

    constructor() {
        this.host =
            this.host = window.location.hostname;
        this.port = 1780;
    }

    // Subscribe to metadata updates
    onMetadataUpdate(listener: (streamId: string, metadata: any) => void): () => void {
        this.metadataUpdateListeners.add(listener);
        // Return unsubscribe function
        return () => {
            this.metadataUpdateListeners.delete(listener);
        };
    }

    // Subscribe to playback state updates
    onPlaybackStateUpdate(listener: (streamId: string, playbackStatus: string, properties: SnapcastStreamProperties) => void): () => void {
        this.playbackStateListeners.add(listener);
        // Return unsubscribe function
        return () => {
            this.playbackStateListeners.delete(listener);
        };
    }

    connect(): Promise<void> {
        return new Promise((resolve, reject) => {
            try {
                const wsUrl = `ws://${this.host}:${this.port}/jsonrpc`;
                this.ws = new WebSocket(wsUrl);

                this.ws.onopen = () => {
                    console.log('Connected to Snapcast server');
                    this.isConnected = true;
                    resolve();
                };

                this.ws.onmessage = (event) => {
                    try {
                        const message: SnapcastResponse = JSON.parse(event.data);

                        if (message.id && this.callbacks.has(message.id)) {
                            const callback = this.callbacks.get(message.id);
                            if (callback) {
                                callback(message);
                                this.callbacks.delete(message.id);
                            }
                        }

                        // Handle notifications (method-based messages)
                        if (message.method) {
                            this.handleNotification(message);
                        }
                    } catch (error) {
                        console.error('Error parsing WebSocket message:', error);
                    }
                };

                this.ws.onerror = (error) => {
                    console.error('WebSocket error:', error);
                    this.isConnected = false;
                    reject(error);
                };

                this.ws.onclose = () => {
                    console.log('Disconnected from Snapcast server');
                    this.ws = null;
                    this.isConnected = false;
                };
            } catch (error) {
                reject(error);
            }
        });
    }

    private handleNotification(message: SnapcastResponse) {
        // Handle real-time updates from the server
        console.log('Received notification:', message.method, message.params);

        // Handle stream property updates (including metadata and playback state)
        if (message.method === 'Plugin.Stream.Player.Properties' || message.method === 'Stream.OnProperties') {
            const params = message.params;
            const streamId = params.id || params.stream_id || 'unknown';

            // Notify metadata listeners if metadata changed
            if (params && params.metadata) {
                console.log('Metadata update received for stream', streamId, ':', params.metadata);
                this.metadataUpdateListeners.forEach(listener => {
                    listener(streamId, params.metadata);
                });
            }

            // Notify playback state listeners if playback status changed
            if (params && params.playbackStatus !== undefined) {
                console.log('Playback state update received for stream', streamId, ':', params.playbackStatus);
                this.playbackStateListeners.forEach(listener => {
                    listener(streamId, params.playbackStatus, params);
                });
            }
        }
    }

    private sendRequest(method: string, params: any = {}): Promise<any> {
        return new Promise((resolve, reject) => {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN || !this.isConnected) {
                reject(new Error('WebSocket not connected'));
                return;
            }

            const id = this.messageId++;
            const request = {
                id,
                jsonrpc: '2.0',
                method,
                params
            };

            this.callbacks.set(id, (response: SnapcastResponse) => {
                if (response.result !== undefined) {
                    resolve(response.result);
                } else if (response.error) {
                    // Enhanced error reporting
                    const errorMsg = response.error.message || 'Unknown error';
                    const errorCode = response.error.code;
                    const errorData = response.error.data;
                    console.error(`Snapcast API Error [${errorCode}]: ${errorMsg}`, errorData);
                    reject(new Error(`${errorMsg} (Code: ${errorCode})`));
                } else {
                    reject(new Error('No result in response'));
                }
            });

            console.log('Sending request:', request);
            this.ws.send(JSON.stringify(request));

            // Timeout after 5 seconds
            setTimeout(() => {
                if (this.callbacks.has(id)) {
                    this.callbacks.delete(id);
                    reject(new Error('Request timeout'));
                }
            }, 5000);
        });
    }

    async getServerStatus(): Promise<any> {
        // Add a small delay to ensure connection is fully established
        await new Promise(resolve => setTimeout(resolve, 100));
        return this.sendRequest('Server.GetStatus');
    }

    // Get current stream status from server
    async getStreamStatus(streamId: string): Promise<SnapcastStream | null> {
        try {
            const serverStatus = await this.getServerStatus();
            const stream = serverStatus.server?.streams?.find((s: any) => s.id === streamId);
            return stream || null;
        } catch (error) {
            console.error(`Failed to get stream status for ${streamId}:`, error);
            return null;
        }
    }

    // Check if stream is currently playing based on its status and properties
    isStreamPlaying(stream: SnapcastStream | null): boolean {
        if (!stream) return false;

        // First check the playbackStatus property if available
        if (stream.properties?.playbackStatus) {
            const status = stream.properties.playbackStatus.toLowerCase();
            return status === 'playing';
        }

        // Fall back to the stream status field
        const status = stream.status?.toLowerCase();
        return status === 'playing';
    }

    // Set the stream for a specific group
    async setGroupStream(groupId: string, streamId: string): Promise<any> {
        console.log(`Setting group ${groupId} to stream ${streamId}`);
        return this.sendRequest('Group.SetStream', {
            id: groupId,
            stream_id: streamId
        });
    }

    // Set volume for a specific client
    async setClientVolume(clientId: string, volume: number, muted: boolean = false): Promise<any> {
        console.log(`Setting client ${clientId} volume to ${volume}% (muted: ${muted})`);
        return this.sendRequest('Client.SetVolume', {
            id: clientId,
            volume: {
                percent: volume,
                muted: muted
            }
        });
    }

    // Get stream properties - this will tell us what controls are available
    async getStreamProperties(streamId: string): Promise<SnapcastStreamProperties> {
        try {
            const serverStatus = await this.getServerStatus();
            const stream = serverStatus.server?.streams?.find((s: any) => s.id === streamId);
            console.log(`Stream ${streamId} properties:`, stream?.properties);
            return stream?.properties || {};
        } catch (error) {
            console.error(`Failed to get stream properties for ${streamId}:`, error);
            return {};
        }
    }

    // Use the correct Stream.Control method for playback commands [[1]](https://github.com/badaix/snapcast/blob/develop/doc/json_rpc_api/stream_plugin.md)
    private async sendStreamControl(streamId: string, command: string, params: any = {}): Promise<any> {
        console.log(`Sending Stream.Control command '${command}' to stream ${streamId}`, params);
        return this.sendRequest('Stream.Control', {
            id: streamId,
            command: command,
            params: params
        });
    }

    // Playback controls using the correct Stream.Control API
    async playStream(streamId: string): Promise<any> {
        const properties = await this.getStreamProperties(streamId);
        console.log(`Play stream ${streamId} - capabilities:`, properties);

        if (!properties.canPlay) {
            throw new Error(`Stream ${streamId} does not support play control`);
        }

        // Try the standard play command
        try {
            return await this.sendStreamControl(streamId, 'play');
        } catch (error) {
            // If play doesn't work, try playPause if currently paused
            console.warn('Direct play failed, trying playPause:', error);
            return await this.sendStreamControl(streamId, 'playPause');
        }
    }

    async pauseStream(streamId: string): Promise<any> {
        const properties = await this.getStreamProperties(streamId);
        console.log(`Pause stream ${streamId} - capabilities:`, properties);

        if (!properties.canPause) {
            throw new Error(`Stream ${streamId} does not support pause control`);
        }

        // Try the standard pause command
        try {
            return await this.sendStreamControl(streamId, 'pause');
        } catch (error) {
            // If pause doesn't work, try playPause [[1]](https://github.com/badaix/snapcast/blob/develop/doc/json_rpc_api/stream_plugin.md)
            console.warn('Direct pause failed, trying playPause:', error);
            return await this.sendStreamControl(streamId, 'playPause');
        }
    }

    async nextTrack(streamId: string): Promise<any> {
        const properties = await this.getStreamProperties(streamId);
        console.log(`Next track for stream ${streamId} - capabilities:`, properties);

        if (!properties.canGoNext) {
            throw new Error(`Stream ${streamId} does not support next track control`);
        }

        // Use the next command [[1]](https://github.com/badaix/snapcast/blob/develop/doc/json_rpc_api/stream_plugin.md)
        return this.sendStreamControl(streamId, 'next');
    }

    async previousTrack(streamId: string): Promise<any> {
        const properties = await this.getStreamProperties(streamId);
        console.log(`Previous track for stream ${streamId} - capabilities:`, properties);

        if (!properties.canGoPrevious) {
            throw new Error(`Stream ${streamId} does not support previous track control`);
        }

        // Use the previous command
        try {
            return await this.sendStreamControl(streamId, 'previous');
        } catch (error) {
            // Some plugins might use 'prev' instead
            console.warn('Previous failed, trying prev:', error);
            return await this.sendStreamControl(streamId, 'prev');
        }
    }

    async seekTo(streamId: string, position: number): Promise<any> {
        const properties = await this.getStreamProperties(streamId);
        if (!properties.canSeek) {
            throw new Error(`Stream ${streamId} does not support seek control`);
        }

        // Use the seek command with position parameter
        return this.sendStreamControl(streamId, 'seek', {position: position});
    }

    // Toggle play/pause - more reliable for many stream plugins
    async togglePlayPause(streamId: string): Promise<any> {
        const properties = await this.getStreamProperties(streamId);
        if (!properties.canPause) {
            throw new Error(`Stream ${streamId} does not support play/pause control`);
        }

        return this.sendStreamControl(streamId, 'playPause');
    }

    // Stop playback
    async stopStream(streamId: string): Promise<any> {
        console.log(`Stopping stream ${streamId}`);
        return this.sendStreamControl(streamId, 'stop');
    }

    // Check if stream supports various controls
    async getStreamCapabilities(streamId: string): Promise<{
        canPlay: boolean;
        canPause: boolean;
        canSeek: boolean;
        canGoNext: boolean;
        canGoPrevious: boolean;
        playbackStatus?: string;
    }> {
        try {
            const properties = await this.getStreamProperties(streamId);
            console.log(`Stream ${streamId} capabilities:`, properties);
            return {
                canPlay: properties.canPlay || false,
                canPause: properties.canPause || false,
                canSeek: properties.canSeek || false,
                canGoNext: properties.canGoNext || false,
                canGoPrevious: properties.canGoPrevious || false,
                playbackStatus: properties.playbackStatus || 'Unknown'
            };
        } catch (error) {
            console.error(`Failed to get stream capabilities for ${streamId}:`, error);
            return {
                canPlay: false,
                canPause: false,
                canSeek: false,
                canGoNext: false,
                canGoPrevious: false
            };
        }
    }

    // Get current playback state from stream properties
    async getPlaybackState(streamId: string): Promise<'playing' | 'paused' | 'stopped' | 'unknown'> {
        try {
            const properties = await this.getStreamProperties(streamId);
            const status = properties.playbackStatus?.toLowerCase();

            if (status === 'playing') return 'playing';
            if (status === 'paused') return 'paused';
            if (status === 'stopped') return 'stopped';

            return 'unknown';
        } catch (error) {
            console.error(`Failed to get playback state for stream ${streamId}:`, error);
            return 'unknown';
        }
    }

    // Find which group a client belongs to
    async findClientGroup(clientId: string): Promise<string | null> {
        try {
            const status = await this.getServerStatus();
            const {server} = status;

            if (server && server.groups) {
                for (const group of server.groups) {
                    if (group.clients && group.clients.some((client: any) => client.id === clientId)) {
                        return group.id;
                    }
                }
            }
            return null;
        } catch (error) {
            console.error('Error finding client group:', error);
            return null;
        }
    }

    /**
     * Get the base HTTP URL for the Snapcast server
     * Used for constructing cover art URLs
     */
    getHttpUrl(): string {
        return `http://${this.host}:${this.port}`;
    }

    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.callbacks.clear();
        this.isConnected = false;
    }
}

export const snapcastService = new SnapcastService();