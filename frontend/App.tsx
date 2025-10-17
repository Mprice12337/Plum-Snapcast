import React, {useCallback, useEffect, useState} from 'react';
import {NowPlaying} from './components/NowPlaying';
import {PlayerControls} from './components/PlayerControls';
import {StreamSelector} from './components/StreamSelector';
import {ClientManager} from './components/ClientManager';
import {SyncedDevices} from './components/SyncedDevices';
import {Settings as SettingsModal} from './components/Settings';
import {getSnapcastData} from './services/snapcastDataService';
import {snapcastService} from './services/snapcastService';
import type {Client, Settings, Stream} from './types';
import {useAudioSync} from './hooks/useAudioSync';

const MY_CLIENT_ID = 'client-1';
const VOLUME_STEP = 5;

const App: React.FC = () => {
    const [streams, setStreams] = useState<Stream[]>([]);
    const [clients, setClients] = useState<Client[]>([]);
    const [serverName, setServerName] = useState<string>('Snapcast Server');
    const [isLoading, setIsLoading] = useState(true);
    const [connectionError, setConnectionError] = useState<string | null>(null);
    const [preMuteGroupVolumes, setPreMuteGroupVolumes] = useState<Record<string, Record<string, number>>>({});
    const [isSettingsOpen, setIsSettingsOpen] = useState(false);
    const [settings, setSettings] = useState<Settings>({
        integrations: {
            airplay: true,
            spotifyConnect: false,
            bluetooth: false, // Added bluetooth
            snapcast: true,
            visualizer: false,
        },
        theme: {
            mode: 'dark',
            accent: 'purple',
        }
    });

    // Store group mappings for clients
    const [clientGroupMap, setClientGroupMap] = useState<Record<string, string>>({});

    useEffect(() => {
        const root = document.documentElement;

        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
        const handleSystemThemeChange = (e: MediaQueryListEvent) => {
            if (settings.theme.mode === 'system') {
                root.setAttribute('data-theme', e.matches ? 'dark' : 'light');
            }
        };

        if (settings.theme.mode === 'system') {
            root.setAttribute('data-theme', mediaQuery.matches ? 'dark' : 'light');
            mediaQuery.addEventListener('change', handleSystemThemeChange);
        } else {
            root.setAttribute('data-theme', settings.theme.mode);
            mediaQuery.removeEventListener('change', handleSystemThemeChange);
        }

        root.setAttribute('data-accent', settings.theme.accent);

        return () => {
            mediaQuery.removeEventListener('change', handleSystemThemeChange);
        };
    }, [settings.theme]);

    // Find the client that represents "you" - first try client-1, then first available
    const myClient = clients.find(c => c.id === MY_CLIENT_ID) || clients[0];
    const currentStream = streams.find(s => s.id === myClient?.currentStreamId);

    // Determine if there's an active audio source
    const hasActiveSource = currentStream?.isPlaying ?? false;

    // Get synced devices (other clients on same stream, excluding yourself)
    const syncedClients = clients.filter(c =>
        c.id !== myClient?.id &&
        c.currentStreamId === myClient?.currentStreamId &&
        c.isConnected !== false // Only include connected clients
    );

    // Check if we're streaming out to other devices
    const isStreamingOut = hasActiveSource && syncedClients.length > 0;

    const otherClients = clients.filter(c => c.currentStreamId !== myClient?.currentStreamId);

    const updateStreamProgress = useCallback((streamId: string, newProgress: number) => {
        setStreams(prevStreams =>
            prevStreams.map(s =>
                s.id === streamId
                    ? {...s, progress: Math.min(newProgress, s.currentTrack.duration)}
                    : s
            )
        );
    }, []);

    useAudioSync(currentStream, updateStreamProgress);

    // Periodically sync stream status with server
    useEffect(() => {
        if (!currentStream || !snapcastService) return;

        const syncStreamStatus = async () => {
            try {
                const serverStream = await snapcastService.getStreamStatus(currentStream.id);
                if (serverStream) {
                    const isPlaying = snapcastService.isStreamPlaying(serverStream);

                    // Only update if the status has changed
                    if (isPlaying !== currentStream.isPlaying) {
                        setStreams(prevStreams =>
                            prevStreams.map(s =>
                                s.id === currentStream.id ? {...s, isPlaying} : s
                            )
                        );
                    }
                }
            } catch (error) {
                // Silently handle errors to avoid spam
            }
        };

        // Sync immediately and then every 5 seconds
        syncStreamStatus();
        const interval = setInterval(syncStreamStatus, 5000);

        return () => clearInterval(interval);
    }, [currentStream?.id, currentStream?.isPlaying]);

    useEffect(() => {
        let isCancelled = false;

        const fetchData = async () => {
            if (!isLoading) return; // Prevent multiple calls

            setConnectionError(null);

            try {
                console.log('Fetching Snapcast data...');
                const {initialStreams, initialClients, serverName: snapServerName} = await getSnapcastData();

                if (isCancelled) return; // Don't update state if component unmounted

                setStreams(initialStreams);
                setClients(initialClients);
                setServerName(snapServerName || 'Snapcast Server');

                // Build client to group mapping
                try {
                    const serverStatus = await snapcastService.getServerStatus();
                    const groupMap: Record<string, string> = {};

                    if (serverStatus.server && serverStatus.server.groups) {
                        serverStatus.server.groups.forEach((group: any) => {
                            if (group.clients) {
                                group.clients.forEach((client: any) => {
                                    groupMap[client.id] = group.id;
                                });
                            }
                        });
                    }

                    setClientGroupMap(groupMap);
                    console.log('Client group mapping:', groupMap);
                } catch (error) {
                    console.warn('Could not build client group mapping:', error);
                }

                console.log('Data set successfully:', {
                    streamsCount: initialStreams.length,
                    clientsCount: initialClients.length,
                    firstClient: initialClients[0]
                });

                // Check if we got error data (connection failed)
                if (initialStreams.length === 1 && initialStreams[0].id === 'error-stream') {
                    setConnectionError('Unable to connect to Snapcast server. Please check your configuration.');
                }
            } catch (error) {
                console.error('Error fetching data:', error);
                setConnectionError('Failed to load Snapcast data. Please check your connection.');
            } finally {
                setIsLoading(false);
            }
        };

        fetchData();

        return () => {
            isCancelled = true;
        };
    }, []);

    const handleVolumeChange = useCallback(async (newVolume: number) => {
        if (!myClient) return;

        const oldVolume = myClient.volume;
        setClients(prevClients =>
            prevClients.map(c => c.id === myClient.id ? {...c, volume: newVolume} : c)
        );

        try {
            await snapcastService.setClientVolume(myClient.id, newVolume);
        } catch (error) {
            console.error('Failed to set volume:', error);
            setClients(prevClients =>
                prevClients.map(c => c.id === myClient.id ? {...c, volume: oldVolume} : c)
            );
        }
    }, [myClient]);

    const handleStreamChange = useCallback(async (streamId: string | null) => {
        if (!myClient) return;

        const groupId = clientGroupMap[myClient.id];
        if (!groupId) {
            console.error('Could not find group for client:', myClient.id);
            return;
        }

        const oldStreamId = myClient.currentStreamId;
        setClients(prevClients =>
            prevClients.map(c => c.id === myClient.id ? {...c, currentStreamId: streamId} : c)
        );

        try {
            if (streamId) {
                await snapcastService.setGroupStream(groupId, streamId);
            }
        } catch (error) {
            console.error('Failed to change stream:', error);
            setClients(prevClients =>
                prevClients.map(c => c.id === myClient.id ? {...c, currentStreamId: oldStreamId} : c)
            );
        }
    }, [myClient, clientGroupMap]);

    const handleSyncedClientVolumeChange = useCallback(async (clientId: string, newVolume: number) => {
        const client = clients.find(c => c.id === clientId);
        if (!client) return;

        const oldVolume = client.volume;
        setClients(prevClients =>
            prevClients.map(c => c.id === clientId ? {...c, volume: newVolume} : c)
        );

        try {
            await snapcastService.setClientVolume(clientId, newVolume);
        } catch (error) {
            console.error('Failed to set synced client volume:', error);
            setClients(prevClients =>
                prevClients.map(c => c.id === clientId ? {...c, volume: oldVolume} : c)
            );
        }
    }, [clients]);

    const handleSyncedClientStreamChange = useCallback(async (clientId: string, streamId: string | null) => {
        const groupId = clientGroupMap[clientId];
        if (!groupId) {
            console.error('Could not find group for client:', clientId);
            return;
        }

        const client = clients.find(c => c.id === clientId);
        if (!client) return;

        const oldStreamId = client.currentStreamId;
        setClients(prevClients =>
            prevClients.map(c => c.id === clientId ? {...c, currentStreamId: streamId} : c)
        );

        try {
            if (streamId) {
                await snapcastService.setGroupStream(groupId, streamId);
            }
        } catch (error) {
            console.error('Failed to change synced client stream:', error);
            setClients(prevClients =>
                prevClients.map(c => c.id === clientId ? {...c, currentStreamId: oldStreamId} : c)
            );
        }
    }, [clients, clientGroupMap]);

    const handleOtherClientVolumeChange = useCallback(async (clientId: string, newVolume: number) => {
        const client = clients.find(c => c.id === clientId);
        if (!client) return;

        const oldVolume = client.volume;
        setClients(prevClients =>
            prevClients.map(c => c.id === clientId ? {...c, volume: newVolume} : c)
        );

        try {
            await snapcastService.setClientVolume(clientId, newVolume);
        } catch (error) {
            console.error('Failed to set other client volume:', error);
            setClients(prevClients =>
                prevClients.map(c => c.id === clientId ? {...c, volume: oldVolume} : c)
            );
        }
    }, [clients]);

    const handleOtherClientStreamChange = useCallback(async (clientId: string, streamId: string | null) => {
        const groupId = clientGroupMap[clientId];
        if (!groupId) {
            console.error('Could not find group for client:', clientId);
            return;
        }

        const client = clients.find(c => c.id === clientId);
        if (!client) return;

        const oldStreamId = client.currentStreamId;
        setClients(prevClients =>
            prevClients.map(c => c.id === clientId ? {...c, currentStreamId: streamId} : c)
        );

        try {
            if (streamId) {
                await snapcastService.setGroupStream(groupId, streamId);
            }
        } catch (error) {
            console.error('Failed to change other client stream:', error);
            setClients(prevClients =>
                prevClients.map(c => c.id === clientId ? {...c, currentStreamId: oldStreamId} : c)
            );
        }
    }, [clients, clientGroupMap]);

    const handleGroupVolumeAdjust = useCallback(async (direction: 'up' | 'down') => {
        if (!myClient || !currentStream) return;

        const groupClients = clients.filter(c => c.currentStreamId === myClient.currentStreamId);
        const adjustment = direction === 'up' ? VOLUME_STEP : -VOLUME_STEP;

        const oldVolumes = groupClients.map(c => ({id: c.id, volume: c.volume}));

        setClients(prevClients =>
            prevClients.map(c => {
                if (c.currentStreamId === myClient.currentStreamId) {
                    return {...c, volume: Math.max(0, Math.min(100, c.volume + adjustment))};
                }
                return c;
            })
        );

        try {
            await Promise.all(
                groupClients.map(c =>
                    snapcastService.setClientVolume(c.id, Math.max(0, Math.min(100, c.volume + adjustment)))
                )
            );
        } catch (error) {
            console.error('Failed to adjust group volume:', error);
            setClients(prevClients =>
                prevClients.map(c => {
                    const oldVol = oldVolumes.find(ov => ov.id === c.id);
                    return oldVol ? {...c, volume: oldVol.volume} : c;
                })
            );
        }
    }, [myClient, currentStream, clients]);

    const handleGroupMute = useCallback(async () => {
        if (!myClient || !currentStream) return;

        const groupId = clientGroupMap[myClient.id];
        if (!groupId) return;

        const groupClients = clients.filter(c => c.currentStreamId === myClient.currentStreamId);

        const currentlyMuted = preMuteGroupVolumes[groupId] !== undefined;

        if (currentlyMuted) {
            const savedVolumes = preMuteGroupVolumes[groupId];
            setClients(prevClients =>
                prevClients.map(c => {
                    if (c.currentStreamId === myClient.currentStreamId && savedVolumes[c.id] !== undefined) {
                        return {...c, volume: savedVolumes[c.id]};
                    }
                    return c;
                })
            );

            try {
                await Promise.all(
                    Object.entries(savedVolumes).map(([clientId, volume]) =>
                        snapcastService.setClientVolume(clientId, volume)
                    )
                );
                setPreMuteGroupVolumes(prev => {
                    const next = {...prev};
                    delete next[groupId];
                    return next;
                });
            } catch (error) {
                console.error('Failed to unmute group:', error);
            }
        } else {
            const volumeMap: Record<string, number> = {};
            groupClients.forEach(c => {
                volumeMap[c.id] = c.volume;
            });

            setPreMuteGroupVolumes(prev => ({...prev, [groupId]: volumeMap}));

            setClients(prevClients =>
                prevClients.map(c =>
                    c.currentStreamId === myClient.currentStreamId ? {...c, volume: 0} : c
                )
            );

            try {
                await Promise.all(
                    groupClients.map(c => snapcastService.setClientVolume(c.id, 0))
                );
            } catch (error) {
                console.error('Failed to mute group:', error);
                setPreMuteGroupVolumes(prev => {
                    const next = {...prev};
                    delete next[groupId];
                    return next;
                });
            }
        }
    }, [myClient, currentStream, clients, clientGroupMap, preMuteGroupVolumes]);

    const handleOtherGroupVolumeAdjust = useCallback(async (streamId: string, direction: 'up' | 'down') => {
        const groupClients = clients.filter(c => c.currentStreamId === streamId);
        const adjustment = direction === 'up' ? VOLUME_STEP : -VOLUME_STEP;

        const oldVolumes = groupClients.map(c => ({id: c.id, volume: c.volume}));

        setClients(prevClients =>
            prevClients.map(c => {
                if (c.currentStreamId === streamId) {
                    return {...c, volume: Math.max(0, Math.min(100, c.volume + adjustment))};
                }
                return c;
            })
        );

        try {
            await Promise.all(
                groupClients.map(c =>
                    snapcastService.setClientVolume(c.id, Math.max(0, Math.min(100, c.volume + adjustment)))
                )
            );
        } catch (error) {
            console.error('Failed to adjust other group volume:', error);
            setClients(prevClients =>
                prevClients.map(c => {
                    const oldVol = oldVolumes.find(ov => ov.id === c.id);
                    return oldVol ? {...c, volume: oldVol.volume} : c;
                })
            );
        }
    }, [clients]);

    const handleOtherGroupMute = useCallback(async (streamId: string) => {
        const groupClients = clients.filter(c => c.currentStreamId === streamId);
        const currentlyMuted = preMuteGroupVolumes[streamId] !== undefined;

        if (currentlyMuted) {
            const savedVolumes = preMuteGroupVolumes[streamId];
            setClients(prevClients =>
                prevClients.map(c => {
                    if (c.currentStreamId === streamId && savedVolumes[c.id] !== undefined) {
                        return {...c, volume: savedVolumes[c.id]};
                    }
                    return c;
                })
            );

            try {
                await Promise.all(
                    Object.entries(savedVolumes).map(([clientId, volume]) =>
                        snapcastService.setClientVolume(clientId, volume)
                    )
                );
                setPreMuteGroupVolumes(prev => {
                    const next = {...prev};
                    delete next[streamId];
                    return next;
                });
            } catch (error) {
                console.error('Failed to unmute other group:', error);
            }
        } else {
            const volumeMap: Record<string, number> = {};
            groupClients.forEach(c => {
                volumeMap[c.id] = c.volume;
            });

            setPreMuteGroupVolumes(prev => ({...prev, [streamId]: volumeMap}));

            setClients(prevClients =>
                prevClients.map(c =>
                    c.currentStreamId === streamId ? {...c, volume: 0} : c
                )
            );

            try {
                await Promise.all(
                    groupClients.map(c => snapcastService.setClientVolume(c.id, 0))
                );
            } catch (error) {
                console.error('Failed to mute other group:', error);
                setPreMuteGroupVolumes(prev => {
                    const next = {...prev};
                    delete next[streamId];
                    return next;
                });
            }
        }
    }, [clients, preMuteGroupVolumes]);

    const handlePlayPause = useCallback(async () => {
        if (!currentStream) return;

        try {
            const capabilities = await snapcastService.getStreamCapabilities(currentStream.id);
            if (currentStream.isPlaying && capabilities.canPause) {
                await snapcastService.pauseStream(currentStream.id);
                setStreams(prevStreams =>
                    prevStreams.map(s =>
                        s.id === currentStream.id ? {...s, isPlaying: false} : s
                    )
                );
            } else if (!currentStream.isPlaying && capabilities.canPlay) {
                await snapcastService.playStream(currentStream.id);
                setStreams(prevStreams =>
                    prevStreams.map(s =>
                        s.id === currentStream.id ? {...s, isPlaying: true} : s
                    )
                );
            }
        } catch (error) {
            console.error('Play/Pause failed:', error);
        }
    }, [currentStream]);

    const handleSkip = useCallback(async (direction: 'next' | 'prev') => {
        if (!currentStream) return;

        try {
            const capabilities = await snapcastService.getStreamCapabilities(currentStream.id);
            if (direction === 'next' && capabilities.canGoNext) {
                await snapcastService.nextTrack(currentStream.id);
            } else if (direction === 'prev' && capabilities.canGoPrevious) {
                await snapcastService.previousTrack(currentStream.id);
            }
        } catch (error) {
            console.error(`Skip ${direction} failed for stream ${currentStream.id}:`, error);
        }
    }, [currentStream]);

    // Debug logging
    console.log('App render state:', {
        isLoading,
        streamsCount: streams.length,
        clientsCount: clients.length,
        myClient: myClient?.id,
        currentStream: currentStream?.id
    });

    if (isLoading) {
        return (
            <div className="flex items-center justify-center min-h-screen bg-[var(--bg-primary)]">
                <div className="text-center">
                    <i className="fas fa-spinner fa-spin text-5xl text-[var(--accent-color)]"></i>
                    <p className="mt-4 text-lg text-[var(--text-secondary)]">Connecting to Snapcast Server...</p>
                    <p className="mt-2 text-sm text-[var(--text-muted)]">{serverName}</p>
                </div>
            </div>
        );
    }

    if (!myClient) {
        return (
            <div className="flex items-center justify-center min-h-screen bg-[var(--bg-primary)]">
                <div className="text-center">
                    <i className="fas fa-exclamation-triangle text-5xl text-red-400"></i>
                    <p className="mt-4 text-lg text-[var(--text-secondary)]">No clients found</p>
                    <p className="mt-2 text-sm text-[var(--text-muted)]">Unable to load client data from Snapcast
                        server</p>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-[var(--bg-primary)] text-[var(--text-primary)] font-sans p-4 md:p-8">
            <div className="max-w-4xl mx-auto">
                {/* Header */}
                <div className="flex items-center justify-between mb-8">
                    <div>
                        <h1 className="text-3xl font-bold">Plum Audio</h1>
                        <p className="text-sm text-[var(--text-muted)] mt-1">{serverName}</p>
                    </div>
                    <button
                        onClick={() => setIsSettingsOpen(true)}
                        className="w-10 h-10 flex items-center justify-center rounded-full text-[var(--text-secondary)] bg-[var(--border-color)] hover:bg-[var(--bg-secondary-hover)] transition-colors"
                        aria-label="Settings"
                    >
                        <i className="fas fa-cog"></i>
                    </button>
                </div>

                {connectionError && (
                    <div className="mb-4 p-4 bg-red-900/20 border border-red-500/50 rounded-lg text-red-200">
                        <i className="fas fa-exclamation-triangle mr-2"></i>
                        {connectionError}
                    </div>
                )}

                {/* Main Card */}
                <div className="bg-[var(--bg-secondary)] rounded-xl shadow-2xl overflow-hidden mb-6">
                    <NowPlaying
                        stream={currentStream || null}
                        settings={settings}
                        hasActiveSource={hasActiveSource}
                    />

                    <div className="px-6 pb-6">
                        <PlayerControls
                            stream={currentStream || null}
                            volume={myClient?.volume || 0}
                            onVolumeChange={handleVolumeChange}
                            onPlayPause={handlePlayPause}
                            onSkip={handleSkip}
                            hasActiveSource={hasActiveSource}
                        />

                        <SyncedDevices
                            clients={syncedClients}
                            streams={streams}
                            onVolumeChange={handleSyncedClientVolumeChange}
                            onStreamChange={handleSyncedClientStreamChange}
                            onGroupVolumeAdjust={handleGroupVolumeAdjust}
                            onGroupMute={handleGroupMute}
                            isStreaming={isStreamingOut}
                        />
                    </div>
                </div>

                {/* Stream Selector and Client Manager */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <StreamSelector
                        streams={streams}
                        currentStreamId={currentStream?.id || null}
                        onSelectStream={handleStreamChange}
                    />
                    <ClientManager
                        clients={otherClients}
                        streams={streams}
                        myClientStreamId={myClient?.currentStreamId || null}
                        onVolumeChange={handleOtherClientVolumeChange}
                        onStreamChange={handleOtherClientStreamChange}
                        onGroupVolumeAdjust={handleOtherGroupVolumeAdjust}
                        onGroupMute={handleOtherGroupMute}
                    />
                </div>
            </div>

            <SettingsModal
                isOpen={isSettingsOpen}
                onClose={() => setIsSettingsOpen(false)}
                settings={settings}
                onSettingsChange={setSettings}
            />
        </div>
    );
};

export default App;