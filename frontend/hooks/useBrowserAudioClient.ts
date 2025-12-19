import { useState, useEffect, useRef } from 'react';
import { SnapStream } from '../services/snapStreamService';

export interface BrowserAudioClientState {
    isActive: boolean;
    isPlaying: boolean;
    volume: number;
    muted: boolean;
    clientId: string;
}

export function useBrowserAudioClient(host: string) {
    const [state, setState] = useState<BrowserAudioClientState>({
        isActive: false,
        isPlaying: false,
        volume: 100,
        muted: false,
        clientId: SnapStream.getClientId()
    });

    const snapStreamRef = useRef<SnapStream | null>(null);

    // Start the browser audio client
    const start = async (startMuted: boolean = false) => {
        if (snapStreamRef.current) {
            console.warn("Browser audio client already started");
            return;
        }

        try {
            const stream = new SnapStream(host, 1780);
            await stream.start();
            stream.resume(); // Resume audio context (requires user interaction)
            snapStreamRef.current = stream;

            // Set initial volume (muted or unmuted)
            if (startMuted) {
                stream.setVolume(100, true); // Start muted for visualizer
            }

            setState(prev => ({
                ...prev,
                isActive: true,
                isPlaying: true,
                muted: startMuted
            }));

            console.log(`Browser audio client started (${startMuted ? 'muted' : 'unmuted'})`);
        } catch (error) {
            console.error("Failed to start browser audio client:", error);
            throw error;
        }
    };

    // Stop the browser audio client
    const stop = () => {
        if (!snapStreamRef.current) {
            return;
        }

        snapStreamRef.current.stop();
        snapStreamRef.current = null;

        setState(prev => ({
            ...prev,
            isActive: false,
            isPlaying: false
        }));

        console.log("Browser audio client stopped");
    };

    // Set volume
    const setVolume = (volume: number, muted?: boolean) => {
        const isMuted = muted !== undefined ? muted : state.muted;

        if (snapStreamRef.current) {
            snapStreamRef.current.setVolume(volume, isMuted);
        }

        setState(prev => ({
            ...prev,
            volume,
            muted: isMuted
        }));
    };

    // Toggle mute
    const toggleMute = () => {
        const newMuted = !state.muted;

        if (snapStreamRef.current) {
            snapStreamRef.current.setVolume(state.volume, newMuted);
        }

        setState(prev => ({
            ...prev,
            muted: newMuted
        }));
    };

    // Cleanup on unmount
    useEffect(() => {
        return () => {
            if (snapStreamRef.current) {
                snapStreamRef.current.stop();
            }
        };
    }, []);

    // Get muted state (for visualizer UI)
    const isMuted = () => state.muted;

    return {
        state,
        start,
        stop,
        setVolume,
        toggleMute,
        isMuted,
        getSnapStream: () => snapStreamRef.current // Expose for visualizer
    };
}
