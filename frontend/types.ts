export interface Track {
    id: string;
    title: string;
    artist: string;
    album: string;
    albumArtUrl: string;
    duration: number; // in seconds
}

// Federation: Server representation
export interface Server {
    id: string;           // "server-192-168-7-122"
    name: string;         // "Main Server"
    host: string;         // "192.168.7.122"
    port: number;         // 1780
    connected: boolean;
    isLocal: boolean;
}

export interface Stream {
    id: string;                      // Federated ID: "server-192-168-7-122-airplay1"
    serverId?: string;               // "server-192-168-7-122" (for federation)
    serverName?: string;             // "Main Server" (for federation)
    name: string;
    sourceDevice: string;
    currentTrack: Track;
    isPlaying: boolean;
    progress: number; // in seconds
}

export interface Client {
    id: string;                      // Federated ID: "server-192-168-7-122-living-room"
    serverId?: string;               // "server-192-168-7-122" (for federation)
    serverName?: string;             // "Main Server" (for federation)
    name: string;
    currentStreamId: string | null;
    volume: number; // 0-100
    connected: boolean;
}

export type AccentColor = 'purple' | 'blue' | 'green' | 'orange' | 'red';
export type ThemeMode = 'light' | 'dark' | 'system';

export interface Settings {
    integrations: {
        airplay: {
            enabled: boolean;
            deviceName: string;
        };
        bluetooth: {
            enabled: boolean;
            deviceName: string;
            adapter: string;
            autoPair: boolean;
            discoverable: boolean;
        };
        spotify: {
            enabled: boolean;
            sourceName: string;
            deviceName: string;
            bitrate: 96 | 160 | 320;
        };
        dlna: {
            enabled: boolean;
            sourceName: string;
            deviceName: string;
        };
        snapcast: boolean;
        visualizer: boolean;
    };
    theme: {
        mode: ThemeMode;
        accent: AccentColor;
    };
    display: {
        showOfflineDevices: boolean;
    };
    federation: {
        enabled: boolean;
        autoDiscover: boolean;
        localServerName: string;
    };
}
