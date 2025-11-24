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
import {useBrowserAudioClient} from './hooks/useBrowserAudioClient';

const VOLUME_STEP = 5;

const App: React.FC = () => {
    const [streams, setStreams] = useState<Stream[]>([]);
    const [clients, setClients] = useState<Client[]>([]);
    const [serverName, setServerName] = useState<string>('Snapcast Server');
    const [streamCapabilities, setStreamCapabilities] = useState<{canSeek?: boolean}>({});
    const [isLoading, setIsLoading] = useState(true);
    const [connectionError, setConnectionError] = useState<string | null>(null);
    const [preMuteGroupVolumes, setPreMuteGroupVolumes] = useState<Record<string, Record<string, number>>>({});
    const [isSettingsOpen, setIsSettingsOpen] = useState(false);

    // Track recent user-initiated playback changes to prevent polling from overwriting them
    const [recentPlaybackChange, setRecentPlaybackChange] = useState<{streamId: string, timestamp: number} | null>(null);

    // Load settings from localStorage or use defaults
    const [settings, setSettings] = useState<Settings>(() => {
        try {
            const saved = localStorage.getItem('snapcast-settings');
            if (saved) {
                return JSON.parse(saved);
            }
        } catch (error) {
            console.error('Failed to load settings from localStorage:', error);
        }

        // Default settings
        return {
            integrations: {
                airplay: true,
                spotifyConnect: false,
                snapcast: true,
                visualizer: false,
            },
            theme: {
                mode: 'dark',
                accent: 'purple',
            },
            display: {
                showOfflineDevices: true,
            }
        };
    });

    // Store group mappings for clients
    const [clientGroupMap, setClientGroupMap] = useState<Record<string, string>>({});

    // Browser audio client for "Listen in Browser" functionality
    const browserAudio = useBrowserAudioClient(window.location.hostname);

    // Track if we've already auto-assigned the browser client to prevent loops
    const [browserClientAutoAssigned, setBrowserClientAutoAssigned] = useState(false);
    // Capture the target stream when "Listen in Browser" is clicked
    const [targetStreamForBrowserAudio, setTargetStreamForBrowserAudio] = useState<string | null>(null);

    // Persist settings to localStorage whenever they change
    useEffect(() => {
        try {
            localStorage.setItem('snapcast-settings', JSON.stringify(settings));
        } catch (error) {
            console.error('Failed to save settings to localStorage:', error);
        }
    }, [settings]);

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

    // Find the primary client to control
    // Prefer MAC address format (integrated snapclient on Raspberry Pi), otherwise use first client
    // Exclude browser audio client from being selected as primary
    const myClient = clients.find(c =>
        c.id !== browserAudio.state.clientId &&
        /^[0-9a-f]{2}(:[0-9a-f]{2}){5}$/i.test(c.id)
    ) || clients.find(c => c.id !== browserAudio.state.clientId);
    const currentStream = streams.find(s => s.id === myClient?.currentStreamId);

    // Auto-assign browser audio client to user's current stream when it connects
    useEffect(() => {
        if (!browserAudio.state.isActive) {
            // Reset flags when browser audio is stopped
            setBrowserClientAutoAssigned(false);
            setTargetStreamForBrowserAudio(null);
            return;
        }

        // Check if browser client exists in client list (server has recognized it)
        // Note: Browser audio client might not report as connected immediately, but if it exists, we can assign it
        const browserClient = clients.find(c => c.id === browserAudio.state.clientId);
        if (!browserClient) {
            return; // Server hasn't reported it yet
        }

        // Skip if already auto-assigned
        if (browserClientAutoAssigned) {
            return;
        }

        // Use the captured target stream (from when button was clicked)
        // Fall back to myClient's current stream if target wasn't captured
        const targetStream = targetStreamForBrowserAudio || myClient?.currentStreamId;

        // Always assign to target stream if we have one
        // This handles both new connections and reconnections with stale stream assignments
        if (targetStream && browserClient.currentStreamId !== targetStream) {
            handleStreamChange(browserAudio.state.clientId, targetStream);
        }

        if (targetStream) {
            setBrowserClientAutoAssigned(true);
        }
    }, [browserAudio.state.isActive, browserAudio.state.clientId, clients, myClient, browserClientAutoAssigned, targetStreamForBrowserAudio, streams]);

    // Update browser client name and volume if server has reported it
    // Volume is managed locally (not synced to server), so override with local state
    const allClients = clients.map(c => {
        // If this is our browser audio client, ensure proper naming and local volume
        if (browserAudio.state.isActive && c.id === browserAudio.state.clientId) {
            return {
                ...c,
                // Use a friendly name instead of "snapweb"
                name: c.name.toLowerCase().includes('snapweb') ? 'Browser Audio' : c.name,
                // Override volume with local state (browser audio volume is local only)
                volume: browserAudio.state.volume
            };
        }
        return c;
    });

    // Add placeholder if browser audio is active but server hasn't reported it yet
    if (browserAudio.state.isActive) {
        const serverHasClient = clients.some(c => c.id === browserAudio.state.clientId);

        if (!serverHasClient) {
            // Server hasn't seen the client yet - add temporary placeholder
            const browserClient: Client = {
                id: browserAudio.state.clientId,
                name: 'Browser Audio (Connecting...)',
                currentStreamId: null,
                volume: browserAudio.state.volume,
                connected: false
            };
            allClients.push(browserClient);
        }
    }

    // Helper function to detect if a client should be hidden
    // Hide snapweb clients that aren't our active browser audio client
    const shouldHideClient = (client: Client): boolean => {
        // If this is our active browser audio client, NEVER hide it (check ID first!)
        if (client.id === browserAudio.state.clientId && browserAudio.state.isActive) {
            return false;
        }

        // Hide other snapweb/browser clients (auto-created by server)
        const browserIndicators = ['snapweb', 'browser'];
        const clientName = client.name.toLowerCase();
        const isSnapwebClient = browserIndicators.some(indicator => clientName.includes(indicator));

        return isSnapwebClient;
    };

    // Filter clients based on settings
    // Always show browser audio client when active, regardless of offline device setting
    const filteredClients = settings.display.showOfflineDevices
        ? allClients
        : allClients.filter(c =>
            c.connected || (c.id === browserAudio.state.clientId && browserAudio.state.isActive)
        );

    // Synced clients: same stream as myClient, excluding myClient itself, applying same hiding rules
    const syncedClients = filteredClients.filter(c =>
        c.id !== myClient?.id &&
        c.currentStreamId === myClient?.currentStreamId &&
        !shouldHideClient(c)
    );

    // Other clients: all clients EXCEPT myClient and synced clients
    const otherClients = filteredClients.filter(c =>
        c.id !== myClient?.id &&
        c.currentStreamId !== myClient?.currentStreamId &&
        !shouldHideClient(c)
    );

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

    // Clean up recent playback change after grace period expires
    useEffect(() => {
        if (!recentPlaybackChange) return;

        const gracePeriod = 8000;
        const timeRemaining = gracePeriod - (Date.now() - recentPlaybackChange.timestamp);

        if (timeRemaining > 0) {
            const timeout = setTimeout(() => {
                setRecentPlaybackChange(null);
            }, timeRemaining);

            return () => clearTimeout(timeout);
        } else {
            setRecentPlaybackChange(null);
        }
    }, [recentPlaybackChange]);

    // Listen for real-time metadata updates from Snapcast
    useEffect(() => {
        if (!snapcastService) return;

        const unsubscribe = snapcastService.onMetadataUpdate((streamId, metadata) => {
            // Debug: Log all metadata updates
            console.log(`[Metadata] Update received:`, {
                streamId,
                hasTitle: !!metadata.title,
                hasArtist: !!metadata.artist,
                hasAlbum: !!metadata.album,
                hasArtUrl: metadata.artUrl !== undefined,
                artUrlPreview: metadata.artUrl ? metadata.artUrl.substring(0, 50) + '...' : 'none'
            });

            // Update the stream with new metadata
            // IMPORTANT: Metadata updates are instant and indicate the stream is actively playing
            setStreams(prevStreams =>
                prevStreams.map(stream => {
                    if (stream.id === streamId) {
                        // Detect if this is a new track (title changed)
                        const isNewTrack = metadata.title && metadata.title !== stream.currentTrack.title;

                        console.log(`[Metadata] Track analysis:`, {
                            isNewTrack,
                            oldTitle: stream.currentTrack.title,
                            newTitle: metadata.title,
                            currentArtUrl: stream.currentTrack.albumArtUrl?.substring(0, 50) + '...'
                        });

                        // Update track metadata
                        const updatedTrack = {
                            ...stream.currentTrack,
                            title: metadata.title || stream.currentTrack.title,
                            artist: metadata.artist || stream.currentTrack.artist,
                            album: metadata.album || stream.currentTrack.album,
                            // Update duration when it changes (convert from ms to seconds)
                            duration: metadata.duration ? Math.floor(metadata.duration / 1000) : stream.currentTrack.duration,
                        };

                        // Handle artwork updates:
                        // - If artwork explicitly provided and valid → use it
                        // - If new track but no artwork yet → clear to default
                        // - Otherwise → keep current artwork (for partial metadata updates)
                        const artUrlType = metadata.artUrl === undefined ? 'undefined' : metadata.artUrl === null ? 'null' : metadata.artUrl === '' ? 'empty' : 'valid';
                        const artUrlPreview = metadata.artUrl ? `${metadata.artUrl.substring(0, 50)}...` : String(metadata.artUrl);
                        console.log(`[Metadata] artUrl received: type=${artUrlType}, preview=${artUrlPreview}`);

                        if (metadata.artUrl && metadata.artUrl.trim() !== '') {
                            console.log(`[Metadata] ✓ Using provided artwork (${metadata.artUrl.length} chars)`);
                            updatedTrack.albumArtUrl = metadata.artUrl;
                        } else if (isNewTrack) {
                            console.log(`[Metadata] ⚠ New track without artwork - using placeholder`);
                            updatedTrack.albumArtUrl = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDAwIiBoZWlnaHQ9IjQwMCIgdmlld0JveD0iMCAwIDQwMCA0MDAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxyZWN0IHdpZHRoPSI0MDAiIGhlaWdodD0iNDAwIiBmaWxsPSIjMkEyQTM2Ii8+CjxnIHRyYW5zZm9ybT0idHJhbnNsYXRlKDEwMCwgMTAwKSBzY2FsZSgxMi41KSI+CjxwYXRoIGZpbGw9IiNGMEYwRjAiIGQ9Ik00IDN2OS40Yy0wLjQtMC4yLTAuOS0wLjQtMS41LTAuNC0xLjQgMC0yLjUgMC45LTIuNSAyczEuMSAyIDIuNSAyIDIuNS0wLjkgMi41LTJ2LTcuM2w3LTIuM3Y1LjFjLTAuNC0wLjMtMC45LTAuNS0xLjUtMC41LTEuNCAwLTIuNSAwLjktMi41IDJzMS4xIDIgMi41IDIgMi41LTAuOSAyLjUtMnYtMTFsLTkgM3oiPjwvcGF0aD4KPC9nPgo8L3N2Zz4K';
                        } else {
                            console.log(`[Metadata] → Keeping existing artwork (partial update)`);
                        }
                        // else: keep stream.currentTrack.albumArtUrl (already in updatedTrack from spread)

                        // When we receive metadata, the stream is actively playing
                        // This gives us instant state feedback instead of waiting for stream.status
                        const wasPlaying = stream.isPlaying;
                        const nowPlaying = true; // Metadata = audio is flowing = playing

                        // Check if there's a recent user-initiated pause (grace period)
                        const now = Date.now();
                        const gracePeriod = 8000;
                        const hasRecentPause = recentPlaybackChange &&
                            recentPlaybackChange.streamId === streamId &&
                            (now - recentPlaybackChange.timestamp) < gracePeriod;

                        // If user just paused, don't override with metadata-based playing state
                        const finalPlayingState = hasRecentPause ? stream.isPlaying : nowPlaying;

                        if (!wasPlaying && finalPlayingState && !hasRecentPause) {
                            console.log(`[Metadata] Stream ${streamId} started playing (metadata received)`);
                        }

                        return {
                            ...stream,
                            currentTrack: updatedTrack,
                            isPlaying: finalPlayingState,
                            // Reset progress to 0 when new track starts
                            progress: isNewTrack ? 0 : stream.progress
                        };
                    }
                    return stream;
                })
            );
        });

        return () => unsubscribe();
    }, [recentPlaybackChange]);

    // Listen for real-time playback state updates from Snapcast
    useEffect(() => {
        if (!snapcastService) return;

        const unsubscribe = snapcastService.onPlaybackStateUpdate(async (streamId, playbackStatus, properties) => {
            // Handle refresh signal - fetch latest state for all streams
            if (playbackStatus === 'REFRESH') {
                // Fetch latest state for all streams
                const serverStatus = await snapcastService.getServerStatus();
                if (serverStatus && serverStatus.server && serverStatus.server.streams) {
                    setStreams(prevStreams =>
                        prevStreams.map(stream => {
                            const serverStream = serverStatus.server.streams.find((s: any) => s.id === stream.id);
                            if (serverStream) {
                                const isPlaying = snapcastService.isStreamPlaying(serverStream);
                                if (stream.isPlaying !== isPlaying) {
                                    console.log(`[PlaybackState] Stream ${stream.id} updated: ${stream.isPlaying} → ${isPlaying}`);
                                }
                                return {
                                    ...stream,
                                    isPlaying: isPlaying
                                };
                            }
                            return stream;
                        })
                    );
                }
                return;
            }

            // Handle direct playback status update
            const isPlaying = playbackStatus.toLowerCase() === 'playing';

            // Update the stream's playing state
            setStreams(prevStreams =>
                prevStreams.map(stream => {
                    if (stream.id === streamId) {
                        if (stream.isPlaying !== isPlaying) {
                            console.log(`[WebSocket] Stream ${streamId} playback state: ${stream.isPlaying ? 'Playing' : 'Paused'} → ${isPlaying ? 'Playing' : 'Paused'}`);
                        }
                        return {
                            ...stream,
                            isPlaying: isPlaying
                        };
                    }
                    return stream;
                })
            );
        });

        return () => unsubscribe();
    }, []);

    // Listen for real-time position updates from Snapcast (for sources that support it)
    useEffect(() => {
        if (!snapcastService) return;

        const unsubscribe = snapcastService.onPositionUpdate((streamId, position, duration) => {
            // Position and duration come in milliseconds from backend, convert to seconds
            const progressInSeconds = Math.floor(position / 1000);

            // Update stream progress
            updateStreamProgress(streamId, progressInSeconds);
        });

        return () => unsubscribe();
    }, [updateStreamProgress]);

    // Fetch stream capabilities when current stream changes
    useEffect(() => {
        if (!currentStream || !snapcastService) {
            setStreamCapabilities({});
            return;
        }

        const fetchCapabilities = async () => {
            try {
                const capabilities = await snapcastService.getStreamCapabilities(currentStream.id);
                setStreamCapabilities({
                    canSeek: capabilities.canSeek || false
                });
            } catch (error) {
                console.error('Failed to fetch stream capabilities:', error);
                setStreamCapabilities({canSeek: false});
            }
        };

        fetchCapabilities();
    }, [currentStream?.id]);

    // Periodically retry fetching artwork when showing placeholder
    // AirPlay artwork can take 1-10 seconds to arrive in the backend cache
    useEffect(() => {
        if (!currentStream) return;

        // Check if current stream has placeholder artwork
        const hasPlaceholder = currentStream.currentTrack.albumArtUrl?.startsWith('data:image/svg+xml;base64');

        if (!hasPlaceholder) return; // No need to retry if we have real artwork

        console.log(`[ArtworkRetry] ⏱ Starting periodic check for "${currentStream.currentTrack.title}"`);

        let attemptCount = 0;
        const retryInterval = setInterval(async () => {
            attemptCount++;
            try {
                console.log(`[ArtworkRetry] Attempt ${attemptCount}/15: Checking backend...`);
                const freshStream = await snapcastService.getStreamStatus(currentStream.id);
                const artUrl = freshStream?.properties?.metadata?.artUrl;
                const artUrlType = artUrl === undefined ? 'undefined' : artUrl === null ? 'null' : artUrl === '' ? 'empty' : 'valid';

                console.log(`[ArtworkRetry] Backend responded: artUrl type=${artUrlType}`);

                if (artUrl && artUrl.trim() !== '') {
                    console.log(`[ArtworkRetry] ✓ SUCCESS! Found artwork (${artUrl.length} chars) - applying and stopping retry`);
                    setStreams(prev => prev.map(s =>
                        s.id === currentStream.id
                            ? {...s, currentTrack: {...s.currentTrack, albumArtUrl: artUrl}}
                            : s
                    ));
                    // Stop retrying once we found artwork
                    clearInterval(retryInterval);
                } else {
                    console.log(`[ArtworkRetry] ⏳ No artwork yet, will retry in 1s...`);
                }
            } catch (error) {
                console.error(`[ArtworkRetry] ✗ Request failed:`, error);
            }
        }, 1000); // Check every 1 second

        // Stop retrying after 15 seconds (artwork should have arrived by then)
        const timeout = setTimeout(() => {
            console.log(`[ArtworkRetry] ⏹ Timeout: Giving up after 15 seconds - artwork may not be available for this track`);
            clearInterval(retryInterval);
        }, 15000);

        return () => {
            clearInterval(retryInterval);
            clearTimeout(timeout);
        };
    }, [currentStream?.id, currentStream?.currentTrack.albumArtUrl, currentStream?.currentTrack.title]);

    // Periodically sync metadata AND playback state with server as fallback
    // This ensures GUI stays in sync even if WebSocket notifications fail
    useEffect(() => {
        if (!currentStream || !snapcastService) return;

        const syncStreamState = async () => {
            try {
                const serverStream = await snapcastService.getStreamStatus(currentStream.id);
                if (serverStream) {
                    const isPlaying = snapcastService.isStreamPlaying(serverStream);

                    // Extract metadata from stream properties (simple field names)
                    let updatedMetadata = null;
                    if (serverStream.properties?.metadata) {
                        const meta = serverStream.properties.metadata;

                        // Handle artwork URL properly (same as snapcastDataService.ts)
                        let albumArtUrl = undefined;
                        if (meta.artUrl) {
                            if (meta.artUrl.startsWith('data:')) {
                                // Data URL - use directly
                                albumArtUrl = meta.artUrl;
                            } else if (meta.artUrl.startsWith('/')) {
                                // Relative path - prepend Snapcast HTTP server URL
                                albumArtUrl = `${snapcastService.getHttpUrl()}${meta.artUrl}`;
                            } else {
                                // Absolute URL - use directly
                                albumArtUrl = meta.artUrl;
                            }
                        }

                        updatedMetadata = {
                            title: meta.title || meta.name,
                            artist: Array.isArray(meta.artist) ? meta.artist.join(', ') : meta.artist,
                            album: meta.album,
                            albumArtUrl: albumArtUrl,
                            // Convert duration from milliseconds to seconds
                            duration: meta.duration ? Math.floor(meta.duration / 1000) : undefined
                        };

                        // Debug: Log what we got from server
                        console.log(`[Polling] Server metadata:`, {
                            hasTitle: !!updatedMetadata.title,
                            hasArtist: !!updatedMetadata.artist,
                            hasAlbum: !!updatedMetadata.album,
                            hasArtUrl: updatedMetadata.albumArtUrl !== undefined,
                            artUrlPreview: updatedMetadata.albumArtUrl ? updatedMetadata.albumArtUrl.substring(0, 50) + '...' : 'none'
                        });
                    }

                    // Update stream with latest state AND metadata
                    setStreams(prevStreams =>
                        prevStreams.map(s => {
                            if (s.id === currentStream.id) {
                                const updatedStream = { ...s };

                                // Check if there's a recent user-initiated playback change
                                const now = Date.now();
                                const gracePeriod = 8000; // 8 seconds grace period
                                const hasRecentChange = recentPlaybackChange &&
                                    recentPlaybackChange.streamId === s.id &&
                                    (now - recentPlaybackChange.timestamp) < gracePeriod;

                                // Update playback state if changed (but respect grace period)
                                if (s.isPlaying !== isPlaying) {
                                    if (hasRecentChange) {
                                        console.log(`[Polling] Ignoring state change during grace period (${Math.round((gracePeriod - (now - recentPlaybackChange.timestamp!)) / 1000)}s remaining)`);
                                    } else {
                                        console.log(`[Polling] Stream ${s.id} playback state changed: ${s.isPlaying} → ${isPlaying}`);
                                        updatedStream.isPlaying = isPlaying;

                                        // If transitioning from paused to playing and artwork is placeholder, immediately refresh
                                        // This handles the case where user skips while paused and artwork doesn't arrive until playback resumes
                                        if (!s.isPlaying && isPlaying) {
                                            const isDefaultArtwork = s.currentTrack.albumArtUrl?.startsWith('data:image/svg+xml;base64');
                                            if (isDefaultArtwork) {
                                                console.log(`[Polling] Playback resumed with placeholder artwork - fetching fresh metadata`);
                                                // Immediately fetch fresh metadata to get artwork that may have arrived when playback resumed
                                                setTimeout(() => {
                                                    snapcastService.getStreamStatus(s.id).then(freshStream => {
                                                        const artUrl = freshStream?.properties?.metadata?.artUrl;
                                                        if (artUrl && artUrl.trim() !== '') {
                                                            console.log(`[Resume] Found artwork after resume - applying`);
                                                            setStreams(prev => prev.map(st =>
                                                                st.id === s.id
                                                                    ? {...st, currentTrack: {...st.currentTrack, albumArtUrl: artUrl}}
                                                                    : st
                                                            ));
                                                        }
                                                    });
                                                }, 500); // Small delay to let backend process resume
                                            }
                                        }
                                    }
                                }

                                // Update metadata if we got new data
                                if (updatedMetadata) {
                                    // Detect if this is a new track (title changed)
                                    const isNewTrack = updatedMetadata.title && updatedMetadata.title !== s.currentTrack.title;

                                    console.log(`[Polling] Track analysis:`, {
                                        isNewTrack,
                                        oldTitle: s.currentTrack.title,
                                        newTitle: updatedMetadata.title,
                                        currentArtUrl: s.currentTrack.albumArtUrl?.substring(0, 50) + '...'
                                    });

                                    updatedStream.currentTrack = {
                                        ...s.currentTrack,
                                        title: updatedMetadata.title || s.currentTrack.title,
                                        artist: updatedMetadata.artist || s.currentTrack.artist,
                                        album: updatedMetadata.album || s.currentTrack.album,
                                        // Update duration when it changes (already in seconds from metadata extraction)
                                        duration: updatedMetadata.duration !== undefined ? updatedMetadata.duration : s.currentTrack.duration,
                                    };

                                    // Handle artwork updates:
                                    // - If artwork explicitly provided and valid → use it
                                    // - If new track but no artwork yet → clear to default
                                    // - Otherwise → keep current artwork (for partial metadata updates)
                                    const artUrlType = updatedMetadata.albumArtUrl === undefined ? 'undefined' : updatedMetadata.albumArtUrl === null ? 'null' : updatedMetadata.albumArtUrl === '' ? 'empty' : 'valid';
                                    const artUrlPreview = updatedMetadata.albumArtUrl ? `${updatedMetadata.albumArtUrl.substring(0, 50)}...` : String(updatedMetadata.albumArtUrl);
                                    console.log(`[Polling] artUrl from server: type=${artUrlType}, preview=${artUrlPreview}`);

                                    if (updatedMetadata.albumArtUrl && updatedMetadata.albumArtUrl.trim() !== '') {
                                        console.log(`[Polling] ✓ Using provided artwork (${updatedMetadata.albumArtUrl.length} chars)`);
                                        updatedStream.currentTrack.albumArtUrl = updatedMetadata.albumArtUrl;
                                    } else if (isNewTrack) {
                                        console.log(`[Polling] ⚠ New track without artwork - using placeholder`);
                                        updatedStream.currentTrack.albumArtUrl = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDAwIiBoZWlnaHQ9IjQwMCIgdmlld0JveD0iMCAwIDQwMCA0MDAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxyZWN0IHdpZHRoPSI0MDAiIGhlaWdodD0iNDAwIiBmaWxsPSIjMkEyQTM2Ii8+CjxnIHRyYW5zZm9ybT0idHJhbnNsYXRlKDEwMCwgMTAwKSBzY2FsZSgxMi41KSI+CjxwYXRoIGZpbGw9IiNGMEYwRjAiIGQ9Ik00IDN2OS40Yy0wLjQtMC4yLTAuOS0wLjQtMS41LTAuNC0xLjQgMC0yLjUgMC45LTIuNSAyczEuMSAyIDIuNSAyIDIuNS0wLjkgMi41LTJ2LTcuM2w3LTIuM3Y1LjFjLTAuNC0wLjMtMC45LTAuNS0xLjUtMC41LTEuNCAwLTIuNSAwLjktMi41IDJzMS4xIDIgMi41IDIgMi41LTAuOSAyLjUtMnYtMTFsLTkgM3oiPjwvcGF0aD4KPC9nPgo8L3N2Zz4K';
                                    } else {
                                        console.log(`[Polling] Keeping existing artwork`);
                                        updatedStream.currentTrack.albumArtUrl = s.currentTrack.albumArtUrl;
                                    }

                                    // Reset progress to 0 when new track starts
                                    if (isNewTrack) {
                                        updatedStream.progress = 0;
                                    }
                                }

                                return updatedStream;
                            }
                            return s;
                        })
                    );
                }
            } catch (error) {
                // Silently handle errors to avoid spam
            }
        };

        // Poll every 2 seconds for active streams (more aggressive than before)
        const interval = setInterval(syncStreamState, 2000);

        return () => clearInterval(interval);
    }, [currentStream?.id]);

    useEffect(() => {
        let isCancelled = false;

        const fetchData = async () => {
            if (!isLoading) return; // Prevent multiple calls

            setConnectionError(null);

            try {
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

                    console.log('[Init] Built client group mapping:', groupMap);
                    setClientGroupMap(groupMap);
                } catch (error) {
                    console.error('[Init] Could not build client group mapping:', error);
                }

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
        // Handle browser audio client volume changes locally
        if (clientId === browserAudio.state.clientId) {
            browserAudio.setVolume(volume);
            return;
        }

        // Update local state immediately for responsiveness
        setClients(prevClients =>
            prevClients.map(c => (c.id === clientId ? {...c, volume} : c))
        );

        // Send to Snapcast server
        try {
            await snapcastService.setClientVolume(clientId, volume);
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
        console.log('[StreamChange] Request:', {clientId, streamId, clientGroupMap, allClients: clients.map(c => c.id)});

        // Handle browser audio client - stop it when stream set to null
        if (clientId === browserAudio.state.clientId && streamId === null) {
            browserAudio.stop();
            return;
        }

        // Update local state immediately for responsiveness
        setClients(prevClients =>
            prevClients.map(c => (c.id === clientId ? {...c, currentStreamId: streamId} : c))
        );

        // Send to Snapcast server
        try {
            const groupId = clientGroupMap[clientId];
            console.log('[StreamChange] Looked up groupId:', groupId, 'for client:', clientId);

            if (groupId && streamId) {
                console.log('[StreamChange] Calling setGroupStream:', {groupId, streamId});
                await snapcastService.setGroupStream(groupId, streamId);
                console.log('[StreamChange] SUCCESS: Stream changed');
            } else if (groupId && streamId === null) {
                // For setting to "no stream", we might need a different approach
                // This depends on how Snapcast handles idle streams
                // You might need to set it to a default idle stream instead
                console.log('[StreamChange] Skipping: streamId is null');
            } else {
                console.error(`[StreamChange] ERROR: Could not find group for client ${clientId}. ClientGroupMap:`, clientGroupMap);
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

        try {
            // Check stream capabilities first
            const capabilities = await snapcastService.getStreamCapabilities(currentStream.id);

            const newPlayingState = !currentStream.isPlaying;

            if (currentStream.isPlaying) {
                // Try to pause
                if (capabilities.canPause) {
                    // Optimistically update state immediately
                    setStreams(prevStreams =>
                        prevStreams.map(s =>
                            s.id === currentStream.id ? {...s, isPlaying: false} : s
                        )
                    );
                    // Record this change to prevent polling from overwriting for 8 seconds
                    setRecentPlaybackChange({streamId: currentStream.id, timestamp: Date.now()});

                    await snapcastService.pauseStream(currentStream.id);
                } else {
                    console.warn(`Stream ${currentStream.id} does not support pause`);
                }
            } else {
                // Try to play
                if (capabilities.canPlay) {
                    // Optimistically update state immediately
                    setStreams(prevStreams =>
                        prevStreams.map(s =>
                            s.id === currentStream.id ? {...s, isPlaying: true} : s
                        )
                    );
                    // Record this change to prevent polling from overwriting for 8 seconds
                    setRecentPlaybackChange({streamId: currentStream.id, timestamp: Date.now()});

                    await snapcastService.playStream(currentStream.id);
                } else {
                    console.warn(`Stream ${currentStream.id} does not support play`);
                }
            }
        } catch (error) {
            console.error(`Playback control failed for stream ${currentStream.id}:`, error);
            // On error, clear the grace period so polling can correct the state
            setRecentPlaybackChange(null);
        }
    };

    const handleSkip = async (direction: 'next' | 'prev') => {
        if (!currentStream) return;

        // Optimistically clear artwork IMMEDIATELY when user clicks skip
        // This must happen before any async operations to prevent race condition where
        // metadata arrives before the clear is applied
        const defaultArtwork = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDAwIiBoZWlnaHQ9IjQwMCIgdmlld0JveD0iMCAwIDQwMCA0MDAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxyZWN0IHdpZHRoPSI0MDAiIGhlaWdodD0iNDAwIiBmaWxsPSIjMkEyQTM2Ii8+CjxnIHRyYW5zZm9ybT0idHJhbnNsYXRlKDEwMCwgMTAwKSBzY2FsZSgxMi41KSI+CjxwYXRoIGZpbGw9IiNGMEYwRjAiIGQ9Ik00IDN2OS40Yy0wLjQtMC4yLTAuOS0wLjQtMS41LTAuNC0xLjQgMC0yLjUgMC45LTIuNSAyczEuMSAyIDIuNSAyIDIuNS0wLjkgMi41LTJ2LTcuM2w3LTIuM3Y1LjFjLTAuNC0wLjMtMC45LTAuNS0xLjUtMC41LTEuNCAwLTIuNSAwLjktMi41IDJzMS4xIDIgMi41IDIgMi41LTAuOSAyLjUtMnYtMTFsLTkgM3oiPjwvcGF0aD4KPC9nPgo8L3N2Zz4K';

        setStreams(prevStreams =>
            prevStreams.map(s =>
                s.id === currentStream.id
                    ? {
                        ...s,
                        currentTrack: {
                            ...s.currentTrack,
                            albumArtUrl: defaultArtwork
                        }
                    }
                    : s
            )
        );

        try {
            // Check stream capabilities
            const capabilities = await snapcastService.getStreamCapabilities(currentStream.id);

            if (direction === 'next') {
                if (capabilities.canGoNext) {
                    await snapcastService.nextTrack(currentStream.id);
                } else {
                    console.warn(`Stream ${currentStream.id} does not support next track`);
                }
            } else {
                if (capabilities.canGoPrevious) {
                    await snapcastService.previousTrack(currentStream.id);
                } else {
                    console.warn(`Stream ${currentStream.id} does not support previous track`);
                }
            }
        } catch (error) {
            console.error(`Skip ${direction} failed for stream ${currentStream.id}:`, error);
        }
    };

    const handleSeek = async (positionInSeconds: number) => {
        if (!currentStream) return;

        try {
            // Check stream capabilities
            const capabilities = await snapcastService.getStreamCapabilities(currentStream.id);

            if (capabilities.canSeek) {
                // Convert position to milliseconds for backend
                const positionInMs = positionInSeconds * 1000;

                // Optimistically update progress locally
                updateStreamProgress(currentStream.id, positionInSeconds);

                // Send seek command to backend
                await snapcastService.seekTo(currentStream.id, positionInMs);

                console.log(`Seek to ${positionInSeconds}s (${positionInMs}ms) for stream ${currentStream.id}`);
            } else {
                console.warn(`Stream ${currentStream.id} does not support seek`);
            }
        } catch (error) {
            console.error(`Seek failed for stream ${currentStream.id}:`, error);
        }
    };

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
                                <NowPlaying
                                    stream={currentStream}
                                    canSeek={streamCapabilities.canSeek}
                                    onSeek={handleSeek}
                                />
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
                            onStartBrowserAudio={() => {
                                const targetStream = myClient?.currentStreamId || null;
                                setTargetStreamForBrowserAudio(targetStream);
                                browserAudio.start();
                            }}
                            browserAudioActive={browserAudio.state.isActive}
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