import React, {useCallback, useEffect, useRef, useState} from 'react';
import {Routes, Route, useNavigate} from 'react-router-dom';
import {NowPlaying} from './components/NowPlaying';
import {PlayerControls} from './components/PlayerControls';
import {StreamSelector} from './components/StreamSelector';
import {ClientManager} from './components/ClientManager';
import {SyncedDevices} from './components/SyncedDevices';
import {Settings as SettingsModal} from './components/Settings';
import {Visualizer} from './components/Visualizer';
import {getSnapcastData} from './services/snapcastDataService';
import {snapcastService} from './services/snapcastService';
import {federationService} from './services/federationService';
import {settingsService} from './services/settingsService';
import type {Client, Server, Settings, Stream, VisualizerPreset} from './types';
import {DEFAULT_VISUALIZER_SETTINGS, BUILT_IN_PRESETS} from './types';
import {useAudioSync} from './hooks/useAudioSync';
import {useBrowserAudioClient} from './hooks/useBrowserAudioClient';
import { Icon } from './components/Icon';
import {updateFavicon} from './utils/favicon';
import {getTextColorForBackground, lightenColor, darkenColor} from './utils/colorContrast';
import {extractDualColorsFromAlbumArt, type DualColorExtractionResult} from './utils/albumArtColorExtraction';
import musicNotePlaceholderRaw from './src/assets/icons/music-note-placeholder.svg?raw';

// Convert raw SVG to data URI for use in img src
const musicNotePlaceholder = `data:image/svg+xml,${encodeURIComponent(musicNotePlaceholderRaw)}`;

const VOLUME_STEP = 5;

const App: React.FC = () => {
    const [streams, setStreams] = useState<Stream[]>([]);
    const [clients, setClients] = useState<Client[]>([]);
    const [servers, setServers] = useState<Server[]>([]);
    const [serverName, setServerName] = useState<string>('Snapcast Server');
    const [streamCapabilities, setStreamCapabilities] = useState<{canSeek?: boolean}>({});
    const [isLoading, setIsLoading] = useState(true);
    const [connectionError, setConnectionError] = useState<string | null>(null);
    const [preMuteGroupVolumes, setPreMuteGroupVolumes] = useState<Record<string, Record<string, number>>>({});
    const [isSettingsOpen, setIsSettingsOpen] = useState(false);
    const [settingsInitialTab, setSettingsInitialTab] = useState<string | undefined>(undefined);
    const [isVisualizerOpen, setIsVisualizerOpen] = useState(false);

    // Album art dual-color extraction state (background + accent)
    const [extractedAlbumArtColors, setExtractedAlbumArtColors] = useState<DualColorExtractionResult | null>(null);
    const [isExtractingColor, setIsExtractingColor] = useState(false);

    // Track recent user-initiated changes to prevent polling from overwriting them
    const [recentPlaybackChange, setRecentPlaybackChange] = useState<{streamId: string, timestamp: number} | null>(null);
    const [recentUserChanges, setRecentUserChanges] = useState<{type: string, timestamp: number, data: any} | null>(null);
    // Use ref to avoid stale closure in polling callback
    const recentUserChangesRef = useRef<{type: string, timestamp: number, data: any} | null>(null);
    // Use ref to access current streams without circular dependency
    const streamsRef = useRef<Stream[]>(streams);
    // Use ref to prevent concurrent fetchData calls
    const isFetchingRef = useRef(false);

    // Settings loaded from settingsService (server + local storage)
    const [settings, setSettings] = useState<Settings>(settingsService.getMergedSettings());

    // Store group mappings for clients
    const [clientGroupMap, setClientGroupMap] = useState<Record<string, string>>({});

    // Update streamsRef when streams changes
    useEffect(() => {
        streamsRef.current = streams;
    }, [streams]);

    // Browser audio client for "Listen in Browser" functionality
    const browserAudio = useBrowserAudioClient(window.location.hostname);

    // Track if we've already auto-assigned the browser client to prevent loops
    const [browserClientAutoAssigned, setBrowserClientAutoAssigned] = useState(false);
    // Capture the target stream when "Listen in Browser" is clicked
    const [targetStreamForBrowserAudio, setTargetStreamForBrowserAudio] = useState<string | null>(null);

    // Visualizer preset cycling state
    const [previousTrackId, setPreviousTrackId] = useState<string | null>(null);
    const [currentCycleIndex, setCurrentCycleIndex] = useState(0);

    // Initialize settings from service (fetch from server + local storage)
    useEffect(() => {
        settingsService.init().then((initialSettings) => {
            setSettings(initialSettings);
        }).catch((error) => {
            console.error('[Settings] Failed to initialize:', error);
        });

        // Subscribe to settings changes
        const unsubscribe = settingsService.subscribe((updatedSettings) => {
            setSettings(updatedSettings);
        });

        return () => unsubscribe();
    }, []);

    // Update browser title when device name changes
    useEffect(() => {
        if (settings.deviceName) {
            document.title = settings.deviceName;
        }
    }, [settings.deviceName]);

    // Update favicon when theme changes
    useEffect(() => {
        updateFavicon(settings.theme.accent, settings.theme.customColor, settings.theme.mode);
    }, [settings.theme.accent, settings.theme.customColor, settings.theme.mode]);

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

        // Determine the effective theme mode (resolve 'system' to actual mode)
        const effectiveMode = settings.theme.mode === 'system'
            ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
            : settings.theme.mode;

        // Check if we're in a monochrome mode
        const isMonochromeMode = effectiveMode === 'black' || effectiveMode === 'white';

        // Only set colors if NOT in monochrome mode
        // Monochrome modes define their own colors in CSS
        if (isMonochromeMode) {
            // Clear any previously set inline styles so CSS takes over
            root.style.removeProperty('--accent-text-color');
            root.style.removeProperty('--bg-primary');
            root.style.removeProperty('--bg-secondary');
            root.style.removeProperty('--bg-tertiary');
            root.style.removeProperty('--bg-secondary-hover');
            root.style.removeProperty('--bg-tertiary-hover');
            root.style.removeProperty('--border-color');
            root.style.removeProperty('--text-primary');
            root.style.removeProperty('--text-secondary');
            root.style.removeProperty('--text-muted');
            root.style.removeProperty('--icon-muted');
            root.style.removeProperty('--accent-color');
            root.style.removeProperty('--accent-color-hover');
            root.style.removeProperty('--custom-accent-color');
            root.style.removeProperty('--custom-accent-color-hover');
            root.style.removeProperty('--control-icon-color');
        } else {
            // Priority: Extracted album art colors (if enabled) > User-selected colors
            if (settings.theme.useAlbumArtColors && extractedAlbumArtColors) {
                // Apply extracted dual colors (background + accent)
                const bgColor = extractedAlbumArtColors.backgroundColor;
                const accentColor = extractedAlbumArtColors.accentColor;
                const isDark = extractedAlbumArtColors.isDarkTheme;

                // Apply background colors
                // --bg-primary: Main background
                root.style.setProperty('--bg-primary', bgColor);

                // Calculate secondary background (slightly lighter for dark, slightly lighter for light)
                const bgSecondary = isDark ? lightenColor(bgColor, 5) : lightenColor(bgColor, 3);
                root.style.setProperty('--bg-secondary', bgSecondary);

                // Calculate tertiary background (slightly lighter than secondary)
                const bgTertiary = isDark ? lightenColor(bgColor, 8) : lightenColor(bgColor, 5);
                root.style.setProperty('--bg-tertiary', bgTertiary);

                // Calculate hover states (slightly lighter than their base)
                const bgSecondaryHover = isDark ? lightenColor(bgSecondary, 5) : lightenColor(bgSecondary, 3);
                root.style.setProperty('--bg-secondary-hover', bgSecondaryHover);

                const bgTertiaryHover = isDark ? lightenColor(bgTertiary, 5) : lightenColor(bgTertiary, 3);
                root.style.setProperty('--bg-tertiary-hover', bgTertiaryHover);

                // Calculate border color (lighter than background)
                const borderColor = isDark ? lightenColor(bgColor, 15) : darkenColor(bgColor, 10);
                root.style.setProperty('--border-color', borderColor);

                // Calculate text colors based on theme
                if (isDark) {
                    // Dark theme: light text on dark background
                    root.style.setProperty('--text-primary', '#f0f0f0');
                    root.style.setProperty('--text-secondary', '#b0b0c0');
                    root.style.setProperty('--text-muted', '#808090');
                    root.style.setProperty('--icon-muted', '#707080');
                } else {
                    // Light theme: dark text on light background
                    root.style.setProperty('--text-primary', '#181c32');
                    root.style.setProperty('--text-secondary', '#5e6278');
                    root.style.setProperty('--text-muted', '#7e8299');
                    root.style.setProperty('--icon-muted', '#a1a5b7');
                }

                // Apply accent colors
                const accentHover = lightenColor(accentColor, 15);
                root.style.setProperty('--accent-color', accentColor);
                root.style.setProperty('--accent-color-hover', accentHover);
                root.style.setProperty('--custom-accent-color', accentColor);
                root.style.setProperty('--custom-accent-color-hover', accentHover);

                // Calculate optimal text color for accent
                const textColor = getTextColorForBackground(accentColor);
                root.style.setProperty('--accent-text-color', textColor);

                // Set control icon color to accent (for media control buttons)
                root.style.setProperty('--control-icon-color', accentColor);
            } else {
                // Clear background and text overrides when not using album art colors
                root.style.removeProperty('--bg-primary');
                root.style.removeProperty('--bg-secondary');
                root.style.removeProperty('--bg-tertiary');
                root.style.removeProperty('--bg-secondary-hover');
                root.style.removeProperty('--bg-tertiary-hover');
                root.style.removeProperty('--border-color');
                root.style.removeProperty('--text-primary');
                root.style.removeProperty('--text-secondary');
                root.style.removeProperty('--text-muted');
                root.style.removeProperty('--icon-muted');
                root.style.removeProperty('--control-icon-color');

                // Determine the effective accent color
                // Priority: Custom color > Built-in color
                let effectiveAccentColor: string;

                if (settings.theme.accent === 'custom' && settings.theme.customColor) {
                    effectiveAccentColor = settings.theme.customColor;
                } else {
                    // Use built-in accent color
                    const accentColors: Record<string, string> = {
                        purple: '#aa5cc3',
                        blue: '#3b82f6',
                        green: '#22c55e',
                        orange: '#f97316',
                        red: '#ef4444',
                        yellow: '#eab308',
                    };
                    effectiveAccentColor = accentColors[settings.theme.accent] || accentColors.purple;
                }

                // Apply the effective accent color
                const accentHover = lightenColor(effectiveAccentColor, 15);
                const textColor = getTextColorForBackground(effectiveAccentColor);

                // Set both --accent-color and --custom-accent-color to ensure it applies
                // regardless of the data-accent attribute
                root.style.setProperty('--accent-color', effectiveAccentColor);
                root.style.setProperty('--accent-color-hover', accentHover);
                root.style.setProperty('--custom-accent-color', effectiveAccentColor);
                root.style.setProperty('--custom-accent-color-hover', accentHover);
                root.style.setProperty('--accent-text-color', textColor);
            }
        }

        return () => {
            mediaQuery.removeEventListener('change', handleSystemThemeChange);
        };
    }, [settings.theme, extractedAlbumArtColors]);

    // Helper to get the local server
    const getLocalServer = () => servers.find(s => s.isLocal);

    // Helper to check if a client/stream ID belongs to the local server
    const isLocalId = (id: string): boolean => {
        if (!settings.federation.enabled) return true;
        const localServer = getLocalServer();
        return !localServer || id.startsWith(`${localServer.id}-`);
    };

    // Helper to strip server prefix from federated IDs
    const stripServerPrefix = (id: string): string => {
        const localServer = getLocalServer();
        if (localServer && id.startsWith(`${localServer.id}-`)) {
            return id.replace(`${localServer.id}-`, '');
        }
        return id;
    };

    // Helper to get the effective browser audio client ID
    // In federation mode, local clients get "server-{ip}-" prefix from federation API
    const getBrowserAudioClientId = (): string => {
        if (!browserAudio.state.clientId) return '';

        if (settings.federation.enabled) {
            // Find the local server ID (isLocal=true)
            const localServer = getLocalServer();
            if (localServer) {
                return `${localServer.id}-${browserAudio.state.clientId}`;
            }
            // Fallback to localhost prefix if local server not found yet
            return `server-localhost-${browserAudio.state.clientId}`;
        }

        return browserAudio.state.clientId;
    };

    // Find the primary client to control
    // Prefer MAC address format (integrated snapclient on Raspberry Pi), otherwise use first client
    // Exclude browser audio client from being selected as primary
    const browserClientId = getBrowserAudioClientId();
    const myClient = clients.find(c =>
        c.id !== browserClientId &&
        /^[0-9a-f]{2}(:[0-9a-f]{2}){5}$/i.test(c.id)
    ) || clients.find(c => c.id !== browserClientId);
    const currentStream = streams.find(s => s.id === myClient?.currentStreamId);
    // Treat none-* streams the same as no stream selected (hide controls)
    const isNoneStream = currentStream?.id?.startsWith('none-') ?? false;
    const shouldShowControls = currentStream && !isNoneStream;

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
        const browserClient = clients.find(c => c.id === browserClientId);
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
            handleStreamChange(browserClientId, targetStream);
        }

        if (targetStream) {
            setBrowserClientAutoAssigned(true);
        }
    }, [browserAudio.state.isActive, browserAudio.state.clientId, clients, myClient, browserClientAutoAssigned, targetStreamForBrowserAudio, streams, servers, settings.federation.enabled]);

    // Stop browser audio client if its assigned stream is removed or set to none-snapserver
    useEffect(() => {
        if (!browserAudio.state.isActive) {
            return; // Browser audio not active, nothing to do
        }

        // Find the browser audio client in the client list
        const browserClient = clients.find(c => c.id === browserClientId);
        if (!browserClient) {
            return; // Browser client not registered yet, wait for it to appear
        }

        // Stop if no stream is assigned
        if (!browserClient.currentStreamId) {
            browserAudio.stop();
            return;
        }

        // Stop if assigned to the none-snapserver stream (fallback when source stream is removed)
        if (browserClient.currentStreamId === 'none-snapserver') {
            browserAudio.stop();
            return;
        }

        // Check if the assigned stream still exists
        const assignedStream = streams.find(s => s.id === browserClient.currentStreamId);
        if (!assignedStream) {
            // Stream was removed - stop the browser audio client
            browserAudio.stop();
        }
    }, [browserAudio.state.isActive, streams, clients, browserClientId]);

    // Visualizer preset cycling on track change
    useEffect(() => {
        // Get visualizer settings
        const viz = typeof settings.integrations.visualizer === 'object'
            ? settings.integrations.visualizer
            : DEFAULT_VISUALIZER_SETTINGS;

        // Skip if cycling is disabled or no presets selected
        if (!viz.cycleEnabled || !viz.cyclePresetIds || viz.cyclePresetIds.length === 0) {
            return;
        }

        // Get current track ID
        const currentTrackId = currentStream?.currentTrack?.id;

        // Skip if no track or track hasn't changed
        if (!currentTrackId || currentTrackId === previousTrackId) {
            return;
        }

        // Track has changed - cycle to next preset
        console.log('[Visualizer] Track changed, cycling to next preset');
        setPreviousTrackId(currentTrackId);

        // Get all presets (built-in + user)
        const userPresets = settings.integrations.visualizerPresets || [];
        const allPresets = [...BUILT_IN_PRESETS, ...userPresets];

        // Filter to only selected presets
        const cyclePresets = allPresets.filter(p => viz.cyclePresetIds.includes(p.id));

        if (cyclePresets.length === 0) {
            return;
        }

        // Get next preset
        const nextIndex = (currentCycleIndex + 1) % cyclePresets.length;
        const nextPreset = cyclePresets[nextIndex];
        setCurrentCycleIndex(nextIndex);

        console.log(`[Visualizer] Applying preset: ${nextPreset.name} (${nextIndex + 1}/${cyclePresets.length})`);

        // Apply preset settings
        const newVisualizerSettings = {
            enabled: viz.enabled,
            cycleEnabled: viz.cycleEnabled,
            cyclePresetIds: viz.cyclePresetIds,
            ...nextPreset.settings
        };

        settingsService.updateServerSettings({
            integrations: {
                ...settings.integrations,
                visualizer: newVisualizerSettings
            }
        });
    }, [currentStream, settings, previousTrackId, currentCycleIndex]);

    // Extract dual colors (background + accent) from album art when artwork changes (if enabled)
    useEffect(() => {
        // Reset colors when feature disabled or no stream/artwork
        if (!settings.theme.useAlbumArtColors || !currentStream?.currentTrack.albumArtUrl) {
            setExtractedAlbumArtColors(null);
            return;
        }

        const artworkUrl = currentStream.currentTrack.albumArtUrl;

        // Skip extraction for placeholder artwork
        if (artworkUrl === musicNotePlaceholder || artworkUrl.startsWith('data:image/svg+xml')) {
            setExtractedAlbumArtColors(null);
            return;
        }

        // Debounce: Don't extract if already extracting
        if (isExtractingColor) return;

        // Determine if current theme is dark
        const effectiveMode = settings.theme.mode === 'system'
            ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
            : settings.theme.mode;
        const isDarkTheme = effectiveMode === 'dark' || effectiveMode === 'black';

        // Get fallback accent color
        const accentColors: Record<string, string> = {
            purple: '#aa5cc3',
            blue: '#3b82f6',
            green: '#22c55e',
            orange: '#f97316',
            red: '#ef4444',
            yellow: '#eab308',
        };
        const fallbackAccent = settings.theme.accent === 'custom' && settings.theme.customColor
            ? settings.theme.customColor
            : accentColors[settings.theme.accent] || accentColors.purple;

        setIsExtractingColor(true);

        extractDualColorsFromAlbumArt(artworkUrl, isDarkTheme, fallbackAccent)
            .then((result) => {
                if (result) {
                    setExtractedAlbumArtColors(result);
                } else {
                    console.warn('[AlbumArtColor] Extraction returned null, using fallback');
                    setExtractedAlbumArtColors(null);
                }
                setIsExtractingColor(false);
            })
            .catch((error) => {
                console.warn('[AlbumArtColor] Extraction failed:', error);
                setExtractedAlbumArtColors(null);
                setIsExtractingColor(false);
            });
    }, [
        currentStream?.currentTrack.albumArtUrl,
        currentStream?.id,
        settings.theme.useAlbumArtColors,
        settings.theme.mode,
        settings.theme.accent,
        settings.theme.customColor,
        isExtractingColor
    ]);

    // Update browser client name, volume, and connection status if server has reported it
    // Volume is managed locally (not synced to server), so override with local state
    const allClients = clients.map(c => {
        // If this is our browser audio client, ensure proper naming, local volume, and connection status
        if (browserAudio.state.isActive && c.id === browserClientId) {
            // Determine client name based on endpoint name or device name
            const endpointName = settings.deviceName || 'Device';
            const visualizerClientName = `${endpointName}-Visualizer`;

            return {
                ...c,
                // Use visualizer-specific naming
                name: visualizerClientName,
                // Override volume with local state (browser audio volume is local only)
                volume: browserAudio.state.volume,
                // Override connection status - if browser audio is active, it's connected
                connected: true
            };
        }
        return c;
    });

    // Add placeholder if browser audio is active but server hasn't reported it yet
    if (browserAudio.state.isActive) {
        const serverHasClient = clients.some(c => c.id === browserClientId);

        if (!serverHasClient) {
            // Server hasn't seen the client yet - add temporary placeholder
            const endpointName = settings.deviceName || 'Device';
            const visualizerClientName = `${endpointName}-Visualizer`;

            const browserClient: Client = {
                id: browserClientId,
                name: `${visualizerClientName} (Connecting...)`,
                currentStreamId: null,
                volume: browserAudio.state.volume,
                connected: false
            };
            allClients.push(browserClient);
        }
    }

    // Helper function to detect if a client should be hidden
    // Hide clients ending with "-Visualizer" only when browser audio is muted (visualizer mode)
    // Show them when unmuted (listening mode)
    const shouldHideClient = (client: Client): boolean => {
        // Check if this is our browser audio visualizer client
        if (client.name.endsWith('-Visualizer')) {
            // If browser audio is active, check if it's muted
            if (browserAudio.state.isActive && client.id === browserClientId) {
                // Hide if muted (visualizer-only mode), show if unmuted (listening mode)
                return browserAudio.state.muted;
            }
            // Hide other visualizer clients
            return true;
        }

        // Also hide other snapweb/browser clients (auto-created by server)
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
            c.connected || (c.id === browserClientId && browserAudio.state.isActive)
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

    // Sync ref with state changes
    useEffect(() => {
        recentUserChangesRef.current = recentUserChanges;
    }, [recentUserChanges]);

    // Clean up recent user changes after grace period expires
    useEffect(() => {
        if (!recentUserChanges) return;

        const gracePeriod = 7000; // 7 seconds for user changes (longer than 5s polling interval)
        const timeRemaining = gracePeriod - (Date.now() - recentUserChanges.timestamp);

        if (timeRemaining > 0) {
            const timeout = setTimeout(() => {
                setRecentUserChanges(null);
            }, timeRemaining);

            return () => clearTimeout(timeout);
        } else {
            setRecentUserChanges(null);
        }
    }, [recentUserChanges]);

    // Listen for real-time metadata updates from Snapcast
    useEffect(() => {
        if (!snapcastService) return;

        const unsubscribe = snapcastService.onMetadataUpdate((streamId, metadata) => {
            // Debug: Log all metadata updates
            console.log(`[Metadata] Update received:`, {
                streamId,
                federationEnabled: settings.federation.enabled,
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
                    // Map local WebSocket stream ID to federated stream ID
                    const federatedStreamId = getFederatedStreamId(streamId);
                    const isMatch = stream.id === federatedStreamId;

                    if (isMatch) {
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
                            // Transform artUrl: relative paths need Snapcast HTTP URL prefix
                            let resolvedArtUrl = metadata.artUrl;
                            if (metadata.artUrl.startsWith('/')) {
                                resolvedArtUrl = `${snapcastService.getHttpUrl()}${metadata.artUrl}`;
                            }
                            console.log(`[Metadata] ✓ Using provided artwork (${resolvedArtUrl.length} chars)`);
                            updatedTrack.albumArtUrl = resolvedArtUrl;
                        } else if (isNewTrack) {
                            console.log(`[Metadata] ⚠ New track without artwork - using placeholder`);
                            updatedTrack.albumArtUrl = musicNotePlaceholder;
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
    }, [recentPlaybackChange, settings.federation.enabled, servers]);

    // Listen for real-time playback state updates from Snapcast
    useEffect(() => {
        if (!snapcastService) return;

        const unsubscribe = snapcastService.onPlaybackStateUpdate(async (streamId, playbackStatus, properties) => {
            // Handle refresh signal - fetch latest state for all streams
            if (playbackStatus === 'REFRESH') {
                console.log('[PlaybackState] REFRESH signal - refetching full server status');
                // Fetch latest state for all streams
                const serverStatus = await snapcastService.getServerStatus();
                if (serverStatus && serverStatus.server && serverStatus.server.streams) {
                    // Get all current stream IDs (without federation prefix)
                    const currentStreamIds = new Set(streamsRef.current.map(s => getLocalStreamId(s.id)));
                    const newStreamIds = new Set(serverStatus.server.streams.map((s: any) => s.id));

                    // Check if streams have been added or removed
                    const streamsAdded = [...newStreamIds].some(id => !currentStreamIds.has(id));
                    const streamsRemoved = [...currentStreamIds].some(id => !newStreamIds.has(id));

                    if (streamsAdded || streamsRemoved) {
                        console.log('[PlaybackState] Stream list changed - refetching all data');
                        // If streams were added/removed, refetch everything (only if not already fetching)
                        if (!isFetchingRef.current) {
                            await fetchData();
                        } else {
                            console.log('[PlaybackState] Stream list changed but already fetching, skipping');
                        }
                    } else {
                        // Just update playback state for existing streams
                        setStreams(prevStreams =>
                            prevStreams.map(stream => {
                                // Strip federation prefix for server stream lookup
                                const localStreamId = getLocalStreamId(stream.id);

                                const serverStream = serverStatus.server.streams.find((s: any) => s.id === localStreamId);
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
                }
                return;
            }

            // Handle direct playback status update
            const isPlaying = playbackStatus.toLowerCase() === 'playing';

            // Check if this is a new stream that doesn't exist yet
            const federatedStreamId = getFederatedStreamId(streamId);
            const streamExists = streamsRef.current.some(stream => stream.id === federatedStreamId);

            if (!streamExists) {
                // This is a NEW stream - fetch all data to include it (only if not already fetching)
                if (!isFetchingRef.current) {
                    console.log(`[PlaybackState] New stream detected: ${streamId} - refetching all data`);
                    await fetchData();
                } else {
                    console.log(`[PlaybackState] New stream detected: ${streamId} - but already fetching, skipping`);
                }
                return;
            }

            // Update the stream's playing state
            setStreams(prevStreams =>
                prevStreams.map(stream => {
                    const isMatch = stream.id === federatedStreamId;

                    if (isMatch) {
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [settings.federation.enabled, servers]);

    // Listen for real-time position updates from Snapcast (for sources that support it)
    useEffect(() => {
        if (!snapcastService) return;

        const unsubscribe = snapcastService.onPositionUpdate((streamId, position, duration) => {
            // Position and duration come in milliseconds from backend, convert to seconds
            const progressInSeconds = Math.floor(position / 1000);
            console.log(`[App] Position update received: stream=${streamId}, progress=${progressInSeconds}s, federationEnabled=${settings.federation.enabled}`);

            // Map local WebSocket stream ID to federated stream ID
            const federatedStreamId = getFederatedStreamId(streamId);

            // Update stream progress
            updateStreamProgress(federatedStreamId, progressInSeconds);
        });

        return () => unsubscribe();
    }, [updateStreamProgress, settings.federation.enabled, servers]);

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
        const hasPlaceholder = currentStream.currentTrack.albumArtUrl === musicNotePlaceholder;

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
    // NOTE: Disabled in federation mode - federation polling handles this
    useEffect(() => {
        if (!currentStream || !snapcastService) return;
        if (settings.federation.enabled) return; // Federation polling handles this

        const syncStreamState = async () => {
            try {
                const serverStream = await snapcastService.getStreamStatus(currentStream.id);
                if (serverStream) {
                    const isPlaying = snapcastService.isStreamPlaying(serverStream);

                    // Extract position from stream properties (convert ms to seconds)
                    const positionSeconds = serverStream.properties?.position
                        ? Math.floor(serverStream.properties.position / 1000)
                        : 0;

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
                                            const isDefaultArtwork = s.currentTrack.albumArtUrl === musicNotePlaceholder;
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
                                        updatedStream.currentTrack.albumArtUrl = musicNotePlaceholder;
                                    } else {
                                        console.log(`[Polling] Keeping existing artwork`);
                                        updatedStream.currentTrack.albumArtUrl = s.currentTrack.albumArtUrl;
                                    }

                                    // Reset progress to 0 when new track starts
                                    if (isNewTrack) {
                                        updatedStream.progress = 0;
                                    }
                                }

                                // Only sync position from polling on initial load (when current progress is 0)
                                // After that, let useAudioSync handle client-side interpolation
                                // WebSocket notifications will handle seeks/track changes
                                if (isPlaying && positionSeconds > 0 && s.progress === 0) {
                                    console.log(`[Polling] Initial position sync: ${positionSeconds}s`);
                                    updatedStream.progress = positionSeconds;
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
    }, [currentStream?.id, settings.federation.enabled]);

    // Shared function to fetch/refetch all data from Snapcast
    const fetchData = useCallback(async () => {
        // Prevent concurrent fetches - use ref to avoid race conditions
        if (isFetchingRef.current) {
            console.log('[FetchData] Already fetching, skipping duplicate call');
            return;
        }

        isFetchingRef.current = true;
        setConnectionError(null);

        try {
            const {initialStreams, initialClients, serverName: snapServerName} = await getSnapcastData();

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
            console.error('Error loading Snapcast data:', error);
            setConnectionError('Failed to load Snapcast data');

            // Set minimal fallback data
            setStreams([]);
            setClients([{
                id: 'client-1',
                name: 'My Device (You)',
                currentStreamId: null,
                volume: 75,
                connected: true,
            }]);
        } finally {
            // Always reset the flag, even if there was an error
            isFetchingRef.current = false;
        }
    }, []);

    // Initial data fetch on mount
    useEffect(() => {
        if (!isLoading) return; // Prevent multiple calls

        fetchData().finally(() => {
            setIsLoading(false);
        });
    }, []); // Empty dependency array - only run once

    // Poll for stream additions/removals (fallback for when Server.OnUpdate isn't sent)
    // This ensures dynamic streams appear/disappear even if WebSocket notifications fail
    useEffect(() => {
        if (!snapcastService) return;
        if (settings.federation.enabled) return; // Federation polling handles this

        const checkStreamList = async () => {
            try {
                const serverStatus = await snapcastService.getServerStatus();
                if (serverStatus && serverStatus.server && serverStatus.server.streams) {
                    const currentStreamIds = new Set(streamsRef.current.map(s => s.id));
                    const serverStreamIds = new Set(serverStatus.server.streams.map((s: any) => s.id));

                    // Check if streams were added or removed
                    const streamsAdded = [...serverStreamIds].some(id => !currentStreamIds.has(id));
                    const streamsRemoved = [...currentStreamIds].some(id => !serverStreamIds.has(id));

                    if (streamsAdded || streamsRemoved) {
                        console.log('[StreamPoll] Stream list changed - refetching all data');
                        if (!isFetchingRef.current) {
                            await fetchData();
                        }
                    }
                }
            } catch (error) {
                console.error('[StreamPoll] Error checking stream list:', error);
            }
        };

        // Poll every 10 seconds for stream list changes
        const interval = setInterval(checkStreamList, 10000);

        return () => clearInterval(interval);
    }, [settings.federation.enabled, fetchData]);

    // Federation polling - fetch data from federation API when enabled
    useEffect(() => {
        if (!settings.federation.enabled) {
            // Stop polling if federation was disabled
            federationService.stopPolling();
            setServers([]);
            return;
        }

        console.log('[Federation] Waiting for backend to be ready...');

        // Poll the backend until it's ready (with timeout)
        // The backend needs time to restart from minimal mode to full federation mode
        const startPollingDelayed = async () => {
            const maxAttempts = 20; // 20 attempts * 500ms = 10 seconds max
            let attempt = 0;
            let isReady = false;

            while (attempt < maxAttempts && !isReady) {
                attempt++;
                await new Promise(resolve => setTimeout(resolve, 500));

                // Check if federation service is healthy
                const healthy = await federationService.checkHealth();
                if (healthy) {
                    // Backend is healthy, now check if servers are connected
                    try {
                        const servers = await federationService.getServers();
                        const hasConnectedServers = servers.some(s => s.connected);

                        if (hasConnectedServers) {
                            isReady = true;
                            console.log(`[Federation] Backend ready with ${servers.length} server(s) after ${attempt * 0.5}s, starting polling...`);
                        } else if (attempt === maxAttempts) {
                            console.error('[Federation] Backend did not connect to local server in time');
                            return; // Exit without starting polling
                        }
                    } catch (error) {
                        // Servers endpoint not ready yet, continue polling
                        if (attempt === maxAttempts) {
                            console.error('[Federation] Backend servers endpoint not ready in time');
                            return;
                        }
                    }
                } else if (attempt === maxAttempts) {
                    console.error('[Federation] Backend did not become ready in time');
                    return; // Exit without starting polling
                }
            }

            // Transform federated stream data to match frontend Stream type
            const transformFederatedStream = (federatedStream: any): Stream => {
                const metadata = federatedStream.metadata || {};
                const properties = federatedStream.properties || {};

                // Extract stream name from federated ID by removing "{serverId}-" prefix
                // Example: "192-168-7-226-default" -> "default"
                const extractStreamName = (id: string, serverId: string): string => {
                    const prefix = `${serverId}-`;
                    if (id.startsWith(prefix)) {
                        return id.substring(prefix.length);
                    }
                    return 'Unknown';
                };

                const streamName = extractStreamName(federatedStream.id, federatedStream.serverId);

                return {
                    id: federatedStream.id,
                    serverId: federatedStream.serverId,
                    serverName: federatedStream.serverName,
                    name: streamName,
                    sourceDevice: streamName,
                    currentTrack: {
                        id: federatedStream.id,
                        title: metadata.title || 'Unknown Track',
                        artist: Array.isArray(metadata.artist) ? metadata.artist.join(', ') : (metadata.artist || 'Unknown Artist'),
                        album: metadata.album || 'Unknown Album',
                        albumArtUrl: metadata.artUrl ? (metadata.artUrl.startsWith('/') ? `http://${window.location.hostname}:1780${metadata.artUrl}` : metadata.artUrl) : musicNotePlaceholder,
                        duration: metadata.duration ? Math.floor(metadata.duration / 1000) : 0
                    },
                    isPlaying: properties.playbackStatus === 'playing',
                    progress: properties.position ? Math.floor(properties.position / 1000) : 0
                };
            };

            // Transform federated client data to ensure names are populated
            const transformFederatedClient = (federatedClient: any): Client => {
                // Extract client name from federated ID or use provided name
                // Federated client IDs may be in format "server-{serverId}-{clientId}"
                const extractClientName = (client: any): string => {
                    // If client has a name, use it
                    if (client.name && client.name !== '') {
                        return client.name;
                    }
                    // Otherwise try to extract from ID
                    // Format might be: "server-localhost-00:21:6a:7e:3f:ae" or similar
                    const parts = client.id.split('-');
                    if (parts.length >= 3) {
                        // Take everything after "server-{serverId}-"
                        return parts.slice(2).join('-');
                    }
                    return client.id; // Fallback to ID
                };

                return {
                    ...federatedClient,
                    name: extractClientName(federatedClient)
                };
            };

            // Helper to detect if a client ID is local (served by this server's WebSocket)
            // Local clients from federation API have "server-localhost-" prefix but should use WebSocket API
            const isLocalFederatedClient = (clientId: string): boolean => {
                return clientId.startsWith('server-localhost-');
            };

            // Helper to strip federation prefix from local client IDs
            const stripLocalPrefix = (clientId: string): string => {
                if (isLocalFederatedClient(clientId)) {
                    return clientId.replace('server-localhost-', '');
                }
                return clientId;
            };

            // Start polling for federated data
            federationService.startPolling((data) => {
                console.log('[Federation] Received update:', {
                    servers: data.servers.length,
                    streams: data.streams.length,
                    clients: data.clients.length
                });

                setServers(data.servers);

                // Check if we should ignore polling updates due to recent user changes
                // Use ref to avoid stale closure
                const now = Date.now();
                const GRACE_PERIOD = 7000; // 7 second grace period for user changes (longer than 5s polling interval)
                const recentChanges = recentUserChangesRef.current;
                const hasRecentChange = recentChanges && (now - recentChanges.timestamp) < GRACE_PERIOD;

                if (hasRecentChange) {
                    console.log(`[Federation] Grace period active: ${recentChanges.type} change for`, recentChanges.data, `(${Math.round((GRACE_PERIOD - (now - recentChanges.timestamp)) / 1000)}s remaining)`);
                }

                // Transform and MERGE federated streams (preserve client-side progress tracking)
                if (data.streams.length > 0) {
                    setStreams(prevStreams => {
                        const transformedStreams = data.streams.map(federatedStream => {
                            const newStream = transformFederatedStream(federatedStream);

                            // Find existing stream to preserve client-side progress
                            const existingStream = prevStreams.find(s => s.id === newStream.id);

                            if (existingStream && existingStream.isPlaying) {
                                // Stream is playing - preserve client-side progress for smooth updates
                                // Accept all other server data (metadata, isPlaying, etc.)
                                // Use whichever progress is higher (client increments between polls)
                                // However, if there was a recent playback change for THIS stream, preserve its state
                                if (hasRecentChange && recentChanges!.type === 'playback' && recentChanges!.data.streamId === newStream.id) {
                                    console.log(`[Federation] Preserving user-initiated playback state for ${newStream.id} during grace period`);
                                    return {
                                        ...newStream,
                                        isPlaying: existingStream.isPlaying,
                                        progress: Math.max(newStream.progress, existingStream.progress)
                                    };
                                }

                                return {
                                    ...newStream,
                                    progress: Math.max(newStream.progress, existingStream.progress)
                                };
                            }

                            // New stream or not playing - use server data as-is
                            return newStream;
                        });

                        return transformedStreams;
                    });
                }

                // Transform and set federated clients
                if (data.clients.length > 0) {
                    // If there was a recent client routing change, preserve that client's stream assignment
                    const transformedClients = data.clients.map(client => {
                        const transformed = transformFederatedClient(client);

                        if (hasRecentChange && recentChanges!.type === 'routing' && recentChanges!.data.clientId === transformed.id) {
                            console.log(`[Federation] Preserving user-initiated stream routing for ${transformed.id} during grace period`);
                            return {
                                ...transformed,
                                currentStreamId: recentChanges!.data.streamId
                            };
                        }

                        return transformed;
                    });
                    setClients(transformedClients);
                }
            }, 5000);
        };

        // Call the async function to start polling after delay
        startPollingDelayed();

        return () => {
            federationService.stopPolling();
        };
    }, [settings.federation.enabled]);

    const handleVolumeChange = async (clientId: string, volume: number) => {
        // Handle browser audio client volume changes locally
        // Compare with effective browser client ID (accounting for federation prefix)
        const effectiveBrowserClientId = getBrowserAudioClientId();
        if (clientId === effectiveBrowserClientId) {
            browserAudio.setVolume(volume);
            // Also update clients state to ensure controlled input stays in sync
            // (The allClients mapping will override with browserAudio.state.volume,
            // but this ensures React's controlled input batching works correctly)
            setClients(prevClients =>
                prevClients.map(c => (c.id === clientId ? {...c, volume} : c))
            );
            return;
        }

        // Update local state immediately for responsiveness
        setClients(prevClients =>
            prevClients.map(c => (c.id === clientId ? {...c, volume} : c))
        );

        // Determine if this is a local federated client or remote federated client
        const isLocalFederated = clientId.startsWith('server-localhost-');
        const isRemoteFederated = settings.federation.enabled && clientId.startsWith('server-') && !isLocalFederated;

        // If federation is enabled and client is REMOTE federated, use federation API
        if (isRemoteFederated) {
            try {
                await federationService.setVolume(clientId, volume);
            } catch (error) {
                console.error(`Failed to set volume for federated client ${clientId}:`, error);
            }
            return;
        }

        // Local client (either direct WebSocket or local federated) - use WebSocket API
        // Strip "server-localhost-" prefix if present
        const localClientId = isLocalFederated ? clientId.replace('server-localhost-', '') : clientId;

        try {
            await snapcastService.setClientVolume(localClientId, volume);
        } catch (error) {
            console.error(`Failed to set volume for client ${localClientId}:`, error);
            // Could revert local state here if needed
        }
    };

    const handleGroupVolumeAdjust = (streamId: string | null, direction: 'up' | 'down') => {
        if (!streamId) return;
        const adjustment = direction === 'up' ? VOLUME_STEP : -VOLUME_STEP;
        const effectiveBrowserClientId = getBrowserAudioClientId();

        setClients(prevClients => {
            const updatedClients = prevClients.map(c => {
                if (c.currentStreamId === streamId) {
                    const newVolume = Math.max(0, Math.min(100, c.volume + adjustment));

                    // Handle browser audio client locally
                    if (c.id === effectiveBrowserClientId) {
                        browserAudio.setVolume(newVolume);
                    } else {
                        // Determine if remote federated or local
                        const isLocalFederated = c.id.startsWith('server-localhost-');
                        const isRemoteFederated = settings.federation.enabled && c.id.startsWith('server-') && !isLocalFederated;

                        if (isRemoteFederated) {
                            // Remote federated client - use federation API
                            federationService.setVolume(c.id, newVolume).catch(error => {
                                console.error(`Failed to adjust volume for federated client ${c.id}:`, error);
                            });
                        } else {
                            // Local client - use WebSocket API (strip prefix if needed)
                            const localClientId = isLocalFederated ? c.id.replace('server-localhost-', '') : c.id;
                            snapcastService.setClientVolume(localClientId, newVolume).catch(error => {
                                console.error(`Failed to adjust volume for client ${localClientId}:`, error);
                            });
                        }
                    }

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
        const effectiveBrowserClientId = getBrowserAudioClientId();

        if (isMuted) {
            setClients(prevClients =>
                prevClients.map(c => {
                    if (c.currentStreamId === streamId && preMuteGroupVolumes[streamId][c.id] !== undefined) {
                        const restoredVolume = preMuteGroupVolumes[streamId][c.id];

                        // Handle browser audio client locally
                        if (c.id === effectiveBrowserClientId) {
                            browserAudio.setVolume(restoredVolume, false);
                        } else {
                            // Determine if remote federated or local
                            const isLocalFederated = c.id.startsWith('server-localhost-');
                            const isRemoteFederated = settings.federation.enabled && c.id.startsWith('server-') && !isLocalFederated;

                            if (isRemoteFederated) {
                                // Remote federated client - use federation API
                                federationService.setVolume(c.id, restoredVolume, false).catch(error => {
                                    console.error(`Failed to unmute federated client ${c.id}:`, error);
                                });
                            } else {
                                // Local client - unmute on server (strip prefix if needed)
                                const localClientId = isLocalFederated ? c.id.replace('server-localhost-', '') : c.id;
                                snapcastService.setClientVolume(localClientId, restoredVolume, false).catch(error => {
                                    console.error(`Failed to unmute client ${localClientId}:`, error);
                                });
                            }
                        }

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
                        // Handle browser audio client locally
                        if (c.id === effectiveBrowserClientId) {
                            browserAudio.setVolume(0, true);
                        } else {
                            // Determine if remote federated or local
                            const isLocalFederated = c.id.startsWith('server-localhost-');
                            const isRemoteFederated = settings.federation.enabled && c.id.startsWith('server-') && !isLocalFederated;

                            if (isRemoteFederated) {
                                // Remote federated client - use federation API
                                federationService.setVolume(c.id, 0, true).catch(error => {
                                    console.error(`Failed to mute federated client ${c.id}:`, error);
                                });
                            } else {
                                // Local client - mute on server (strip prefix if needed)
                                const localClientId = isLocalFederated ? c.id.replace('server-localhost-', '') : c.id;
                                snapcastService.setClientVolume(localClientId, 0, true).catch(error => {
                                    console.error(`Failed to mute client ${localClientId}:`, error);
                                });
                            }
                        }

                        return {...c, volume: 0};
                    }
                    return c;
                })
            );
        }
    };

    const handleStreamChange = async (clientId: string, streamId: string | null) => {
        console.log('[StreamChange] Request:', {clientId, streamId, federationEnabled: settings.federation.enabled});

        // Handle browser audio client - stop it when stream set to null
        // Compare with effective browser client ID (accounting for federation prefix)
        const effectiveBrowserClientId = getBrowserAudioClientId();
        if (clientId === effectiveBrowserClientId && streamId === null) {
            browserAudio.stop();
            return;
        }

        // Update local state immediately for responsiveness
        setClients(prevClients =>
            prevClients.map(c => (c.id === clientId ? {...c, currentStreamId: streamId} : c))
        );

        // Track this as a user-initiated change to prevent polling from overwriting it
        const timestamp = Date.now();
        setRecentUserChanges({type: 'routing', timestamp, data: {clientId, streamId}});

        // Check if this is a local client (use WebSocket) or remote client (use Federation API)
        const isLocal = isLocalId(clientId);

        // If federation is enabled and client is REMOTE, use federation API
        if (settings.federation.enabled && !isLocal) {
            if (!streamId) {
                return;
            }

            try {
                const result = await federationService.routeClient(clientId, streamId);

                if (result.success) {
                    console.log('[StreamChange] SUCCESS: Remote federated client routed');
                } else {
                    console.error('[StreamChange] Federation routing failed:', result.message);
                    // Revert local state on error
                    setClients(prevClients =>
                        prevClients.map(c => (c.id === clientId ? {...c, currentStreamId: c.currentStreamId} : c))
                    );
                }
            } catch (error) {
                console.error(`Failed to route federated client ${clientId}:`, error);
                // Revert local state on error
                setClients(prevClients =>
                    prevClients.map(c => (c.id === clientId ? {...c, currentStreamId: c.currentStreamId} : c))
                );
            }
            return;
        }

        // Local client - use WebSocket API
        // Strip server prefix if present (e.g., "server-192-168-7-122-")
        const localClientId = stripServerPrefix(clientId);
        const localStreamId = streamId ? stripServerPrefix(streamId) : null;

        console.log('[StreamChange] Using WebSocket API for local client:', {
            originalClientId: clientId,
            localClientId,
            originalStreamId: streamId,
            localStreamId,
            isLocal,
            localServerId: getLocalServer()?.id
        });

        try {
            const groupId = clientGroupMap[localClientId];
            console.log('[StreamChange] Looked up groupId:', groupId, 'for local client:', localClientId);

            if (groupId && localStreamId) {
                console.log('[StreamChange] Calling setGroupStream:', {groupId, streamId: localStreamId});
                await snapcastService.setGroupStream(groupId, localStreamId);
                console.log('[StreamChange] SUCCESS: Stream changed');
            } else if (groupId && localStreamId === null) {
                // For setting to "no stream", we might need a different approach
                // This depends on how Snapcast handles idle streams
                // You might need to set it to a default idle stream instead
                console.log('[StreamChange] Skipping: streamId is null');
            } else {
                console.error(`[StreamChange] ERROR: Could not find group for client ${localClientId}. ClientGroupMap:`, clientGroupMap);
            }
        } catch (error) {
            console.error(`Failed to change stream for client ${localClientId}:`, error);

            // Revert local state on error
            setClients(prevClients =>
                prevClients.map(c => (c.id === clientId ? {...c, currentStreamId: c.currentStreamId} : c))
            );
        }
    };

    // Helper to check if a stream is local (belongs to this server)
    const isLocalStream = (stream: Stream): boolean => {
        if (!settings.federation.enabled) return true;

        // In federation mode, check if the stream's server is the local server
        if (!stream.serverId) return true;

        // Local server is identified by serverId containing "localhost" or being marked as local
        const localServer = servers.find(s => s.isLocal || s.id.includes('localhost'));
        return stream.serverId === localServer?.id;
    };

    // Helper to get local stream ID (strip federation prefix if present)
    const getLocalStreamId = (streamId: string): string => {
        if (!settings.federation.enabled) return streamId;

        // Strip any "server-{ip}-" or "server-localhost-" prefix
        const match = streamId.match(/^server-[\d-]+-(.+)$/) || streamId.match(/^server-localhost-(.+)$/);
        return match ? match[1] : streamId;
    };

    // Helper to map WebSocket stream ID to federated stream ID
    // WebSocket sends: "Airplay" → we need to find: "server-192-168-201-133-Airplay"
    const getFederatedStreamId = (localStreamId: string): string => {
        if (!settings.federation.enabled) return localStreamId;

        // Find the local server
        const localServer = servers.find(s => s.isLocal || s.id.includes('localhost'));
        if (!localServer) return localStreamId; // Fallback if server not found yet

        // Construct federated ID: server ID + local stream ID
        return `${localServer.id}-${localStreamId}`;
    };

    // Track last play/pause command time to debounce rapid toggling
    // This prevents FIFO pipe issues when pause/play are sent too quickly
    const lastPlayPauseRef = useRef<number>(0);
    const PLAY_PAUSE_DEBOUNCE_MS = 2000; // 2 second minimum between play/pause commands

    const handlePlayPause = async () => {
        if (!currentStream) return;

        // Debounce: prevent rapid play/pause toggling which can break FIFO pipes
        const now = Date.now();
        if (now - lastPlayPauseRef.current < PLAY_PAUSE_DEBOUNCE_MS) {
            console.log(`[PlayPause] Debounced - must wait ${PLAY_PAUSE_DEBOUNCE_MS}ms between commands`);
            return;
        }
        lastPlayPauseRef.current = now;

        try {
            const command = currentStream.isPlaying ? 'pause' : 'play';

            // Check if this is a local or remote stream
            if (settings.federation.enabled && !isLocalStream(currentStream)) {
                // Remote stream - use federation API
                console.log(`[PlayPause] Using federation API for remote stream ${currentStream.id}`);

                // Optimistically update state
                setStreams(prevStreams =>
                    prevStreams.map(s =>
                        s.id === currentStream.id ? {...s, isPlaying: !currentStream.isPlaying} : s
                    )
                );
                const timestamp = Date.now();
                setRecentPlaybackChange({streamId: currentStream.id, timestamp});
                setRecentUserChanges({type: 'playback', timestamp, data: {streamId: currentStream.id}});

                const result = await federationService.controlStream(currentStream.id, command);
                if (!result.success) {
                    console.error(`Federation playback control failed: ${result.message}`);
                    setRecentPlaybackChange(null);
                    setRecentUserChanges(null);
                }
            } else {
                // Local stream - use WebSocket API
                const localStreamId = getLocalStreamId(currentStream.id);

                // Check stream capabilities first
                const capabilities = await snapcastService.getStreamCapabilities(localStreamId);

                if (currentStream.isPlaying) {
                    // Try to pause
                    if (capabilities.canPause) {
                        setStreams(prevStreams =>
                            prevStreams.map(s =>
                                s.id === currentStream.id ? {...s, isPlaying: false} : s
                            )
                        );
                        const timestamp = Date.now();
                        setRecentPlaybackChange({streamId: currentStream.id, timestamp});
                        setRecentUserChanges({type: 'playback', timestamp, data: {streamId: currentStream.id}});
                        await snapcastService.pauseStream(localStreamId);
                    } else {
                        console.warn(`Stream ${currentStream.id} does not support pause`);
                    }
                } else {
                    // Try to play
                    if (capabilities.canPlay) {
                        setStreams(prevStreams =>
                            prevStreams.map(s =>
                                s.id === currentStream.id ? {...s, isPlaying: true} : s
                            )
                        );
                        const timestamp = Date.now();
                        setRecentPlaybackChange({streamId: currentStream.id, timestamp});
                        setRecentUserChanges({type: 'playback', timestamp, data: {streamId: currentStream.id}});
                        await snapcastService.playStream(localStreamId);
                    } else {
                        console.warn(`Stream ${currentStream.id} does not support play`);
                    }
                }
            }
        } catch (error) {
            console.error(`Playback control failed for stream ${currentStream.id}:`, error);
            setRecentPlaybackChange(null);
        }
    };

    const handleSkip = async (direction: 'next' | 'prev') => {
        if (!currentStream) return;

        // Optimistically clear artwork IMMEDIATELY when user clicks skip
        const defaultArtwork = musicNotePlaceholder;

        setStreams(prevStreams =>
            prevStreams.map(s =>
                s.id === currentStream.id
                    ? {...s, currentTrack: {...s.currentTrack, albumArtUrl: defaultArtwork}}
                    : s
            )
        );

        try {
            const command = direction === 'next' ? 'next' : 'previous';

            // Check if this is a local or remote stream
            if (settings.federation.enabled && !isLocalStream(currentStream)) {
                // Remote stream - use federation API
                console.log(`[Skip] Using federation API for remote stream ${currentStream.id}`);
                const result = await federationService.controlStream(currentStream.id, command);
                if (!result.success) {
                    console.error(`Federation skip failed: ${result.message}`);
                }
            } else {
                // Local stream - use WebSocket API
                const localStreamId = getLocalStreamId(currentStream.id);
                const capabilities = await snapcastService.getStreamCapabilities(localStreamId);

                if (direction === 'next') {
                    if (capabilities.canGoNext) {
                        await snapcastService.nextTrack(localStreamId);
                    } else {
                        console.warn(`Stream ${currentStream.id} does not support next track`);
                    }
                } else {
                    if (capabilities.canGoPrevious) {
                        await snapcastService.previousTrack(localStreamId);
                    } else {
                        console.warn(`Stream ${currentStream.id} does not support previous track`);
                    }
                }
            }
        } catch (error) {
            console.error(`Skip ${direction} failed for stream ${currentStream.id}:`, error);
        }
    };

    const handleSeek = async (positionInSeconds: number) => {
        if (!currentStream) return;

        try {
            // Seek is only supported for local streams (no federation API endpoint)
            if (settings.federation.enabled && !isLocalStream(currentStream)) {
                console.warn(`Seek not supported for remote streams in federation mode`);
                return;
            }

            const localStreamId = getLocalStreamId(currentStream.id);
            const capabilities = await snapcastService.getStreamCapabilities(localStreamId);

            if (capabilities.canSeek) {
                const positionInMs = positionInSeconds * 1000;
                updateStreamProgress(currentStream.id, positionInSeconds);
                await snapcastService.seekTo(localStreamId, positionInMs);
                console.log(`Seek to ${positionInSeconds}s for stream ${currentStream.id}`);
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
                    <Icon name="spinner" spin className="text-5xl text-[var(--accent-color)]" />
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
                    <Icon name="triangle-exclamation" className="text-5xl text-red-400" />
                    <p className="mt-4 text-lg text-[var(--text-secondary)]">No clients found</p>
                    <p className="mt-2 text-sm text-[var(--text-muted)]">Unable to load client data from Snapcast
                        server</p>
                </div>
            </div>
        );
    }

    // Toggle visualizer
    const toggleVisualizer = () => {
        setIsVisualizerOpen(!isVisualizerOpen);
    };

    return (
        <>
            <Routes>
                {/* Main UI Route */}
                <Route path="/" element={
                <div
                    className="min-h-screen bg-[var(--bg-primary)] text-[var(--text-primary)] font-sans p-4 md:p-8 flex flex-col">
                    {connectionError && (
                        <div className="w-full max-w-7xl mx-auto mb-4 p-4 bg-red-600/20 border border-red-600/30 rounded-lg">
                            <div className="flex items-center">
                                <Icon name="triangle-exclamation" className="text-red-400 mr-2" />
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
                                <Icon name="tower-broadcast" className="mr-2" />
                                <span>Connected</span>
                            </div>
                        </div>
                        <StreamSelector
                            streams={streams}
                            currentStreamId={myClient.currentStreamId}
                            onSelectStream={(streamId) => handleStreamChange(myClient.id, streamId)}
                            federationEnabled={settings.federation.enabled}
                        />
                    </div>
                    {shouldShowControls ? (
                        <div className="flex-grow flex flex-col">
                            <div className="space-y-6">
                                <NowPlaying
                                    stream={currentStream}
                                    canSeek={streamCapabilities.canSeek}
                                    onSeek={handleSeek}
                                    onAlbumArtClick={toggleVisualizer}
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
                            <Icon name="music" className="text-6xl text-[var(--text-muted)] mb-4" />
                            <h2 className="text-2xl font-semibold text-[var(--text-primary)]">No Stream Selected</h2>
                            <p className="text-[var(--text-secondary)] mt-2">Choose a source to begin.</p>
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
                            federationEnabled={settings.federation.enabled}
                        />
                    </div>
                </div>
            </div>
            <footer
                className="w-full max-w-7xl mx-auto grid grid-cols-3 items-center text-[var(--text-muted)] mt-12 text-sm">
                <div>{/* Spacer */}</div>
                <p className="text-center">Sync Audio Controller &copy; 2024</p>
                <div className="flex justify-end gap-2">
                    <button
                        onClick={() => {
                            setSettingsInitialTab(undefined);
                            setIsSettingsOpen(true);
                        }}
                        className="p-2 rounded-full hover:bg-[var(--bg-secondary)] transition-colors"
                        aria-label="Open Settings"
                    >
                        <Icon name="gear" className="text-lg" />
                    </button>
                </div>
            </footer>
                    {isSettingsOpen && (
                        <SettingsModal
                            settings={settings}
                            onSettingsChange={(newSettings) => {
                                // Use settingsService to update settings (handles server + local storage)
                                settingsService.updateSettings(newSettings).catch((error) => {
                                    console.error('[Settings] Failed to update:', error);
                                });
                            }}
                            onClose={() => {
                                setIsSettingsOpen(false);
                                setSettingsInitialTab(undefined);
                            }}
                            initialTab={settingsInitialTab}
                        />
                    )}
                </div>
            } />
            </Routes>

            {/* Visualizer Overlay */}
            <Visualizer
                stream={currentStream}
                streams={streams}
                settings={settings}
                browserAudioSnapStream={browserAudio.getSnapStream?.() || null}
                browserAudioMuted={browserAudio.state.muted}
                extractedAlbumArtColors={extractedAlbumArtColors}
                onPlayPause={handlePlayPause}
                onSkip={handleSkip}
                onVolumeChange={(vol) => handleVolumeChange(myClient.id, vol)}
                onStreamChange={(streamId) => handleStreamChange(myClient.id, streamId)}
                onOpenSettings={() => {
                    setSettingsInitialTab(undefined);
                    setIsSettingsOpen(true);
                }}
                onOpenVisualizerSettings={() => {
                    setSettingsInitialTab('visualizer');
                    setIsSettingsOpen(true);
                }}
                onStartBrowserAudio={() => {
                    const targetStream = myClient?.currentStreamId || null;
                    setTargetStreamForBrowserAudio(targetStream);
                    browserAudio.start(true); // Start muted for visualizer mode
                }}
                onToggleBrowserAudioMute={() => browserAudio.toggleMute()}
                onClose={() => setIsVisualizerOpen(false)}
                currentVolume={myClient.volume}
                isOpen={isVisualizerOpen}
            />

            {/* Global Settings Modal */}
            {isSettingsOpen && (
                <SettingsModal
                    settings={settings}
                    onSettingsChange={(newSettings) => {
                        // Use settingsService to update settings (handles server + local storage)
                        settingsService.updateSettings(newSettings).catch((error) => {
                            console.error('[Settings] Failed to update:', error);
                        });
                    }}
                    onClose={() => {
                        setIsSettingsOpen(false);
                        setSettingsInitialTab(undefined);
                    }}
                    initialTab={settingsInitialTab}
                />
            )}
        </>
    );
};

export default App;