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

    const syncedClients = clients.filter(c => c.id !== myClient?.id && c.currentStreamId === myClient?.currentStreamId);
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
    }, [currentStream?.id]);

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
                if (isCancelled) return;

                console.error('Error loading Snapcast data:', error);
                setConnectionError('Failed to load Snapcast data');

                // Set minimal fallback data
                setStreams([]);
                setClients([{
                    id: 'client-1',
                    name: 'My Device (You)',
                    currentStreamId: null,
                    volume: 75,
                }]);
            } finally {
                if (!isCancelled) {
                    setIsLoading(false);
                }
            }
        };

        fetchData();

        return () => {
            isCancelled = true;
        };
    }, []); // Empty dependency array - only run once

    const handleVolumeChange = async (clientId: string, volume: number) => {
        // Update local state immediately for responsiveness
        setClients(prevClients =>
            prevClients.map(c => (c.id === clientId ? {...c, volume} : c))
        );

        // Send to Snapcast server
        try {
            await snapcastService.setClientVolume(clientId, volume);
            console.log(`Successfully set volume for client ${clientId} to ${volume}%`);
        } catch (error) {
            console.error(`Failed to set volume for client ${clientId}:`, error);
            // Could revert local state here if needed
        }
    };

    const handleGroupVolumeAdjust = (streamId: string | null, direction: 'up' | 'down') => {
        if (!streamId) return;
        const adjustment = direction === 'up' ? VOLUME_STEP : -VOLUME_STEP;

        setClients(prevClients => {
            const updatedClients = prevClients.map(c => {
                if (c.currentStreamId === streamId) {
                    const newVolume = Math.max(0, Math.min(100, c.volume + adjustment));

                    // Send volume change to server for this client
                    snapcastService.setClientVolume(c.id, newVolume).catch(error => {
                        console.error(`Failed to adjust volume for client ${c.id}:`, error);
                    });

                    return {...c, volume: newVolume};
                }
                return c;
            });

            return updatedClients;
        });
    };

    const handleGroupMute = (streamId: string | null) => {
        if (!streamId) return;

        const isMuted = preMuteGroupVolumes[streamId];

        if (isMuted) {
            setClients(prevClients =>
                prevClients.map(c => {
                    if (c.currentStreamId === streamId && preMuteGroupVolumes[streamId][c.id] !== undefined) {
                        const restoredVolume = preMuteGroupVolumes[streamId][c.id];

                        // Unmute on server
                        snapcastService.setClientVolume(c.id, restoredVolume, false).catch(error => {
                            console.error(`Failed to unmute client ${c.id}:`, error);
                        });

                        return {...c, volume: restoredVolume};
                    }
                    return c;
                })
            );
            setPreMuteGroupVolumes(prev => {
                const newPreMuteVolumes = {...prev};
                delete newPreMuteVolumes[streamId];
                return newPreMuteVolumes;
            });
        } else {
            const volumesToStore: Record<string, number> = {};
            clients.forEach(c => {
                if (c.currentStreamId === streamId) {
                    volumesToStore[c.id] = c.volume;
                }
            });

            if (Object.keys(volumesToStore).length > 0) {
                setPreMuteGroupVolumes(prev => ({
                    ...prev,
                    [streamId]: volumesToStore,
                }));
            }

            setClients(prevClients =>
                prevClients.map(c => {
                    if (c.currentStreamId === streamId) {
                        // Mute on server
                        snapcastService.setClientVolume(c.id, 0, true).catch(error => {
                            console.error(`Failed to mute client ${c.id}:`, error);
                        });

                        return {...c, volume: 0};
                    }
                    return c;
                })
            );
        }
    };

    const handleStreamChange = async (clientId: string, streamId: string | null) => {
        console.log(`Changing stream for client ${clientId} to ${streamId}`);

        // Update local state immediately for responsiveness
        setClients(prevClients =>
            prevClients.map(c => (c.id === clientId ? {...c, currentStreamId: streamId} : c))
        );

        // Send to Snapcast server
        try {
            const groupId = clientGroupMap[clientId];
            if (groupId && streamId) {
                await snapcastService.setGroupStream(groupId, streamId);
                console.log(`Successfully changed group ${groupId} to stream ${streamId}`);
            } else if (groupId && streamId === null) {
                // For setting to "no stream", we might need a different approach
                // This depends on how Snapcast handles idle streams
                console.log(`Setting group ${groupId} to idle (stream: null)`);
                // You might need to set it to a default idle stream instead
            } else {
                console.warn(`Could not find group for client ${clientId}`);
            }
        } catch (error) {
            console.error(`Failed to change stream for client ${clientId}:`, error);

            // Revert local state on error
            setClients(prevClients =>
                prevClients.map(c => (c.id === clientId ? {...c, currentStreamId: c.currentStreamId} : c))
            );
        }
    };

    const handlePlayPause = async () => {
        if (!currentStream) return;

        console.log('Play/Pause button clicked for stream:', currentStream.id);

        try {
            // Check stream capabilities first
            const capabilities = await snapcastService.getStreamCapabilities(currentStream.id);
            console.log('Stream capabilities:', capabilities);

            if (currentStream.isPlaying) {
                // Try to pause
                if (capabilities.canPause) {
                    await snapcastService.pauseStream(currentStream.id);
                    setStreams(prevStreams =>
                        prevStreams.map(s =>
                            s.id === currentStream.id ? {...s, isPlaying: false} : s
                        )
                    );
                    console.log(`Successfully paused stream ${currentStream.id}`);
                } else {
                    console.log(`Stream ${currentStream.id} does not support pause`);
                }
            } else {
                // Try to play
                if (capabilities.canPlay) {
                    await snapcastService.playStream(currentStream.id);
                    setStreams(prevStreams =>
                        prevStreams.map(s =>
                            s.id === currentStream.id ? {...s, isPlaying: true} : s
                        )
                    );
                    console.log(`Successfully started playing stream ${currentStream.id}`);
                } else {
                    console.log(`Stream ${currentStream.id} does not support play`);
                }
            }
        } catch (error) {
            console.error(`Playback control failed for stream ${currentStream.id}:`, error);
        }
    };

    const handleSkip = async (direction: 'next' | 'prev') => {
        if (!currentStream) return;

        console.log(`Skip ${direction} button clicked for stream:`, currentStream.id);

        try {
            // Check stream capabilities first
            const capabilities = await snapcastService.getStreamCapabilities(currentStream.id);

            if (direction === 'next') {
                if (capabilities.canGoNext) {
                    await snapcastService.nextTrack(currentStream.id);
                    console.log(`Successfully skipped to next track for stream ${currentStream.id}`);
                } else {
                    console.log(`Stream ${currentStream.id} does not support next track`);
                }
            } else {
                if (capabilities.canGoPrevious) {
                    await snapcastService.previousTrack(currentStream.id);
                    console.log(`Successfully skipped to previous track for stream ${currentStream.id}`);
                } else {
                    console.log(`Stream ${currentStream.id} does not support previous track`);
                }
            }
        } catch (error) {
            console.error(`Skip ${direction} failed for stream ${currentStream.id}:`, error);
        }
    };

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
        <div
            className="min-h-screen bg-[var(--bg-primary)] text-[var(--text-primary)] font-sans p-4 md:p-8 flex flex-col">
            {connectionError && (
                <div className="w-full max-w-7xl mx-auto mb-4 p-4 bg-red-600/20 border border-red-600/30 rounded-lg">
                    <div className="flex items-center">
                        <i className="fas fa-exclamation-triangle text-red-400 mr-2"></i>
                        <span className="text-red-400">{connectionError}</span>
                    </div>
                </div>
            )}

            <div className="w-full max-w-7xl mx-auto flex-grow grid grid-cols-1 lg:grid-cols-3 gap-8">

                <div className="lg:col-span-2 bg-[var(--bg-secondary)] p-6 rounded-2xl shadow-2xl flex flex-col">
                    <div className="border-b border-[var(--border-color)] pb-4">
                        <div className="flex items-center justify-between mb-4">
                            <h1 className="text-xl font-semibold text-[var(--accent-color)]">{serverName}</h1>
                            <div className="flex items-center text-sm text-[var(--text-muted)]">
                                <i className="fas fa-broadcast-tower mr-2"></i>
                                <span>Connected</span>
                            </div>
                        </div>
                        <StreamSelector
                            streams={streams}
                            currentStreamId={myClient.currentStreamId}
                            onSelectStream={(streamId) => handleStreamChange(myClient.id, streamId)}
                        />
                    </div>
                    {currentStream ? (
                        <div className="flex-grow flex flex-col">
                            <div className="space-y-6">
                                <NowPlaying stream={currentStream}/>
                                <PlayerControls
                                    stream={currentStream}
                                    volume={myClient.volume}
                                    onVolumeChange={(vol) => handleVolumeChange(myClient.id, vol)}
                                    onPlayPause={handlePlayPause}
                                    onSkip={handleSkip}
                                />
                            </div>
                            <SyncedDevices
                                clients={syncedClients}
                                streams={streams}
                                onVolumeChange={handleVolumeChange}
                                onStreamChange={handleStreamChange}
                                onGroupVolumeAdjust={(dir) => handleGroupVolumeAdjust(myClient.currentStreamId, dir)}
                                onGroupMute={() => handleGroupMute(myClient.currentStreamId)}
                            />
                        </div>
                    ) : (
                        <div
                            className="flex-grow flex flex-col items-center justify-center bg-[var(--bg-secondary)] rounded-lg p-8 h-full min-h-[300px]">
                            <i className="fas fa-music text-6xl text-[var(--text-muted)] mb-4"></i>
                            <h2 className="text-2xl font-semibold text-[var(--text-secondary)]">No Stream Selected</h2>
                            <p className="text-[var(--text-muted)] mt-2">Choose a source to begin.</p>
                        </div>
                    )}
                </div>

                <div className="space-y-8">
                    <div className="bg-[var(--bg-secondary)] p-6 rounded-2xl shadow-2xl">
                        <h2 className="text-2xl font-bold text-[var(--accent-color)] border-b border-[var(--border-color)] pb-4 mb-4">Other
                            Streams &amp; Devices</h2>
                        <ClientManager
                            clients={otherClients}
                            streams={streams}
                            myClientStreamId={myClient.currentStreamId}
                            onVolumeChange={handleVolumeChange}
                            onStreamChange={handleStreamChange}
                            onGroupVolumeAdjust={handleGroupVolumeAdjust}
                            onGroupMute={handleGroupMute}
                        />
                    </div>
                </div>
            </div>
            <footer
                className="w-full max-w-7xl mx-auto grid grid-cols-3 items-center text-[var(--text-muted)] mt-12 text-sm">
                <div>{/* Spacer */}</div>
                <p className="text-center">Sync Audio Controller &copy; 2024</p>
                <div className="flex justify-end">
                    <button
                        onClick={() => setIsSettingsOpen(true)}
                        className="p-2 rounded-full hover:bg-[var(--bg-secondary)]"
                        aria-label="Open Settings"
                    >
                        <i className="fas fa-cog text-lg"></i>
                    </button>
                </div>
            </footer>
            {isSettingsOpen && (
                <SettingsModal
                    settings={settings}
                    onSettingsChange={setSettings}
                    onClose={() => setIsSettingsOpen(false)}
                />
            )}
        </div>
    );
};

export default App;