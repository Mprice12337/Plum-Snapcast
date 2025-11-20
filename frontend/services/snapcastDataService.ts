import {snapcastService} from './snapcastService';
import type {Client, Stream, Track} from '../types';

// Default fallback data for when no metadata is available
const createDefaultTrack = (): Track => ({
    id: 'unknown',
    title: 'Unknown Track',
    artist: 'Unknown Artist',
    album: 'Unknown Album',
    albumArtUrl: 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDAwIiBoZWlnaHQ9IjQwMCIgdmlld0JveD0iMCAwIDQwMCA0MDAiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjQwMCIgaGVpZ2h0PSI0MDAiIGZpbGw9IiMyQTJBMzYiLz4KICA8cGF0aCBkPSJNMjgwIDgwVjI3MEMyODAgMjcwIDI4MCAyOTAgMjYwIDI5MEMyNDAgMjkwIDIzMCAyODAgMjMwIDI3MEMyMzAgMjYwIDI0MCAyNTAgMjYwIDI1MEMyNzAgMjUwIDI4MCAyNTUgMjgwIDI1NVYxNDBMMTYwIDE3MFYzMDBDMTYwIDMwMCAxNjAgMzIwIDE0MCAzMjBDMTIwIDMyMCAxMTAgMzEwIDExMCAzMDBDMTEwIDI5MCAxMjAgMjgwIDE0MCAyODBDMTUwIDI4MCAxNjAgMjg1IDE2MCAyODVWMTUwTDI4MCAxMjBWODBaIiBmaWxsPSIjRjBGMEYwIi8+Cjwvc3ZnPgo=',
    duration: 0,
});

const extractMetadataFromStream = (snapStream: any): {
    title?: string;
    artist?: string;
    album?: string;
    artUrl?: string;
    duration?: number
} => {
    // Check for metadata in different possible locations
    let metadata: any = {};

    // Check if stream has properties with metadata
    if (snapStream.properties) {

        // Look for metadata in properties
        if (snapStream.properties.metadata) {
            // Snapcast control script metadata format (simple field names)
            const meta = snapStream.properties.metadata;
            metadata = {
                // Simple field names (title, artist, album, artUrl)
                title: meta.title || meta.name,
                artist: Array.isArray(meta.artist) ? meta.artist.join(', ') : meta.artist,
                album: meta.album,
                artUrl: meta.artUrl,
                duration: meta.duration
            };
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
        metadata = {...metadata, ...snapStream.meta};
    }

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

const convertSnapcastStreamToStream = async (snapStream: any): Promise<Stream> => {
    const metadata = extractMetadataFromStream(snapStream);

    // Handle artwork URL from metadata
    let albumArtUrl = createDefaultTrack().albumArtUrl;

    if (metadata.artUrl) {
        // Check if it's a data URL (embedded image)
        if (metadata.artUrl.startsWith('data:')) {
            // Data URL - use directly
            albumArtUrl = metadata.artUrl;
        } else if (metadata.artUrl.startsWith('/')) {
            // Relative path - prepend Snapcast HTTP server URL
            albumArtUrl = `${snapcastService.getHttpUrl()}${metadata.artUrl}`;
        } else {
            // Absolute URL - use directly
            albumArtUrl = metadata.artUrl;
        }
    }

    const track: Track = {
        id: snapStream.id || 'unknown',
        title: metadata.title || 'Unknown Track',
        artist: formatArtist(metadata.artist),
        album: metadata.album || 'Unknown Album',
        albumArtUrl: albumArtUrl,
        duration: metadata.duration || 0,
    };

    // Determine if stream is playing - check properties.playbackStatus first, then fall back to status
    let isPlaying = false;
    if (snapStream.properties?.playbackStatus && snapStream.properties.playbackStatus.toLowerCase() !== 'unknown') {
        // Use playbackStatus from control script (more accurate) - but ignore "unknown"
        isPlaying = snapStream.properties.playbackStatus.toLowerCase() === 'playing';
    } else {
        // Fall back to stream status
        isPlaying = snapStream.status === 'playing';
    }

    return {
        id: snapStream.id,
        name: getStreamName(snapStream),
        sourceDevice: getSourceDevice(snapStream),
        currentTrack: track,
        isPlaying: isPlaying,
        progress: 0, // Snapcast doesn't provide current position in the status
    };
};

const convertSnapcastClientToClient = (snapClient: any, groupStreamId: string | null): Client => ({
    id: snapClient.id,
    name: snapClient.config?.name || snapClient.host?.name || 'Unknown Device',
    currentStreamId: groupStreamId,
    volume: snapClient.config?.volume?.percent || 0,
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
        const {server} = serverStatus;

        if (!server) {
            throw new Error('Invalid server response');
        }

        // Fix: Extract server name correctly as a string
        const serverName = server.server?.snapserver?.name ||
            server.server?.host?.name ||
            'Snapcast Server';

        // Convert streams (now async to fetch artwork)
        const streamPromises = server.streams?.map((snapStream: any) =>
            convertSnapcastStreamToStream(snapStream)
        ) || [];
        const initialStreams: Stream[] = await Promise.all(streamPromises);

        // Convert clients from groups
        const initialClients: Client[] = [];

        if (server.groups) {
            server.groups.forEach((group: any) => {
                if (group.clients) {
                    group.clients.forEach((client: any) => {
                        initialClients.push(convertSnapcastClientToClient(client, group.stream_id));
                    });
                }
            });
        }

        // If no clients found, create a default "You" client
        if (initialClients.length === 0) {
            initialClients.push({
                id: 'client-1',
                name: 'My Device (You)',
                currentStreamId: initialStreams.length > 0 ? initialStreams[0].id : null,
                volume: 75,
            });
        }

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
            }],
            initialClients: [{
                id: 'client-1',
                name: 'My Device (You)',
                currentStreamId: 'error-stream',
                volume: 75,
            }],
            serverName: 'Snapcast Server (Disconnected)'
        };
    }
};