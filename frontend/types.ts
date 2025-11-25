export interface Track {
    id: string;
    title: string;
    artist: string;
    album: string;
    albumArtUrl: string;
    duration: number; // in seconds
}

export interface Stream {
    id: string;
    name: string;
    sourceDevice: string;
    currentTrack: Track;
    isPlaying: boolean;
    progress: number; // in seconds
}

export interface Client {
    id: string;
    name: string;
    currentStreamId: string | null;
    volume: number; // 0-100
    connected: boolean;
}

export type AccentColor = 'purple' | 'blue' | 'green' | 'orange' | 'red';
export type ThemeMode = 'light' | 'dark' | 'system';

export interface Settings {
    integrations: {
        airplay: boolean;
        spotifyConnect: boolean;
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
}
