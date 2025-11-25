import React, {useEffect, useRef, useState} from 'react';
import type {Client, Stream} from '../types';
import {GroupVolumeControl} from './GroupVolumeControl';

interface ClientManagerProps {
    clients: Client[];
    streams: Stream[];
    myClientStreamId: string | null;
    onVolumeChange: (clientId: string, volume: number) => void;
    onStreamChange: (clientId: string, streamId: string | null) => void;
    onGroupVolumeAdjust: (streamId: string, direction: 'up' | 'down') => void;
    onGroupMute: (streamId: string) => void;
    onStartBrowserAudio?: () => void;
    browserAudioActive?: boolean;
}

const ClientDevice: React.FC<{
    client: Client;
    streams: Stream[];
    onVolumeChange: (clientId: string, volume: number) => void;
    onStreamChange: (clientId: string, streamId: string | null) => void;
}> = ({client, streams, onVolumeChange, onStreamChange}) => {
    const [isSelectorOpen, setIsSelectorOpen] = useState(false);
    const wrapperRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
                setIsSelectorOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, [wrapperRef]);

    const handleSelectStream = (streamId: string | null) => {
        onStreamChange(client.id, streamId);
        setIsSelectorOpen(false);
    };

    const volumePercentage = client.volume;
    const sliderStyle = {
        background: `linear-gradient(to right, var(--accent-color) ${volumePercentage}%, var(--border-color) ${volumePercentage}%)`
    };
    return (
        <div className="flex items-center gap-3">
            <span className="flex-1 truncate font-semibold">{client.name}</span>
            <div className="flex items-center gap-2 w-40">
                <i className="fas fa-volume-high w-4 text-[var(--text-secondary)]"></i>
                <input
                    type="range"
                    min="0"
                    max="100"
                    value={client.volume}
                    onChange={(e) => onVolumeChange(client.id, Number(e.target.value))}
                    className="w-full h-2 rounded-lg appearance-none cursor-pointer volume-slider"
                    style={sliderStyle}
                />
            </div>
            <div ref={wrapperRef} className="relative">
                <button
                    onClick={() => setIsSelectorOpen(!isSelectorOpen)}
                    className="w-8 h-8 flex items-center justify-center rounded-full text-[var(--text-secondary)] bg-[var(--border-color)] hover:bg-[var(--bg-secondary-hover)] transition-colors"
                    title="Change Stream"
                >
                    <i className="fas fa-tower-broadcast"></i>
                </button>
                {isSelectorOpen && (
                    <div
                        className="absolute z-10 bottom-full right-0 mb-2 w-48 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg shadow-xl">
                        <ul className="py-1 text-sm text-[var(--text-primary)] max-h-40 overflow-auto">
                            <li role="option">
                                <button
                                    onClick={() => handleSelectStream(null)}
                                    className="block w-full text-left px-3 py-2 text-[var(--text-secondary)] hover:bg-[var(--bg-secondary-hover)]"
                                >
                                    None
                                </button>
                            </li>
                            {streams.map(s => (
                                <li key={s.id} role="option" aria-selected={client.currentStreamId === s.id}>
                                    <button
                                        onClick={() => handleSelectStream(s.id)}
                                        className={`block w-full text-left px-3 py-2 hover:bg-[var(--bg-secondary-hover)] transition-colors truncate ${client.currentStreamId === s.id ? 'font-semibold text-[var(--accent-color)]' : ''}`}
                                    >
                                        {s.name}
                                    </button>
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
            </div>
        </div>
    );
};

export const ClientManager: React.FC<ClientManagerProps> = ({
                                                                clients,
                                                                streams,
                                                                myClientStreamId,
                                                                onVolumeChange,
                                                                onStreamChange,
                                                                onGroupVolumeAdjust,
                                                                onGroupMute,
                                                                onStartBrowserAudio,
                                                                browserAudioActive,
                                                            }) => {
    const groupedClients = clients.reduce((acc, client) => {
        const streamId = client.currentStreamId ?? 'idle';
        if (!acc[streamId]) {
            acc[streamId] = [];
        }
        acc[streamId].push(client);
        return acc;
    }, {} as Record<string, Client[]>);

    const {idle: idleClients, ...streamedClients} = groupedClients;
    const streamGroups = Object.entries(streamedClients);

    // Show listen button if available, even when no other clients
    if (clients.length === 0) {
        return (
            <div className="space-y-6">
                <div className="text-center py-4">
                    <i className="fas fa-desktop text-4xl text-[var(--icon-muted)] mb-3"></i>
                    <p className="text-[var(--text-muted)]">No other active devices.</p>
                </div>
                {onStartBrowserAudio && !browserAudioActive && (
                    <div className="bg-[var(--bg-tertiary)] p-4 rounded-lg">
                        <button
                            onClick={onStartBrowserAudio}
                            className="w-full bg-[var(--accent-color)] text-white font-bold py-3 px-4 rounded-lg hover:bg-[var(--accent-color-hover)] transition-colors flex items-center justify-center gap-2"
                        >
                            <i className="fas fa-headphones"></i>
                            Listen in Browser
                        </button>
                    </div>
                )}
            </div>
        );
    }

    return (
        <div className="space-y-6">
            {streamGroups.map(([streamId, clientsInGroup]) => {
                const stream = streams.find(s => s.id === streamId);
                if (!stream) return null;

                // Type assertion to ensure TypeScript knows clientsInGroup is Client[]
                const typedClientsInGroup = clientsInGroup as Client[];

                return (
                    <div key={streamId} className="bg-[var(--bg-tertiary)] p-4 rounded-lg">
                        <div className="border-b border-[var(--border-color)] pb-3 mb-3">
                            <h3 className="font-bold text-lg truncate text-[var(--text-primary)]">{stream.name}</h3>
                            <p className="text-sm text-[var(--text-secondary)] truncate">
                                <i className="fas fa-music mr-2 text-[var(--text-muted)]"></i>
                                {stream.currentTrack.title}
                            </p>
                        </div>
                        <div className="space-y-3">
                            {typedClientsInGroup.map(client => (
                                <ClientDevice key={client.id} client={client} streams={streams}
                                              onVolumeChange={onVolumeChange} onStreamChange={onStreamChange}/>
                            ))}
                        </div>
                        {typedClientsInGroup.length > 1 && (
                            <GroupVolumeControl
                                onAdjust={(dir) => onGroupVolumeAdjust(streamId, dir)}
                                onMute={() => onGroupMute(streamId)}
                            />
                        )}
                    </div>
                );
            })}

            {idleClients && idleClients.length > 0 && (
                <div className="bg-[var(--bg-tertiary)] p-4 rounded-lg">
                    <h3 className="font-bold text-lg text-[var(--text-primary)] border-b border-[var(--border-color)] pb-3 mb-3">Idle
                        Devices</h3>
                    <div className="space-y-2">
                        {idleClients.map(client => (
                            <div key={client.id}
                                 className="flex items-center justify-between p-2 rounded-lg hover:bg-[var(--bg-tertiary-hover)]">
                                <span className="font-semibold">{client.name}</span>
                                <button
                                    onClick={() => onStreamChange(client.id, myClientStreamId)}
                                    disabled={!myClientStreamId}
                                    className="text-sm bg-[var(--accent-color)] text-white font-bold py-1 px-3 rounded-full hover:bg-[var(--accent-color-hover)] transition-colors disabled:bg-gray-500 disabled:cursor-not-allowed"
                                    title={myClientStreamId ? 'Join your current stream' : 'Select a stream first'}
                                >
                                    <i className="fas fa-plus mr-1"></i>
                                    Join Stream
                                </button>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {onStartBrowserAudio && !browserAudioActive && (
                <div className="bg-[var(--bg-tertiary)] p-4 rounded-lg">
                    <button
                        onClick={onStartBrowserAudio}
                        className="w-full bg-[var(--accent-color)] text-white font-bold py-3 px-4 rounded-lg hover:bg-[var(--accent-color-hover)] transition-colors flex items-center justify-center gap-2"
                    >
                        <i className="fas fa-headphones"></i>
                        Listen in Browser
                    </button>
                </div>
            )}
        </div>
    );
};