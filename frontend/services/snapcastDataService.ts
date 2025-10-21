import {snapcastService} from './snapcastService';
import type {Client, Stream, Track} from '../types';

// Fixed album art placeholder SVG - clean music note icon
const DEFAULT_ALBUM_ART = `data:image/svg+xml;base64,${btoa(`
<svg width="400" height="400" viewBox="0 0 400 400" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect width="400" height="400" fill="#2A2A36"/>
  <circle cx="160" cy="280" r="35" fill="#F0F0F0"/>
  <circle cx="260" cy="260" r="35" fill="#F0F0F0"/>
  <rect x="155" y="150" width="10" height="130" fill="#F0F0F0"/>
  <rect x="255" y="130" width="10" height="130" fill="#F0F0F0"/>
  <path d="M165 150 L265 130 L265 180 L165 200 Z" fill="#F0F0F0"/>
</svg>
`)}`;

// Default fallback data for when no metadata is available
const createDefaultTrack = (): Track => ({
    id: 'unknown',
    title: 'Unknown Track',
    artist: 'Unknown Artist',
    album: 'Unknown Album',
    albumArtUrl: DEFAULT_ALBUM_ART,
    duration: 0,
});

const extractMetadataFromStream = (snapStream: any): {
    title?: string;
    artist?: string;
    album?: string;
    artUrl?: string;
    duration?: number
} => {
    console.log('Processing stream:', snapStream.id, snapStream);

    // Check for metadata in different possible locations
    let metadata: any = {};

    // Check if stream has properties with metadata
    if (snapStream.properties) {
        console.log('Stream properties found:', snapStream.properties);

        // Look for metadata in properties
        if (snapStream.properties.metadata) {
            metadata = snapStream.properties.metadata;
        } else if (snapStream.properties.meta) {
            metadata = snapStream.properties.meta;
        } else {
            // Check for individual metadata fields in properties
            metadata = {
                title: snapStream.properties.title || snapStream.properties.TITLE,
                artist: snapStream.properties.artist || snapStream.properties.ARTIST,
                album: snapStream.properties.album || snapStream.properties.ALBUM,
                artUrl: snapStream.properties.artUrl || snapStream.properties.ART_URL,
                duration: snapStream.properties.duration || snapStream.properties.DURATION
            };
        }
    }

    // Also check direct meta property on stream
    if (snapStream.meta) {
        console.log('Stream meta found:', snapStream.meta);
        metadata = {...metadata, ...snapStream.meta};
    }

    console.log('Extracted metadata:', metadata);
    return metadata;
};

const formatArtist = (artist: any): string => {
    if (Array.isArray(artist)) {
        return artist.join(', ');
    }
    return artist || 'Unknown Artist';
};

const getStreamName = (snapStream: any): string => {
    // Try to get a meaningful name from various sources
    if (snapStream.properties?.name) {
        return snapStream.properties.name;
    }

    // Use the name from URI query if available
    if (snapStream.uri?.query?.name) {
        return snapStream.uri.query.name;
    }

    if (snapStream.uri?.path) {
        const pathName = snapStream.uri.path.split('/').pop();
        if (pathName && pathName !== '') {
            return pathName;
        }
    }

    if (snapStream.uri?.raw) {
        return snapStream.uri.raw;
    }

    return `Stream ${snapStream.id}`;
};

const getSourceDevice = (snapStream: any): string => {
    // Try to extract source device info
    if (snapStream.uri?.scheme) {
        switch (snapStream.uri.scheme.toLowerCase()) {
            case 'pipe':
                return 'Named Pipe';
            case 'file':
                return 'File';
            case 'tcp':
                return 'TCP Stream';
            case 'alsa':
                return 'ALSA Device';
            case 'spotify':
                return 'Spotify Connect';
            case 'airplay':
                return 'AirPlay';
            default:
                return snapStream.uri.scheme.toUpperCase();
        }
    }

    return 'Unknown Source';
};

const convertSnapcastStreamToStream = (snapStream: any): Stream => {
    const metadata = extractMetadataFromStream(snapStream);

    const track: Track = {
        id: snapStream.id || 'unknown',
        title: metadata.title || 'Unknown Track',
        artist: formatArtist(metadata.artist),
        album: metadata.album || 'Unknown Album',
        albumArtUrl: metadata.artUrl || DEFAULT_ALBUM_ART,
        duration: metadata.duration || 0,
    };

    // Determine stream status - if playing or has valid metadata, it's playing
    const hasMetadata = metadata.title && metadata.title !== 'Unknown Track';
    const isPlaying = snapStream.status === 'playing' ||
        (snapStream.properties?.playbackStatus?.toLowerCase() === 'playing');
    const streamStatus = (isPlaying || hasMetadata) ? 'playing' : 'idle';

    return {
        id: snapStream.id,
        name: getStreamName(snapStream),
        sourceDevice: getSourceDevice(snapStream),
        currentTrack: track,
        isPlaying: isPlaying,
        progress: 0, // Snapcast doesn't provide current position in the status
        status: streamStatus,
    };
};

const convertSnapcastClientToClient = (snapClient: any, groupStreamId: string | null): Client => ({
    id: snapClient.id,
    name: snapClient.config?.name || snapClient.host?.name || 'Unknown Device',
    currentStreamId: groupStreamId,
    volume: snapClient.config?.volume?.percent || 0,
    isConnected: snapClient.connected !== false, // Track connection status
});

export const getSnapcastData = async (): Promise<{
    initialStreams: Stream[];
    initialClients: Client[];
    serverName?: string;
}> => {
    try {
        // Connect to Snapcast server
        await snapcastService.connect();

        // Get server status
        const serverStatus = await snapcastService.getServerStatus();
        console.log('Raw server status:', JSON.stringify(serverStatus, null, 2));

        const {server} = serverStatus;

        if (!server) {
            throw new Error('Invalid server response');
        }

        // Fix: Extract server name correctly as a string
        const serverName = server.server?.snapserver?.name ||
            server.server?.host?.name ||
            'Snapcast Server';
        console.log('Server name:', serverName);

        // Convert streams
        const initialStreams: Stream[] = server.streams?.map((snapStream: any) =>
            convertSnapcastStreamToStream(snapStream)
        ) || [];

        console.log('Converted streams:', initialStreams);

        // Convert clients from groups
        const initialClients: Client[] = [];

        if (server.groups) {
            console.log('Processing groups:', server.groups);
            server.groups.forEach((group: any) => {
                console.log('Group:', group.id, 'Stream:', group.stream_id, 'Clients:', group.clients?.length);
                if (group.clients) {
                    group.clients.forEach((client: any) => {
                        initialClients.push(convertSnapcastClientToClient(client, group.stream_id));
                    });
                }
            });
        }

        console.log('Converted clients:', initialClients);

        // If no clients found, create a default "You" client
        if (initialClients.length === 0) {
            initialClients.push({
                id: 'client-1',
                name: 'My Device (You)',
                currentStreamId: initialStreams.length > 0 ? initialStreams[0].id : null,
                volume: 75,
                isConnected: true,
            });
        }

        console.log('Snapcast data loaded:', {
            serverName,
            streamsCount: initialStreams.length,
            clientsCount: initialClients.length
        });

        return {
            initialStreams,
            initialClients,
            serverName
        };

    } catch (error) {
        console.error('Failed to connect to Snapcast server:', error);

        // Fallback to basic mock data structure with connection error info
        return {
            initialStreams: [{
                id: 'error-stream',
                name: 'Connection Error',
                sourceDevice: 'Snapcast Server Unavailable',
                currentTrack: createDefaultTrack(),
                isPlaying: false,
                progress: 0,
                status: 'idle',
            }],
            initialClients: [{
                id: 'client-1',
                name: 'My Device (You)',
                currentStreamId: 'error-stream',
                volume: 75,
                isConnected: true,
            }],
            serverName: 'Snapcast Server (Disconnected)'
        };
    }
};