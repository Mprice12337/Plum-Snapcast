import React from 'react';
import type {Stream, Settings} from '../types';
import {formatTime} from '../utils/time';

interface NowPlayingProps {
    stream: Stream | null;
    settings: Settings;
    hasActiveSource: boolean;
}

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

export const NowPlaying: React.FC<NowPlayingProps> = ({stream, settings, hasActiveSource}) => {
    // Determine if we should show standby mode
    const isStandby = !stream || !hasActiveSource || stream.status === 'idle';

    // Get enabled service names for standby display
    const getEnabledServices = () => {
        const services = [];
        if (settings.integrations.airplay) services.push('AirPlay');
        if (settings.integrations.spotifyConnect) services.push('Spotify Connect');
        if (settings.integrations.bluetooth) services.push('Bluetooth');
        if (settings.integrations.snapcast) services.push('Snapcast');
        return services;
    };

    if (isStandby) {
        const enabledServices = getEnabledServices();
        return (
            <div className="flex flex-col items-center justify-center gap-6 p-8 min-h-[300px]">
                <div className="flex-shrink-0">
                    <img
                        src={DEFAULT_ALBUM_ART}
                        alt="Standby mode"
                        className="w-48 h-48 md:w-56 md:h-56 rounded-lg shadow-lg object-cover opacity-50"
                    />
                </div>
                <div className="text-center">
                    <h2 className="text-2xl font-bold text-[var(--text-secondary)]">Ready to Play</h2>
                    {enabledServices.length > 0 && (
                        <p className="text-lg text-[var(--text-muted)] mt-2">
                            Available: {enabledServices.join(' • ')}
                        </p>
                    )}
                    <p className="text-sm text-[var(--text-muted)] mt-1">
                        Waiting for audio source...
                    </p>
                </div>
            </div>
        );
    }

    const {currentTrack, progress} = stream;
    const progressPercent = currentTrack.duration > 0
        ? (progress / currentTrack.duration) * 100
        : 0;

    // Use placeholder if no valid album art
    const albumArt = currentTrack.albumArtUrl &&
    currentTrack.albumArtUrl !== DEFAULT_ALBUM_ART &&
    !currentTrack.albumArtUrl.includes('Unknown')
        ? currentTrack.albumArtUrl
        : DEFAULT_ALBUM_ART;

    return (
        <div className="flex flex-col md:flex-row items-center gap-6 p-4">
            <div className="flex-shrink-0">
                <img
                    src={albumArt}
                    alt={`Album art for ${currentTrack.album}`}
                    className="w-48 h-48 md:w-56 md:h-56 rounded-lg shadow-lg object-cover transition-transform duration-300 hover:scale-105"
                    onError={(e) => {
                        const target = e.target as HTMLImageElement;
                        if (target.src !== DEFAULT_ALBUM_ART) {
                            target.src = DEFAULT_ALBUM_ART;
                        }
                    }}
                />
            </div>
            <div className="flex-1 text-center md:text-left w-full">
                <h2 className="text-3xl font-bold truncate" title={currentTrack.title}>
                    {currentTrack.title}
                </h2>
                <p className="text-lg text-[var(--text-secondary)] mt-1 truncate" title={currentTrack.artist}>
                    {currentTrack.artist}
                </p>
                <p className="text-md text-[var(--text-muted)] mt-1 truncate" title={currentTrack.album}>
                    {currentTrack.album}
                </p>

                <div className="mt-6 w-full">
                    <div className="bg-[var(--border-color)] rounded-full h-2 w-full">
                        <div
                            className="bg-[var(--accent-color)] h-2 rounded-full transition-all duration-1000 ease-linear"
                            style={{width: `${progressPercent}%`}}
                        />
                    </div>
                    <div className="flex justify-between text-xs text-[var(--text-muted)] mt-2">
                        <span>{formatTime(progress)}</span>
                        <span>{formatTime(currentTrack.duration)}</span>
                    </div>
                </div>
            </div>
        </div>
    );
};

// Export the default album art constant for use in other components
export {DEFAULT_ALBUM_ART};